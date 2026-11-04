"""Client certificates (mutual TLS): wsapi's production profile (security_profile=production) accepts nothing else."""
import base64
import os

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from pycrescolib.clientlib import clientlib
from pycrescolib.dataplane import dataplane
from pycrescolib.logstreamer import logstreamer
from pycrescolib.tls import ClientCertificate, Credentials, TLSConfigError, TrustSettings
from tests.tls_util import WssServer, make_cert


@pytest.fixture(scope="module")
def pki():
    server = make_cert()
    ca = make_cert(ca=True)
    client = make_cert(plugin="carol", sans=(), issuer=ca)
    other_ca = make_cert(ca=True)
    stranger = make_cert(plugin="stranger", sans=(), issuer=other_ca)
    return server, ca, client, stranger


def ca_file(ca):
    return ca.cert_pem


def fp(cert):
    return cert.fingerprint("sha384")


def test_a_pem_client_certificate_is_presented_and_no_credential_header_is_sent(pki):
    server, ca, client, _ = pki
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        c = clientlib("127.0.0.1", srv.port, fingerprint=fp(server), client_cert=client.cert_pem, client_key=client.key_pem)
        assert c.connect(), c.last_error
        c.close()
        assert srv.client_certs and srv.client_certs[0] == client.der
        assert "authorization" not in srv.requests[0] and "cresco_service_key" not in srv.requests[0]
        assert repr(c.credentials) == "Credentials(client certificate)"


def test_an_encrypted_key_and_a_pkcs12_file_work_and_a_wrong_password_is_refused_early(pki, tmp_path):
    server, ca, client, _ = pki
    enc = tmp_path / "enc.key"
    enc.write_bytes(client.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.BestAvailableEncryption(b"s3cret-pass")))
    p12 = tmp_path / "client.p12"
    p12.write_bytes(pkcs12.serialize_key_and_certificates(b"carol", client.key, client.cert, [ca.cert],
                                                          serialization.BestAvailableEncryption(b"p12-pass")))
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        for kw in ({"client_cert": client.cert_pem, "client_key": str(enc), "client_key_password": "s3cret-pass"},
                   {"client_cert": str(p12), "client_key_password": "p12-pass"}):
            c = clientlib("127.0.0.1", srv.port, fingerprint=fp(server), **kw)
            assert c.connect(), (kw, c.last_error)
            c.close()
        assert len(srv.client_certs) == 2
    with pytest.raises(TLSConfigError):
        ClientCertificate(client.cert_pem, str(enc), "wrong")
    with pytest.raises(TLSConfigError):
        ClientCertificate(str(p12), password="wrong")
    with pytest.raises(TLSConfigError):
        ClientCertificate(client.cert_pem, make_cert().key_pem)          # another certificate's key
    with pytest.raises(TLSConfigError):
        ClientCertificate(client.cert_pem)                               # a PEM certificate needs its key
    with pytest.raises(TLSConfigError):
        ClientCertificate(str(tmp_path / "missing.pem"), client.key_pem)
    shown = repr(ClientCertificate(str(p12), password="p12-pass"))
    assert "p12-pass" not in shown and "PRIVATE" not in shown and "sha256:" in shown


def test_without_a_client_certificate_the_refusal_says_one_is_required(pki):
    server, ca, client, _ = pki
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        c = clientlib("127.0.0.1", srv.port, "a-service-key", fingerprint=fp(server))
        assert not c.connect()
        # wsapi (JDK TLS) sends the certificate_required alert: "requires a client certificate"; this Python stand-in
        # closes without one, and the client says what it may need
        assert "require a client certificate" in str(c.last_error) or "requires a client certificate" in str(c.last_error), c.last_error
        assert "client_cert=" in str(c.last_error)
        assert srv.requests == [], "nothing reached HTTP"


def test_a_certificate_of_another_ca_is_refused_at_tls(pki):
    server, ca, _, stranger = pki
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        c = clientlib("127.0.0.1", srv.port, fingerprint=fp(server), client_cert=stranger.cert_pem, client_key=stranger.key_pem)
        assert not c.connect()
        assert "client certificate" in str(c.last_error), c.last_error
        assert srv.requests == []


def test_the_environment_names_the_client_certificate(pki, monkeypatch):
    server, ca, client, _ = pki
    monkeypatch.setenv("CRESCO_TLS_CLIENT_CERT", client.cert_pem)
    monkeypatch.setenv("CRESCO_TLS_CLIENT_KEY", client.key_pem)
    monkeypatch.setenv("CRESCO_TLS_FINGERPRINT", fp(server))
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        c = clientlib("127.0.0.1", srv.port)
        assert c.connect(), c.last_error
        c.close()
        assert srv.client_certs[0] == client.der
        assert "presenting ClientCertificate(" in c.tls.describe()


def test_a_token_goes_over_the_client_certificate(pki):
    server, ca, client, _ = pki
    secret = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")      # made at run time, never a literal
    tok = "cwt1_" + os.urandom(8).hex() + "." + secret
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        c = clientlib("127.0.0.1", srv.port, fingerprint=fp(server), token=tok, client_cert=client.cert_pem, client_key=client.key_pem)
        assert c.connect(), c.last_error
        c.close()
        assert srv.requests[0]["authorization"] == "Bearer " + tok and srv.client_certs[0] == client.der


def test_dataplanes_and_log_streams_present_it_too(pki):
    server, ca, client, _ = pki
    tls = TrustSettings(fingerprint=fp(server), client_cert=ClientCertificate(client.cert_pem, client.key_pem))
    cred = Credentials(client_certificate=True)
    with WssServer(server, client_ca=ca_file(ca)) as srv:
        dp = dataplane("127.0.0.1", srv.port, "u:carol:x", None, lambda m: None, tls=tls, credentials=cred)
        assert dp.connect(), dp.last_error
        dp.close()
        ls = logstreamer("127.0.0.1", srv.port, None, lambda m: None, tls=tls, credentials=cred)
        ls.connect()
        ls.close()
        assert len(srv.client_certs) >= 2 and all(d == client.der for d in srv.client_certs)


def test_without_a_client_certificate_some_credential_is_still_required():
    with pytest.raises(ValueError):
        Credentials()
