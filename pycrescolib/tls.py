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

``CRESCO_TLS_FINGERPRINT`` and ``CRESCO_TLS_CA_FILE`` in the environment are used when the code names neither.

``verify_ssl=False`` turns verification off. Whoever answers then receives the service key or the user's
password, so every connection made that way logs a WARNING.

When the code names nothing (no ``verify_ssl``, ``ca_file`` or ``fingerprint``, and no ``CRESCO_TLS_*`` variable),
the connection is verified with the system trust store (:data:`VERIFY_BY_DEFAULT`); pycrescolib 1.3.2 and earlier did
not verify.

How a pin is enforced: before anything is sent, a TLS handshake (no data) reads the server certificate and
compares its fingerprint with the pin; a mismatch raises :class:`CertificateMismatch` and no credential leaves
this process. The real connection then trusts exactly that certificate (it is the only trust anchor), so a
different server on the second connection fails its handshake, also before any credential is sent.
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

#: Whether a connection whose code names no trust setting verifies the certificate (with the system trust store).
#: True since 1.4.0: such a connection is verified, and against a self-signed wsapi it fails until a pin or CA file is
#: given (fingerprint=, ca_file=, CRESCO_TLS_FINGERPRINT, CRESCO_TLS_CA_FILE). 1.3.2 and earlier did not verify.
#: An explicit ``verify_ssl=False`` turns verification off and logs a WARNING on every connection.
VERIFY_BY_DEFAULT = True

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
        use_env: fall back to ``CRESCO_TLS_FINGERPRINT`` / ``CRESCO_TLS_CA_FILE`` when neither is given.
    """

    def __init__(self, verify: Optional[bool] = None, ca_file: Optional[str] = None,
                 fingerprint: Union[None, str, Sequence[str]] = None, check_hostname: bool = True,
                 use_env: bool = True):
        if verify is not False and use_env and ca_file is None and fingerprint is None:
            fingerprint = os.environ.get(ENV_FINGERPRINT) or None
            ca_file = os.environ.get(ENV_CA_FILE) or None
        if verify is False and (ca_file or fingerprint):
            raise TLSConfigError("verify_ssl=False cannot be combined with ca_file or fingerprint")
        # an explicit opt-out warns on every connection; an unverified default (VERIFY_BY_DEFAULT=False) is silent
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
        if self.mode == "fingerprint":
            return "pinned " + ", ".join(f"{a}:{h[:16]}..." for a, h in self.pins)
        if self.mode == "ca_file":
            return f"CA file {self.ca_file}"
        if self.mode == "insecure" and self._unspecified:
            return "not verified (no trust setting given)"
        return self.mode

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
        """The SSL context for one connection to ``host:port``, after any pin check.

        Raises:
            CertificateMismatch: the server certificate does not match the pin.
            CertificateVerificationError: the certificate could not be read for the pin check.
        """
        if self.mode == "insecure" and self._unspecified:
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
            der = await fetch_server_certificate(host, port, timeout)
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


async def fetch_server_certificate(host: str, port: int, timeout: float = 8.0) -> bytes:
    """Complete a TLS handshake with ``host:port``, send nothing, and return the server certificate (DER)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
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
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
        except Exception:
            pass
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
        raise CertificateVerificationError(tls.explain(e, host, port)) from e
    except Exception as e:
        rej = _rejection(e)
        if rej is not None:
            status, text = rej
            what = {401: "refused the credentials", 403: "refused this caller",
                    429: "is refusing attempts from this address after repeated failures"}.get(status, "refused the upgrade")
            raise AuthenticationError(f"wsapi at {host}:{port} {what} (HTTP {status}"
                                      f"{': ' + text if text else ''}) for {credentials!r}", status) from e
        raise
    try:
        tls.verify_peer(peer_certificate(ws), host, port)
    except CertificateMismatch:
        await ws.close()
        raise
    return ws


_USER = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


class Credentials:
    """What a connection authenticates with: a per-user name and password, or the wsapi service key.

    A user name and password go as HTTP Basic (``Authorization`` header, protected by TLS); the legacy service
    key goes in the ``cresco_service_key`` header. ``repr`` never shows the secret.
    """

    def __init__(self, service_key: Optional[str] = None, user: Optional[str] = None,
                 password: Optional[str] = None):
        if user is not None or password is not None:
            if not user or not password:
                raise ValueError("per-user credentials need both user and password")
            if not _USER.match(user):
                raise ValueError("user names are 1-128 characters from A-Z a-z 0-9 . _ @ -")
            if service_key:
                raise ValueError("give either service_key or user/password, not both")
        elif not service_key:
            raise ValueError("credentials needed: service_key, or user and password")
        self.user = user
        self._password = password
        self._service_key = service_key

    def headers(self) -> dict:
        if self.user is not None:
            token = base64.b64encode(f"{self.user}:{self._password}".encode("utf-8")).decode("ascii")
            return {"Authorization": "Basic " + token}
        return {"cresco_service_key": self._service_key}

    def __repr__(self) -> str:
        return f"Credentials(user={self.user!r})" if self.user else "Credentials(service_key=***)"
