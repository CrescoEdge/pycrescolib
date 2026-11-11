"""A local wss server standing in for wsapi, and throwaway certificates, for the TLS and credential tests."""
import asyncio
import datetime
import ipaddress
import json
import os
import ssl
import tempfile
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from websockets.asyncio.server import serve
from websockets.http11 import Response
from websockets.datastructures import Headers


def _name(org, unit, cn):
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                      x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


class Cert:
    """A key and certificate, written as PEM files in a private temp dir."""

    def __init__(self, cert, key, issuer_key=None):
        self.cert = cert
        self.key = key
        self.dir = tempfile.mkdtemp(prefix="pycrescolib-tls-")
        self.cert_pem = os.path.join(self.dir, "cert.pem")
        self.key_pem = os.path.join(self.dir, "key.pem")
        with open(self.cert_pem, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(self.key_pem, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))

    @property
    def der(self):
        return self.cert.public_bytes(serialization.Encoding.DER)

    def fingerprint(self, algo="sha256", colons=True):
        h = self.cert.fingerprint(hashes.SHA256() if algo == "sha256" else hashes.SHA384()).hex().upper()
        return algo + ":" + (":".join(h[i:i + 2] for i in range(0, len(h), 2)) if colons else h)


def make_cert(region="region-a", agent="agent-a", plugin="plugin/7", sans=("127.0.0.1", "localhost"),
              issuer=None, ca=False):
    """EC P-384 / SHA-384 certificate shaped like wsapi's (O=region, OU=agent, CN=plugin). Self-signed unless
    ``issuer`` (a Cert made with ca=True) signs it."""
    key = ec.generate_private_key(ec.SECP384R1())
    subject = _name(region, agent, plugin) if not ca else x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    alt = []
    for s in sans:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            alt.append(x509.DNSName(s))
    b = (x509.CertificateBuilder().subject_name(subject)
         .issuer_name(issuer.cert.subject if issuer else subject)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if alt and not ca:
        b = b.add_extension(x509.SubjectAlternativeName(alt), critical=False)
    if ca:
        b = b.add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                          content_commitment=False, key_encipherment=False, data_encipherment=False,
                                          key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
    else:
        b = b.add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False,
                                          content_commitment=False, key_encipherment=False, data_encipherment=False,
                                          key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
    cert = b.sign(issuer.key if issuer else key, hashes.SHA384())
    return Cert(cert, key)


class WssServer:
    """wss on 127.0.0.1:<random port>. Records every HTTP upgrade request (headers) it receives.

    /api/apisocket echoes each frame; /api/dataplane and /api/logstreamer answer the stream activation
    ({"status_code": "10"}). ``reject_status`` answers every upgrade with that HTTP status instead.
    ``dataplane_activation``: a callable (number of this dataplane connection, from 1) -> the activation reply (a dict)
    for its handshake. ``api_reply``: a callable (frame) -> the reply to it on /api/apisocket.
    ``paths`` records the path of every WebSocket opened.
    """

    def __init__(self, cert: Cert, reject_status=None, chain_pem=None, client_ca=None, dataplane_activation=None,
                 api_reply=None):
        self.cert = cert
        self.dataplane_activation = dataplane_activation
        self.api_reply = api_reply
        self.paths = []             # the path of every WebSocket opened, in order
        self.requests = []          # one dict of headers per HTTP upgrade request received
        self.client_certs = []      # the client certificate (DER) of each upgrade request, when one was presented
        self.reject_status = reject_status
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if chain_pem:
            self._ctx.load_cert_chain(chain_pem, cert.key_pem)
        else:
            self._ctx.load_cert_chain(cert.cert_pem, cert.key_pem)
        if client_ca:
            # like wsapi's production profile: a client certificate from this CA is required on every connection
            self._ctx.verify_mode = ssl.CERT_REQUIRED
            self._ctx.load_verify_locations(client_ca)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop = None
        self.port = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        assert self._ready.wait(5), "test wss server did not start"
        return self

    def __exit__(self, *a):
        self._loop.call_soon_threadsafe(self._stop.set_result, None)
        self._thread.join(5)

    def _process_request(self, connection, request):
        self.requests.append({k.lower(): v for k, v in request.headers.raw_items()})
        sslobj = connection.transport.get_extra_info("ssl_object")
        der = sslobj.getpeercert(binary_form=True) if sslobj is not None else None
        if der:
            self.client_certs.append(der)
        if self.reject_status:
            return Response(self.reject_status, "refused", Headers([("Content-Type", "text/plain")]),
                            b"authentication failed")
        return None

    async def _handler(self, ws):
        path = ws.request.path
        self.paths.append(path)
        if path == "/api/dataplane" and self.dataplane_activation is not None:
            reply = self.dataplane_activation(self.paths.count("/api/dataplane"))
            async for msg in ws:
                await ws.send(json.dumps(reply))
                if str(reply.get("status_code")) != "10":
                    continue                            # as wsapi: not activated, the next frame is a new handshake
                break
            async for msg in ws:
                await ws.send(msg)
            return
        if path == "/api/apisocket" and self.api_reply is not None:
            async for msg in ws:
                await ws.send(self.api_reply(msg))
            return
        if path in ("/api/dataplane", "/api/logstreamer"):
            if path == "/api/logstreamer":
                await ws.send(json.dumps({"status_code": "10", "status_desc": "Listener Active"}))
            async for msg in ws:
                if path == "/api/dataplane":
                    await ws.send(json.dumps({"status_code": "10", "status_desc": "Listener Active"}))
                    path = "/api/dataplane/active"
                else:
                    await ws.send(msg)
        else:
            async for msg in ws:
                await ws.send(msg)

    def _run(self):
        asyncio.set_event_loop(self._loop)

        async def main():
            self._stop = self._loop.create_future()
            async with serve(self._handler, "127.0.0.1", 0, ssl=self._ctx,
                             process_request=self._process_request) as server:
                self.port = server.sockets[0].getsockname()[1]
                self._ready.set()
                await self._stop

        self._loop.run_until_complete(main())
        self._loop.close()
