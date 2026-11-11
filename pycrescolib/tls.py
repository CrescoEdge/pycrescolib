"""
TLS trust and credentials for every pycrescolib connection: the API socket, dataplane streams and log streams.

Three ways to trust the wsapi server certificate:

* ``fingerprint=``: pin the certificate. wsapi logs its fingerprints at start and writes them to
  ``<agent data>/plugin-data/<wsapi plugin id>/ws.fingerprint``. A SHA-256 (64 hex digits) or SHA-384 (96 hex
  digits) fingerprint, optionally prefixed ``sha256:`` / ``sha384:``, colons and case ignored. Several pins
  (a list, or a comma-separated string) are accepted for a certificate rotation; any one matching is enough.
* ``ca_file=``: a PEM file of trusted certificates. wsapi writes its own certificate to ``ws.crt.pem`` next to
  the fingerprint file, so that file works as a CA file; an operator CA bundle works too. The host name is
  checked against the certificate unless ``check_hostname=False``.
* neither: the system trust store (and ``SSL_CERT_FILE``), with host name checking.

``CRESCO_TLS_FINGERPRINT`` and ``CRESCO_TLS_CA_FILE`` in the environment are used when the code names neither, even
when the code passed ``verify_ssl=False`` (an operator's pin wins, with a WARNING).

``verify_ssl=False`` turns verification off. Whoever answers then receives the service key or the user's
password, so every connection made that way logs a WARNING.

When the code names nothing (no ``verify_ssl``, ``ca_file`` or ``fingerprint``, and no ``CRESCO_TLS_*`` variable),
the connection is verified with the system trust store (:data:`VERIFY_BY_DEFAULT`); pycrescolib 1.3.2 and earlier did
not verify.

How a pin is enforced: before anything is sent, a TLS handshake (no data) reads the server certificate and
compares its fingerprint with the pin; a mismatch raises :class:`CertificateMismatch` and no credential leaves
this process. The real connection then trusts exactly that certificate (it is the only trust anchor), so a
different server on the second connection fails its handshake, also before any credential is sent.

A client certificate (:class:`ClientCertificate`; ``client_cert=`` / ``client_key=`` / ``client_key_password=``, or
``CRESCO_TLS_CLIENT_CERT`` / ``CRESCO_TLS_CLIENT_KEY`` / ``CRESCO_TLS_CLIENT_KEY_PASSWORD``) is presented on every
connection, the pin check's handshake included. wsapi's production profile (``security_profile=production``) accepts
nothing else: the certificate, issued by the operator's client CA, names the caller.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import ssl
from typing import Iterable, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

ENV_FINGERPRINT = "CRESCO_TLS_FINGERPRINT"
ENV_CA_FILE = "CRESCO_TLS_CA_FILE"
ENV_CLIENT_CERT = "CRESCO_TLS_CLIENT_CERT"
ENV_CLIENT_KEY = "CRESCO_TLS_CLIENT_KEY"
ENV_CLIENT_KEY_PASSWORD = "CRESCO_TLS_CLIENT_KEY_PASSWORD"

#: Whether a connection whose code names no trust setting verifies the certificate (with the system trust store).
#: True since 1.4.0: such a connection is verified, and against a self-signed wsapi it fails until a pin or CA file is
#: given (fingerprint=, ca_file=, CRESCO_TLS_FINGERPRINT, CRESCO_TLS_CA_FILE). 1.3.2 and earlier did not verify.
#: An explicit ``verify_ssl=False`` turns verification off and logs a WARNING on every connection.
VERIFY_BY_DEFAULT = True

_unverified_default_warned = False


def _warn_unverified_default(url: str) -> None:
    """Once per process: connections that name no trust setting are not verified, because code set VERIFY_BY_DEFAULT
    to False. Before 1.5.0 that was silent."""
    global _unverified_default_warned
    if _unverified_default_warned:
        return
    _unverified_default_warned = True
    logger.warning(
        f"TLS certificate verification is OFF for {url} and every other connection that names no trust setting "
        f"(pycrescolib.tls.VERIFY_BY_DEFAULT was set to False): the credentials go to whoever answers. Pin the wsapi "
        f"certificate (fingerprint=..., CRESCO_TLS_FINGERPRINT) or trust it with ca_file=... (CRESCO_TLS_CA_FILE). "
        f"This is logged once per process.")


_HEX = re.compile(r"^[0-9a-f]+$")
_DIGESTS = {64: "sha256", 96: "sha384"}


class TLSConfigError(ValueError):
    """The trust settings are unusable (a malformed fingerprint, an unreadable CA file, conflicting options)."""


class CertificateVerificationError(ConnectionError):
    """The wsapi server certificate is not trusted; nothing was sent to the server."""


class CertificateMismatch(CertificateVerificationError):
    """The wsapi server certificate does not match the pinned fingerprint; nothing was sent to the server."""


def normalize_fingerprint(value: str) -> Tuple[str, str]:
    """Return ``(algorithm, lowercase hex)`` for a pin such as ``sha384:AB:CD:...`` or bare hex.

    Raises:
        TLSConfigError: the value is not a SHA-256 or SHA-384 fingerprint.
    """
    if not isinstance(value, str) or not value.strip():
        raise TLSConfigError("empty TLS fingerprint")
    v = value.strip().lower()
    algo = None
    if ":" in v:
        head, rest = v.split(":", 1)
        head = head.replace("-", "")
        if head in ("sha256", "sha384"):
            algo, v = head, rest
    hexpart = v.replace(":", "").replace(" ", "")
    if not _HEX.match(hexpart):
        raise TLSConfigError(f"TLS fingerprint is not hexadecimal: {value!r}")
    by_len = _DIGESTS.get(len(hexpart))
    if by_len is None:
        raise TLSConfigError(f"TLS fingerprint has {len(hexpart)} hex digits; SHA-256 has 64 and SHA-384 has 96")
    if algo is not None and algo != by_len:
        raise TLSConfigError(f"TLS fingerprint is labelled {algo} but has the length of {by_len}")
    return by_len, hexpart


def fingerprint(der: bytes, algorithm: str) -> str:
    """The lowercase hex digest of a DER certificate."""
    return hashlib.new(algorithm, der).hexdigest()


def format_fingerprint(der: bytes, algorithm: str = "sha256") -> str:
    """``sha256:AB:CD:...`` for display (the form wsapi publishes)."""
    h = fingerprint(der, algorithm).upper()
    return algorithm + ":" + ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _parse_pins(pins: Union[None, str, Sequence[str]]) -> List[Tuple[str, str]]:
    if pins is None:
        return []
    if isinstance(pins, str):
        items = [p for p in pins.split(",") if p.strip()]
    else:
        items = list(pins)
    if not items:
        raise TLSConfigError("empty TLS fingerprint")
    return [normalize_fingerprint(p) for p in items]


class ClientCertificate:
    """The client certificate every connection presents (mutual TLS; wsapi's production profile requires one).

    Args:
        cert: a PEM file with the certificate, then its chain (intermediates); or a PKCS12 file (``.p12`` / ``.pfx``,
            or any file that is not PEM) holding the key, the certificate and its chain.
        key: the PEM private key (PKCS#8 or traditional), when ``cert`` is PEM; it may be encrypted.
        password: the key's (or the PKCS12 file's) password, if any.

    The files are read once, here; a PKCS12 file is converted in memory and handed to TLS through owner-only temporary
    files under a random passphrase, deleted at once. ``repr`` names the certificate, never the key or the password.

    Raises:
        TLSConfigError: a file is missing or unreadable, the password is wrong, or the key is not the certificate's.
    """

    def __init__(self, cert: str, key: Optional[str] = None, password: Optional[str] = None):
        if not cert or not os.path.isfile(cert):
            raise TLSConfigError(f"client certificate {cert!r} does not exist")
        if key is not None and not os.path.isfile(key):
            raise TLSConfigError(f"client key {key!r} does not exist")
        with open(cert, "rb") as f:
            data = f.read()
        pkcs12 = cert.lower().endswith((".p12", ".pfx")) or (key is None and b"-----BEGIN" not in data)
        self._pem_chain: bytes
        self._pem_key: bytes
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.serialization import pkcs12 as p12
            pw = password.encode("utf-8") if password is not None else None
            if pkcs12:
                k, c, extra = p12.load_key_and_certificates(data, pw)
                if k is None or c is None:
                    raise TLSConfigError(f"PKCS12 file {cert!r} holds no key and certificate")
                chain = [c] + list(extra or [])
            else:
                if key is None:
                    raise TLSConfigError("a PEM client certificate needs its key (client_key=, or CRESCO_TLS_CLIENT_KEY)")
                with open(key, "rb") as f:
                    k = serialization.load_pem_private_key(f.read(), pw)
                blocks = re.findall(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", data, re.S)
                if not blocks:
                    raise TLSConfigError(f"client certificate {cert!r} holds no PEM certificate")
                chain = [x509.load_pem_x509_certificate(b) for b in blocks]
            self._leaf = chain[0]
            self._pem_chain = b"".join(x.public_bytes(serialization.Encoding.PEM) for x in chain)
            self._pass = base64.urlsafe_b64encode(os.urandom(24))
            self._pem_key = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.BestAvailableEncryption(self._pass))
        except TLSConfigError:
            raise
        except (ValueError, TypeError, OSError) as e:
            raise TLSConfigError(f"client certificate {cert!r} cannot be used: {e}") from e
        self.path = cert
        self.apply(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))       # fails now, not at the first connection

    @classmethod
    def from_environment(cls) -> Optional["ClientCertificate"]:
        """The client certificate named by ``CRESCO_TLS_CLIENT_CERT`` (and ``_KEY``, ``_KEY_PASSWORD``), or None."""
        cert = os.environ.get(ENV_CLIENT_CERT) or None
        if cert is None:
            return None
        return cls(cert, os.environ.get(ENV_CLIENT_KEY) or None, os.environ.get(ENV_CLIENT_KEY_PASSWORD) or None)

    def apply(self, ctx: ssl.SSLContext) -> None:
        """Present this certificate on connections made with ``ctx``."""
        import tempfile
        d = tempfile.mkdtemp(prefix="pycrescolib-client-")
        try:
            os.chmod(d, 0o700)
            cpath, kpath = os.path.join(d, "chain.pem"), os.path.join(d, "key.pem")
            for path, data in ((cpath, self._pem_chain), (kpath, self._pem_key)):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
            try:
                ctx.load_cert_chain(cpath, kpath, password=self._pass)
            except ssl.SSLError as e:
                raise TLSConfigError(f"client certificate {self.path!r}: the key is not the certificate's ({e})") from e
        finally:
            for name in ("chain.pem", "key.pem"):
                try:
                    os.remove(os.path.join(d, name))
                except OSError:
                    pass
            os.rmdir(d)

    def fingerprint(self) -> str:
        """``sha256:<hex>`` of the client certificate (what wsapi's deny list names)."""
        from cryptography.hazmat.primitives import hashes
        return "sha256:" + self._leaf.fingerprint(hashes.SHA256()).hex()

    def __repr__(self) -> str:
        return f"ClientCertificate({self._leaf.subject.rfc4514_string()}, {self.fingerprint()[:23]}...)"


class TrustSettings:
    """How a connection decides whether the wsapi server certificate is trusted.

    Args:
        verify: True verifies (with ``ca_file``, ``fingerprint``, the ``CRESCO_TLS_*`` environment or the system
            trust store); False turns verification off (a WARNING on every connection); None (the default) verifies
            when a trust setting is given and otherwise follows :data:`VERIFY_BY_DEFAULT`.
        ca_file: PEM file of trusted certificates.
        fingerprint: pinned certificate fingerprint(s) (SHA-256 or SHA-384).
        check_hostname: with ``ca_file`` or the system trust store, check the host name (default True). A pin
            identifies the certificate itself, so it never checks the host name.
        use_env: fall back to ``CRESCO_TLS_FINGERPRINT`` / ``CRESCO_TLS_CA_FILE`` when neither is given, and to
            ``CRESCO_TLS_CLIENT_CERT`` when no client certificate is.
        client_cert: a :class:`ClientCertificate` every connection presents (mutual TLS), or None.
    """

    def __init__(self, verify: Optional[bool] = None, ca_file: Optional[str] = None,
                 fingerprint: Union[None, str, Sequence[str]] = None, check_hostname: bool = True,
                 use_env: bool = True, client_cert: Optional["ClientCertificate"] = None):
        if client_cert is None and use_env:
            client_cert = ClientCertificate.from_environment()
        self.client_cert = client_cert
        if verify is False and (ca_file or fingerprint):
            raise TLSConfigError("verify_ssl=False cannot be combined with ca_file or fingerprint")
        if use_env and ca_file is None and fingerprint is None:
            env_fp = os.environ.get(ENV_FINGERPRINT) or None
            env_ca = os.environ.get(ENV_CA_FILE) or None
            if env_fp or env_ca:
                if verify is False:
                    # an operator's pin is never dropped by code that turned verification off (the GaiaKeep profile's
                    # "verify_ssl": false, for one): the pin wins, and the service key never goes to an impostor
                    logger.warning(f"verify_ssl=False is overridden: {ENV_FINGERPRINT if env_fp else ENV_CA_FILE} is "
                                   f"set, so the wsapi certificate is verified against it")
                    verify = None
                fingerprint, ca_file = env_fp, env_ca
        # an explicit opt-out warns on every connection; an unverified default (VERIFY_BY_DEFAULT=False) once per process
        self._unspecified = verify is None and not ca_file and not fingerprint
        if verify is None:
            verify = True if (ca_file or fingerprint) else VERIFY_BY_DEFAULT
        self.verify = bool(verify)
        self.ca_file = ca_file
        self.pins = _parse_pins(fingerprint)
        self.check_hostname = bool(check_hostname)
        if ca_file is not None:
            if not os.path.isfile(ca_file):
                raise TLSConfigError(f"TLS CA file {ca_file!r} does not exist")
            try:
                ssl.create_default_context(cafile=ca_file)
            except (ssl.SSLError, OSError) as e:
                raise TLSConfigError(f"TLS CA file {ca_file!r} is not a PEM certificate file: {e}") from e

    @property
    def mode(self) -> str:
        if not self.verify:
            return "insecure"
        if self.pins:
            return "fingerprint"
        if self.ca_file:
            return "ca_file"
        return "system"

    def describe(self) -> str:
        mine = f", presenting {self.client_cert!r}" if self.client_cert is not None else ""
        if self.mode == "fingerprint":
            return "pinned " + ", ".join(f"{a}:{h[:16]}..." for a, h in self.pins) + mine
        if self.mode == "ca_file":
            return f"CA file {self.ca_file}" + mine
        if self.mode == "insecure" and self._unspecified:
            return "not verified (no trust setting given)" + mine
        return self.mode + mine

    def matches(self, der: bytes) -> bool:
        """True if the DER certificate matches one of the pins (constant-time compare)."""
        ok = False
        for algo, want in self.pins:
            ok |= hmac.compare_digest(fingerprint(der, algo), want)
        return ok

    def _base_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    async def ssl_context(self, host: str, port: int, url: str, timeout: float = 8.0) -> ssl.SSLContext:
        """The SSL context for one connection to ``host:port``, after any pin check; it presents the client certificate.

        Raises:
            CertificateMismatch: the server certificate does not match the pin.
            CertificateVerificationError: the certificate could not be read for the pin check.
        """
        ctx = await self._server_trust(host, port, url, timeout)
        if self.client_cert is not None:
            self.client_cert.apply(ctx)
        return ctx

    async def _server_trust(self, host: str, port: int, url: str, timeout: float) -> ssl.SSLContext:
        """The SSL context for one connection to ``host:port``, after any pin check.

        Raises:
            CertificateMismatch: the server certificate does not match the pin.
            CertificateVerificationError: the certificate could not be read for the pin check.
        """
        if self.mode == "insecure" and self._unspecified:
            _warn_unverified_default(url)
            ctx = self._base_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        if self.mode == "insecure":
            logger.warning(
                f"TLS certificate verification is DISABLED for {url} (verify_ssl=False): the credentials go to "
                f"whoever answers. Pin the wsapi certificate (fingerprint=..., from ws.fingerprint) or trust it "
                f"with ca_file=... (ws.crt.pem).")
            ctx = self._base_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        if self.mode == "fingerprint":
            der = await fetch_server_certificate(host, port, timeout, self.client_cert)
            if not self.matches(der):
                raise CertificateMismatch(
                    f"wsapi certificate mismatch for {host}:{port}: the pinned fingerprint "
                    f"({', '.join(a + ':' + h for a, h in self.pins)}) does not match the certificate the server "
                    f"presented ({format_fingerprint(der, 'sha256')}, {format_fingerprint(der, 'sha384')}). "
                    f"Nothing was sent. If the wsapi certificate was regenerated, compare the new value in its "
                    f"ws.fingerprint file before pinning it.")
            ctx = self._base_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(cadata=der)
            partial = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", None)
            if partial is not None:
                ctx.verify_flags |= partial
            return ctx
        ctx = ssl.create_default_context(cafile=self.ca_file) if self.ca_file else ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = self.check_hostname
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    def verify_peer(self, der: Optional[bytes], host: str, port: int) -> None:
        """Re-check the certificate of an established connection against the pin (defence in depth)."""
        if self.mode != "fingerprint":
            return
        if der is None or not self.matches(der):
            raise CertificateMismatch(f"wsapi certificate for {host}:{port} changed during the connection")

    def explain(self, err: BaseException, host: str, port: int) -> str:
        """A clear message for a failed handshake."""
        if isinstance(err, CertificateVerificationError):
            return str(err)
        refused = client_certificate_refusal(err, self.client_cert)
        if refused:
            return f"wsapi at {host}:{port} {refused}"
        if isinstance(err, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(err):
            how = {
                "system": "the system trust store does not trust it (wsapi certificates are self-signed by default)",
                "ca_file": f"it does not chain to {self.ca_file} or does not name {host}",
                "fingerprint": "it is not the pinned certificate",
            }.get(self.mode, "")
            return (f"wsapi certificate for {host}:{port} is not trusted: {how} ({err}). Nothing was sent. Pin it "
                    f"with fingerprint=<value of ws.fingerprint> or trust it with ca_file=<path to ws.crt.pem>; "
                    f"both files are in the wsapi plugin data directory on the agent.")
        return f"{err}"


def client_certificate_refusal(err: BaseException, client_cert: Optional["ClientCertificate"]) -> Optional[str]:
    """Why the server refused the TLS connection over the client certificate, or None (another failure)."""
    text = ""
    e: Optional[BaseException] = err
    while e is not None and len(text) < 2000:
        text += " " + str(e) + " " + type(e).__name__
        e = e.__cause__ or e.__context__
    t = text.upper()
    if "CERTIFICATE_REQUIRED" in t or "CERTIFICATE REQUIRED" in t:
        return ("requires a client certificate (its security_profile is production): give client_cert= and client_key= "
                "(or CRESCO_TLS_CLIENT_CERT and CRESCO_TLS_CLIENT_KEY)" if client_cert is None else
                f"refused the client certificate {client_cert!r}")
    if any(a in t for a in ("ALERT_BAD_CERTIFICATE", "ALERT_UNKNOWN_CA", "ALERT_CERTIFICATE_UNKNOWN", "ALERT_CERTIFICATE_EXPIRED",
                            "ALERT_CERTIFICATE_REVOKED", "ALERT_UNSUPPORTED_CERTIFICATE", "ALERT_ACCESS_DENIED")):
        if client_cert is None:                      # wsapi (JDK TLS) answers a missing certificate with bad_certificate
            return ("requires a client certificate (its security_profile is production): give client_cert= and client_key= "
                    f"(or CRESCO_TLS_CLIENT_CERT and CRESCO_TLS_CLIENT_KEY) ({err})")
        return (f"did not accept the client certificate {client_cert!r} at TLS (not issued by its client CA, expired, or "
                f"unusable): {err}")
    return None


async def fetch_server_certificate(host: str, port: int, timeout: float = 8.0,
                                   client_cert: Optional["ClientCertificate"] = None) -> bytes:
    """Complete a TLS handshake with ``host:port``, send nothing, and return the server certificate (DER). The client
    certificate, if any, is presented (a server that requires one would otherwise refuse the handshake)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if client_cert is not None:
        client_cert.apply(ctx)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=host), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise CertificateVerificationError(f"TLS handshake with {host}:{port} timed out after {timeout} s") from e
    except OSError as e:
        raise CertificateVerificationError(f"TLS handshake with {host}:{port} failed: {e}") from e
    try:
        sslobj = writer.get_extra_info("ssl_object")
        der = sslobj.getpeercert(binary_form=True) if sslobj is not None else None
    finally:
        # Nothing was sent: drop the connection at once. A graceful close waits for the server's close_notify, which a
        # server that has seen no request may never send (wsapi does not), so every pinned connection (the API socket,
        # each dataplane and log stream) waited out a 2 s timeout here before it was made.
        writer.transport.abort()
    if not der:
        raise CertificateVerificationError(f"{host}:{port} presented no TLS certificate")
    return der


def peer_certificate(ws) -> Optional[bytes]:
    """The DER server certificate of an open websockets connection, or None."""
    try:
        transport = getattr(ws, "transport", None)
        sslobj = transport.get_extra_info("ssl_object") if transport is not None else None
        return sslobj.getpeercert(binary_form=True) if sslobj is not None else None
    except Exception:
        return None


class AuthenticationError(ConnectionError):
    """wsapi refused the credentials (HTTP 401), refused the caller (403) or is limiting failed attempts (429)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _rejection(err: BaseException) -> Optional[Tuple[int, str]]:
    """(HTTP status, server text) when the WebSocket upgrade was answered with an HTTP error."""
    response = getattr(err, "response", None)          # websockets >= 14: InvalidStatus
    status = getattr(response, "status_code", None) if response is not None else None
    if status is None:
        status = getattr(err, "status_code", None)      # legacy InvalidStatusCode
    if status is None:
        return None
    body = getattr(response, "body", b"") if response is not None else b""
    try:
        text = body.decode("utf-8", "replace").strip()[:200] if isinstance(body, (bytes, bytearray)) else ""
    except Exception:
        text = ""
    return int(status), text


async def connect_websocket(url: str, host: str, port: int, tls: TrustSettings, credentials: Credentials,
                            open_timeout: float = 8.0, **kwargs):
    """Open a wsapi WebSocket with verified TLS and the given credentials.

    Raises:
        CertificateMismatch / CertificateVerificationError: the server certificate is not trusted (nothing sent).
        AuthenticationError: the server answered the upgrade with 401, 403 or 429.
    """
    import websockets  # imported here so tls.py stays importable for configuration checks

    ctx = await tls.ssl_context(host, port, url, timeout=open_timeout)
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url, ssl=ctx, additional_headers=credentials.headers(), **kwargs),
            timeout=open_timeout)
    except ssl.SSLError as e:
        refused = client_certificate_refusal(e, tls.client_cert)
        if refused:
            raise AuthenticationError(f"wsapi at {host}:{port} {refused}") from e
        raise CertificateVerificationError(tls.explain(e, host, port)) from e
    except Exception as e:
        refused = client_certificate_refusal(e, tls.client_cert)
        if refused:
            raise AuthenticationError(f"wsapi at {host}:{port} {refused}") from e
        if _closed_before_http(e):
            # TLS completed but the server closed before answering: with TLS 1.3 a server refuses a missing or unaccepted
            # client certificate after the client's side of the handshake, and asyncio drops the alert. Look once more.
            alert = await _tls_alert(host, port, tls, url)
            refused = client_certificate_refusal(alert, tls.client_cert) if alert is not None else None
            raise AuthenticationError(f"wsapi at {host}:{port} " + (refused or (
                "closed the connection after TLS without answering: it may require a client certificate (its "
                "security_profile is production): give client_cert= and client_key= (or CRESCO_TLS_CLIENT_CERT and "
                "CRESCO_TLS_CLIENT_KEY)" if tls.client_cert is None else
                f"closed the connection after TLS without answering: it may not accept the client certificate "
                f"{tls.client_cert!r} (not issued by its client CA, or expired)"))) from e
        rej = _rejection(e)
        if rej is not None:
            status, text = rej
            what = {401: "refused the credentials", 403: "refused this caller",
                    429: "refused this connection for now"}.get(status, "refused the upgrade")
            raise AuthenticationError(f"wsapi at {host}:{port} {what} (HTTP {status}"
                                      f"{': ' + text if text else ''}) for {credentials!r}", status) from e
        raise
    try:
        tls.verify_peer(peer_certificate(ws), host, port)
    except CertificateMismatch:
        await ws.close()
        raise
    return ws


def _closed_before_http(err: BaseException) -> bool:
    """The connection closed after TLS, before any HTTP response (websockets' InvalidMessage from an EOF)."""
    e: Optional[BaseException] = err
    seen = 0
    while e is not None and seen < 10:
        if isinstance(e, EOFError) and "status line" in str(e):
            return True
        e = e.__cause__ or e.__context__
        seen += 1
    return False


async def _tls_alert(host: str, port: int, tls: "TrustSettings", url: str, timeout: float = 4.0) -> Optional[BaseException]:
    """A plain blocking TLS connection that sends one request line: the SSL error it ends with (the server's alert), or
    None when the server just closes (or answers)."""
    import socket

    ctx = await tls.ssl_context(host, port, url, timeout=timeout)

    def probe():
        try:
            with socket.create_connection((host, port), timeout=timeout) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as s:
                    s.sendall(b"GET / HTTP/1.1\r\nHost: " + host.encode("ascii", "replace") + b"\r\n\r\n")
                    s.recv(1)
            return None
        except ssl.SSLError as e:
            return e
        except OSError:
            return None
    try:
        return await asyncio.get_running_loop().run_in_executor(None, probe)
    except Exception:
        return None


_USER = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


#: An API token (wsapi CredentialTool token add): cwt1_<16 hex id>.<43 base64url characters>
_TOKEN = re.compile(r"cwt1_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}")

#: The environment variable a tool can hand its API token in (instead of code or the command line)
ENV_API_TOKEN = "CRESCO_API_TOKEN"


class Credentials:
    """What a connection authenticates with: an API token, a per-user name and password, or the wsapi service key.

    An API token (``cwt1_...``, made with wsapi's ``CredentialTool token add``) goes as ``Authorization: Bearer``; it
    acts as its user, cannot be guessed, and so is never throttled per user: tools and automation should use one. A
    user name and password go as HTTP Basic (``Authorization`` header, protected by TLS); the legacy service key goes in
    the ``cresco_service_key`` header. ``repr`` never shows the secret.
    """

    def __init__(self, service_key: Optional[str] = None, user: Optional[str] = None,
                 password: Optional[str] = None, token: Optional[str] = None, client_certificate: bool = False):
        given = sum(1 for g in (service_key, token, user or password) if g)
        if given > 1:
            raise ValueError("give one of token, service_key, or user and password")
        self.client_certificate = bool(client_certificate) and given == 0
        if self.client_certificate:
            pass                                    # the TLS client certificate is the credential: no header
        elif token is not None:
            if not _TOKEN.fullmatch(token):
                raise ValueError("an API token looks like cwt1_<16 hex>.<43 base64url characters>")
        elif user is not None or password is not None:
            if not user or not password:
                raise ValueError("per-user credentials need both user and password")
            if not _USER.match(user):
                raise ValueError("user names are 1-128 characters from A-Z a-z 0-9 . _ @ -")
        elif not service_key:
            raise ValueError("credentials needed: token, service_key, user and password, or a client certificate")
        self.user = user
        self._password = password
        self._service_key = service_key
        self._token = token

    @property
    def token_id(self) -> Optional[str]:
        """The API token's id (not secret), or None."""
        return self._token[5:21] if self._token else None

    def headers(self) -> dict:
        if self.client_certificate:
            return {}
        if self._token is not None:
            return {"Authorization": "Bearer " + self._token}
        if self.user is not None:
            token = base64.b64encode(f"{self.user}:{self._password}".encode("utf-8")).decode("ascii")
            return {"Authorization": "Basic " + token}
        return {"cresco_service_key": self._service_key}

    def __repr__(self) -> str:
        if self.client_certificate:
            return "Credentials(client certificate)"
        if self._token is not None:
            return f"Credentials(token={self.token_id}...)"
        return f"Credentials(user={self.user!r})" if self.user else "Credentials(service_key=***)"
