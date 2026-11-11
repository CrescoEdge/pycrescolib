"""
A dataplane handshake wsapi refuses (status 9: the caller's role or tenant, a stream it does not open to this caller;
status 90: it failed starting the listener) is a refusal with a reason. Before 1.5.0 the reply was not read: connect()
waited out its 5 s as for a timeout, and the stream reconnected every 5 s for ever, each attempt refused.
"""
import time

import pytest

from pycrescolib import dataplane as dpmod
from pycrescolib.dataplane import dataplane
from pycrescolib.tls import TrustSettings
from tests.tls_util import WssServer, make_cert

REFUSED = {"status_code": "9", "status_desc": "refused: the dataplane of tenant acme is not open to api:other/bob"}
ACTIVE = {"status_code": "10", "status_desc": "Listener Active"}


@pytest.fixture(scope="module")
def server_cert():
    return make_cert()


def _wait(pred, secs):
    end = time.time() + secs
    while time.time() < end and not pred():
        time.sleep(0.05)
    return pred()


def test_a_refusal_is_recorded_with_its_reason_and_reported():
    told = []
    dp = dataplane("localhost", 8282, "stream", "key", refused_callback=told.append)
    dp._on_activation(REFUSED)
    assert not dp.is_active()
    assert dp.handshake_refused == REFUSED["status_desc"]
    assert "status 9" in dp.last_error and "tenant acme" in dp.last_error
    assert told == [REFUSED["status_desc"]]
    assert dp._handshake_retry_pending()
    assert dp.send("x") == "dropped" and "refused its handshake" in dp.last_send_error


@pytest.mark.parametrize("reply,reason", [
    ({"status_code": "90", "status_desc": "broker not ready"}, "broker not ready"),
    ({"status_code": "9"}, "status 9"),
    ({"status_code": "soon"}, "an activation reply this client cannot read"),
    ({}, "status 0"),
])
def test_every_reply_that_is_not_active_is_a_refusal(reply, reason):
    dp = dataplane("localhost", 8282, "stream", "key", callback=lambda m: None)
    dp._on_activation(reply)
    assert not dp.is_active() and dp.handshake_refused == reason


def test_the_wait_doubles_to_a_minute_and_starts_over_after_an_activation():
    dp = dataplane("localhost", 8282, "stream", "key")
    waits = []
    for _ in range(6):
        dp._on_activation(REFUSED)
        waits.append(round(dp._refused_retry_at - time.monotonic()))
    assert waits == [5, 10, 20, 40, 60, 60]
    dp._on_activation(ACTIVE)
    assert dp.is_active()
    dp._on_activation(REFUSED)
    assert round(dp._refused_retry_at - time.monotonic()) == 5


def test_connect_answers_at_once_with_the_reason_and_does_not_reconnect_every_five_seconds(server_cert):
    with WssServer(server_cert, dataplane_activation=lambda n: REFUSED) as srv:
        dp = dataplane("127.0.0.1", srv.port, "stream", "sk-test", tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        try:
            t0 = time.time()
            assert dp.connect() is False
            assert time.time() - t0 < 3.0, "a refusal must not wait out the 5 s activation timeout"
            assert dp.handshake_refused == REFUSED["status_desc"]
            assert "refused the dataplane handshake" in dp.last_error
            time.sleep(3.5)                             # before: the monitor reconnected 2 s after the start
            assert srv.paths.count("/api/dataplane") == 1
            assert _wait(lambda: dp.ws is None, 1.0), "the refused socket is closed, not left open at wsapi"
        finally:
            dp.close()


def test_a_refused_stream_tries_again_and_activates_when_wsapi_accepts_it(server_cert, monkeypatch):
    monkeypatch.setattr(dpmod, "HANDSHAKE_REFUSED_RETRY_S", 0.2)
    with WssServer(server_cert, dataplane_activation=lambda n: REFUSED if n == 1 else ACTIVE) as srv:
        got = []
        dp = dataplane("127.0.0.1", srv.port, "stream", "sk-test", callback=got.append,
                       tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        try:
            assert dp.connect() is False
            assert _wait(dp.is_active, 8.0), dp.last_error
            assert dp.handshake_refused is None
            assert dp.send("hello")
            assert _wait(lambda: got == ["hello"], 3.0)
        finally:
            dp.close()
