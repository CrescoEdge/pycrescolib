"""
TLS verification and credentials on every pycrescolib connection (API socket, dataplane, log stream).

The rule these tests hold: a server whose certificate is not trusted never receives an HTTP request, so it never
sees the service key or a user's password. ``WssServer.requests`` records every upgrade request that arrived.
"""
import asyncio
import base64
import logging
import time

import pytest

from pycrescolib import tls
from pycrescolib.clientlib import clientlib
from pycrescolib.dataplane import dataplane
from pycrescolib.logstreamer import logstreamer
from pycrescolib.tls import (AuthenticationError, CertificateMismatch, CertificateVerificationError, Credentials,
                             TLSConfigError, TrustSettings, connect_websocket, normalize_fingerprint)
from tests.tls_util import WssServer, make_cert


@pytest.fixture(scope="module")
def server_cert():
    return make_cert(region="region-a", agent="agent-a", plugin="plugin/7")


@pytest.fixture(scope="module")
def other_cert():
    return make_cert(region="evil", agent="evil", plugin="evil")


@pytest.fixture(autouse=True)
def no_env_trust(monkeypatch):
    monkeypatch.delenv(tls.ENV_FINGERPRINT, raising=False)
    monkeypatch.delenv(tls.ENV_CA_FILE, raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)


def _open(srv, trust, creds=None, path="/api/apisocket"):
    creds = creds or Credentials(service_key="sk-test")

    async def go():
        ws = await connect_websocket(f"wss://127.0.0.1:{srv.port}{path}", "127.0.0.1", srv.port, trust, creds)
        await ws.send("ping")
        reply = await ws.recv()
        await ws.close()
        return reply

    return asyncio.run(go())


# ---- fingerprint parsing -------------------------------------------------------------------------------------

def test_fingerprint_forms(server_cert):
    hex256 = server_cert.fingerprint("sha256", colons=False).split(":", 1)[1].lower()
    assert normalize_fingerprint(server_cert.fingerprint("sha256")) == ("sha256", hex256)
    assert normalize_fingerprint(hex256.upper()) == ("sha256", hex256)
    assert normalize_fingerprint("SHA-256:" + hex256) == ("sha256", hex256)
    assert normalize_fingerprint(server_cert.fingerprint("sha384"))[0] == "sha384"


@pytest.mark.parametrize("bad", ["", "zz", "sha256:abcd", "sha1:" + "a" * 40, "sha384:" + "a" * 64, "a" * 63])
def test_malformed_fingerprints_are_refused(bad):
    with pytest.raises(TLSConfigError):
        normalize_fingerprint(bad)


def test_insecure_cannot_be_combined_with_a_trust_anchor(server_cert):
    with pytest.raises(TLSConfigError):
        TrustSettings(verify=False, fingerprint=server_cert.fingerprint())


def test_a_missing_ca_file_is_refused():
    with pytest.raises(TLSConfigError):
        TrustSettings(ca_file="/nonexistent/ca.pem")


# ---- pinned fingerprint ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("algo", ["sha256", "sha384"])
def test_a_pinned_certificate_connects(server_cert, algo):
    with WssServer(server_cert) as srv:
        assert _open(srv, TrustSettings(fingerprint=server_cert.fingerprint(algo))) == "ping"
        assert srv.requests and srv.requests[0]["cresco_service_key"] == "sk-test"


def test_one_of_several_pins_is_enough(server_cert, other_cert):
    pins = [other_cert.fingerprint(), server_cert.fingerprint("sha384")]
    with WssServer(server_cert) as srv:
        assert _open(srv, TrustSettings(fingerprint=pins)) == "ping"


def test_a_pin_mismatch_fails_before_any_credential_is_sent(server_cert, other_cert):
    with WssServer(other_cert) as srv:
        with pytest.raises(CertificateMismatch) as e:
            _open(srv, TrustSettings(fingerprint=server_cert.fingerprint()))
        assert srv.requests == [], "the impostor received an HTTP request (and the service key)"
    msg = str(e.value)
    assert "mismatch" in msg and other_cert.fingerprint() in msg and "Nothing was sent" in msg


def test_the_pin_comes_from_the_environment(server_cert, monkeypatch):
    monkeypatch.setenv(tls.ENV_FINGERPRINT, server_cert.fingerprint("sha384"))
    trust = TrustSettings()
    assert trust.mode == "fingerprint"
    with WssServer(server_cert) as srv:
        assert _open(srv, trust) == "ping"


# ---- CA file ----------------------------------------------------------------------------------------------------

def test_the_server_certificate_as_a_ca_file_connects(server_cert):
    with WssServer(server_cert) as srv:
        assert _open(srv, TrustSettings(ca_file=server_cert.cert_pem)) == "ping"


def test_a_ca_signed_certificate_connects():
    ca = make_cert(ca=True)
    leaf = make_cert(issuer=ca)
    with WssServer(leaf) as srv:
        assert _open(srv, TrustSettings(ca_file=ca.cert_pem)) == "ping"


def test_a_certificate_from_another_ca_fails_before_any_credential_is_sent(server_cert, other_cert):
    with WssServer(other_cert) as srv:
        with pytest.raises(CertificateVerificationError) as e:
            _open(srv, TrustSettings(ca_file=server_cert.cert_pem))
        assert srv.requests == []
    assert "not trusted" in str(e.value) and "ws.crt.pem" in str(e.value)


def test_the_host_name_is_checked_with_a_ca_file():
    cert = make_cert(sans=("somewhere-else.example",))
    with WssServer(cert) as srv:
        with pytest.raises(CertificateVerificationError):
            _open(srv, TrustSettings(ca_file=cert.cert_pem))
        assert srv.requests == []
        assert _open(srv, TrustSettings(ca_file=cert.cert_pem, check_hostname=False)) == "ping"


def test_the_system_store_does_not_trust_a_self_signed_wsapi(server_cert):
    with WssServer(server_cert) as srv:
        with pytest.raises(CertificateVerificationError) as e:
            _open(srv, TrustSettings(verify=True))
        assert srv.requests == []
    assert "fingerprint=" in str(e.value)


# ---- insecure opt-out -------------------------------------------------------------------------------------------

def test_insecure_connects_and_warns_every_time(server_cert, caplog):
    trust = TrustSettings(verify=False)
    with WssServer(server_cert) as srv, caplog.at_level(logging.WARNING, logger="pycrescolib.tls"):
        _open(srv, trust)
        _open(srv, trust)
    warnings = [r for r in caplog.records if "verification is DISABLED" in r.getMessage()]
    assert len(warnings) == 2


# ---- credentials ------------------------------------------------------------------------------------------------

def test_per_user_credentials_go_as_basic_auth_and_no_service_key(server_cert):
    with WssServer(server_cert) as srv:
        _open(srv, TrustSettings(fingerprint=server_cert.fingerprint()), Credentials(user="alice", password="pw-1"))
        h = srv.requests[0]
    assert "cresco_service_key" not in h
    assert h["authorization"] == "Basic " + base64.b64encode(b"alice:pw-1").decode()


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_refused_credential_is_a_typed_error(server_cert, status):
    with WssServer(server_cert, reject_status=status) as srv:
        with pytest.raises(AuthenticationError) as e:
            _open(srv, TrustSettings(fingerprint=server_cert.fingerprint()), Credentials(user="alice", password="x"))
    assert e.value.status == status and "alice" in str(e.value) and "x'" not in str(e.value)
    assert "authentication failed" in str(e.value), "the server's own reason is quoted"
    assert "repeated failures" not in str(e.value), "a 429 is not always a lockout (it may be the per-user connection cap)"


@pytest.mark.parametrize("kw", [{}, {"user": "a"}, {"password": "p"}, {"service_key": "k", "user": "a", "password": "p"},
                                {"user": "a:b", "password": "p"}])
def test_bad_credential_combinations_are_refused(kw):
    with pytest.raises(ValueError):
        Credentials(**kw)


def test_credentials_never_show_the_secret():
    assert "pw" not in repr(Credentials(user="alice", password="pw")) and "sk" not in repr(Credentials(service_key="sk"))


# ---- the client, its dataplanes and log streams --------------------------------------------------------------

def test_client_reads_identity_from_the_verified_connection(server_cert):
    with WssServer(server_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", fingerprint=server_cert.fingerprint())
        try:
            assert c.connect()
            assert (c.ws_interface.region, c.ws_interface.agent, c.ws_interface.plugin) == ("region-a", "agent-a", "plugin/7")
        finally:
            c.close()


def test_client_against_a_mismatched_server_fails_and_says_why(server_cert, other_cert):
    with WssServer(other_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", fingerprint=server_cert.fingerprint())
        try:
            assert not c.connect()
            assert "mismatch" in c.last_error
        finally:
            c.close()
        assert srv.requests == []


def test_client_without_a_trust_setting_follows_the_default(server_cert, caplog):
    """Until the default flips (tls.VERIFY_BY_DEFAULT), a client that names no trust setting is not verified and
    logs nothing, as in 1.3.2; when it flips, the same client verifies against the system store."""
    with WssServer(server_cert) as srv, caplog.at_level(logging.WARNING, logger="pycrescolib.tls"):
        c = clientlib("127.0.0.1", srv.port, "sk-test")
        try:
            if tls.VERIFY_BY_DEFAULT:
                assert c.tls.mode == "system" and not c.connect()
                assert srv.requests == []
            else:
                assert c.tls.mode == "insecure" and c.connect()
                assert not [r for r in caplog.records if "DISABLED" in r.getMessage()], "the unverified default is silent"
        finally:
            c.close()


def test_verify_ssl_true_uses_the_system_store(server_cert):
    with WssServer(server_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", True)
        try:
            assert c.tls.mode == "system" and not c.connect()
            assert "not trusted" in c.last_error
        finally:
            c.close()
        assert srv.requests == []


def test_a_trust_setting_alone_turns_verification_on(server_cert, other_cert, monkeypatch):
    monkeypatch.setenv(tls.ENV_FINGERPRINT, server_cert.fingerprint())
    with WssServer(other_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test")
        try:
            assert c.tls.mode == "fingerprint" and not c.connect()
        finally:
            c.close()
        assert srv.requests == []


def test_positional_verify_ssl_false_still_works_with_a_warning(server_cert, caplog):
    with WssServer(server_cert) as srv, caplog.at_level(logging.WARNING, logger="pycrescolib.tls"):
        c = clientlib("127.0.0.1", srv.port, "sk-test", False)
        try:
            assert c.connect()
        finally:
            c.close()
    assert any("DISABLED" in r.getMessage() for r in caplog.records)


def _wait(pred, secs=5.0):
    end = time.time() + secs
    while time.time() < end and not pred():
        time.sleep(0.05)
    return pred()


def test_dataplane_pinned_connects_and_mismatch_is_refused(server_cert, other_cert):
    with WssServer(server_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, user="alice", password="pw", fingerprint=server_cert.fingerprint())
        got = []
        dp = c.get_dataplane("stream-1", callback=got.append)
        try:
            assert dp.connect(), dp.last_error
            dp.send("hello")
            assert _wait(lambda: got == ["hello"])
            assert srv.requests[0]["authorization"].startswith("Basic ")
        finally:
            c.close()
    with WssServer(other_cert) as srv:
        dp = dataplane("127.0.0.1", srv.port, "stream-1", "sk-test", callback=lambda m: None,
                       tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        try:
            t0 = time.time()
            assert not dp.connect()
            assert time.time() - t0 < 4.0, "a refused certificate must not wait out the activation timeout"
            assert "mismatch" in dp.last_error
        finally:
            dp.close()
        assert srv.requests == []


def test_dataplane_verifies_with_verify_true_or_the_flipped_default(server_cert):
    with WssServer(server_cert) as srv:
        dp = dataplane("127.0.0.1", srv.port, "s", "sk-test", tls=TrustSettings(verify=True))
        try:
            assert not dp.connect() and "not trusted" in dp.last_error
        finally:
            dp.close()
        assert srv.requests == []
        dp = dataplane("127.0.0.1", srv.port, "s", "sk-test")
        try:
            assert dp.connect() != tls.VERIFY_BY_DEFAULT
        finally:
            dp.close()


def test_logstreamer_pinned_connects_and_mismatch_is_refused(server_cert, other_cert):
    with WssServer(server_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", ca_file=server_cert.cert_pem)
        ls = c.get_logstreamer("logs", callback=lambda m: None)
        try:
            assert ls.connect(), ls.last_error
            assert srv.requests[0]["cresco_service_key"] == "sk-test"
        finally:
            c.close()
    with WssServer(other_cert) as srv:
        ls = logstreamer("127.0.0.1", srv.port, "sk-test", tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        try:
            assert not ls.connect() and "mismatch" in ls.last_error
        finally:
            ls.close()
        assert srv.requests == []


# ---- dataplane close releases its event loop -------------------------------------------------------------------

def test_dataplane_close_closes_its_event_loop(server_cert):
    with WssServer(server_cert) as srv:
        dp = dataplane("127.0.0.1", srv.port, "s", "sk-test", tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        assert dp.connect()
        loop, thread = dp._event_loop, dp._thread
        dp.close()
        assert loop.is_closed(), "close() must close the dataplane's event loop"
        assert not thread.is_alive(), "close() must stop the dataplane's event-loop thread"
        dp.close()  # idempotent


def test_closing_a_dataplane_that_never_connected_closes_its_loop():
    dp = dataplane("127.0.0.1", 1, "s", "sk-test")
    dp.close()
    assert dp._event_loop.is_closed()


def test_a_closed_dataplane_can_connect_again(server_cert):
    with WssServer(server_cert) as srv:
        dp = dataplane("127.0.0.1", srv.port, "s", "sk-test", tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        dp.close()
        try:
            assert dp.connect()
        finally:
            dp.close()


def test_logstreamer_close_closes_its_event_loop(server_cert):
    with WssServer(server_cert) as srv:
        ls = logstreamer("127.0.0.1", srv.port, "sk-test", tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        assert ls.connect()
        loop = ls._event_loop
        ls.close()
        assert loop.is_closed()


# ---- a refused credential or certificate is not retried every few seconds -------------------------------------

def test_streams_back_off_after_a_refused_credential_or_certificate(server_cert, other_cert):
    """wsapi locks an address out after repeated failures: a stream that retried a wrong password every 5 s would
    lock out every client on its host. After a credential, rate-limit or certificate failure it waits a minute."""
    with WssServer(server_cert, reject_status=401) as srv:
        dp = dataplane("127.0.0.1", srv.port, "s", None, callback=lambda m: None,
                       tls=TrustSettings(fingerprint=server_cert.fingerprint()), credentials=Credentials(user="a", password="b"))
        try:
            assert not dp.connect()
            assert dp._permanent_failure_due()
        finally:
            dp.close()
    with WssServer(other_cert) as srv:
        ls = logstreamer("127.0.0.1", srv.port, "sk", tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        try:
            assert not ls.connect()
            assert ls._permanent_failure_due()
        finally:
            ls.close()
    dp = dataplane("127.0.0.1", 1, "s", "sk", tls=TrustSettings(verify=False))   # nothing listens: a transient failure
    try:
        assert not dp.connect()
        assert not dp._permanent_failure_due()
    finally:
        dp.close()


def test_an_operator_pin_or_ca_file_wins_over_verify_ssl_false(server_cert, other_cert, monkeypatch, caplog):
    monkeypatch.setenv(tls.ENV_FINGERPRINT, server_cert.fingerprint("sha384"))
    with caplog.at_level(logging.WARNING, logger="pycrescolib.tls"):
        t = TrustSettings(verify=False)
    assert t.mode == "fingerprint" and t.verify
    assert any("overridden" in r.getMessage() for r in caplog.records)
    with WssServer(server_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", False)          # GaiaKeep's profile: verify_ssl false
        try:
            assert c.connect(), c.last_error
        finally:
            c.close()
    with WssServer(other_cert) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", False)
        try:
            assert not c.connect() and "mismatch" in c.last_error
        finally:
            c.close()
        assert srv.requests == []
    monkeypatch.delenv(tls.ENV_FINGERPRINT)
    monkeypatch.setenv(tls.ENV_CA_FILE, server_cert.cert_pem)
    assert TrustSettings(verify=False).mode == "ca_file"
    with pytest.raises(TLSConfigError):
        TrustSettings(verify=False, fingerprint=server_cert.fingerprint())   # the code's own conflict is still refused


# ---- API tokens (wsapi round 3) -------------------------------------------------------------------------------

def _tok():
    return "cwt1_" + "0123456789abcdef" + "." + "Q" * 43


def test_an_api_token_goes_as_bearer_and_never_shows(server_cert):
    presented = _tok()
    creds = Credentials(token=presented)
    assert creds.headers() == {"Authorization": "Bearer " + presented}
    assert presented[22:] not in repr(creds) and "0123456789abcdef" in repr(creds)
    with WssServer(server_cert) as srv:
        _open(srv, TrustSettings(fingerprint=server_cert.fingerprint()), creds)
        assert srv.requests[0]["authorization"] == "Bearer " + presented
        assert "cresco_service_key" not in srv.requests[0]


@pytest.mark.parametrize("kw", [{"token": "cwt1_short"}, {"token": _tok(), "service_key": "k"},
                                {"token": _tok(), "user": "a", "password": "p"}])
def test_bad_token_combinations_are_refused(kw):
    with pytest.raises(ValueError):
        Credentials(**kw)


def test_a_tool_takes_its_token_from_the_environment(monkeypatch, server_cert):
    monkeypatch.setenv("CRESCO_API_TOKEN", _tok())
    c = clientlib("127.0.0.1", 1, fingerprint=server_cert.fingerprint())
    assert c.credentials.headers()["Authorization"] == "Bearer " + _tok()
    c2 = clientlib("127.0.0.1", 1, "sk-test", fingerprint=server_cert.fingerprint())
    assert "cresco_service_key" in c2.credentials.headers(), "explicit credentials win over the environment"
