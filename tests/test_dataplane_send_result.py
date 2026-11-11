"""
A dataplane send returns what became of the data: SENT, DROPPED (the stream was not active) or FAILED (the write raised
or did not finish in time). Before 1.5.0 every send returned None, and a send slower than a fixed 5 s tore the stream
down. A fragmented message that lost a fragment is dropped whole.
"""
import asyncio
import time

import pytest

from pycrescolib import dataplane as dpmod
from pycrescolib.dataplane import SendResult, dataplane
from pycrescolib.tls import TrustSettings
from tests.tls_util import WssServer, make_cert


@pytest.fixture(scope="module")
def server_cert():
    return make_cert()


@pytest.fixture
def stream(server_cert):
    """A connected dataplane on an echoing server: (dataplane, text received, binary received)."""
    with WssServer(server_cert) as srv:
        text, binary = [], []
        dp = dataplane("127.0.0.1", srv.port, "stream", "sk-test", callback=text.append, binary_callback=binary.append,
                       tls=TrustSettings(fingerprint=server_cert.fingerprint()))
        try:
            assert dp.connect(), dp.last_error
            yield dp, text, binary
        finally:
            dp.close()


def _wait(pred, secs=3.0):
    end = time.time() + secs
    while time.time() < end and not pred():
        time.sleep(0.02)
    return pred()


def test_only_data_that_is_not_lost_is_true():
    assert SendResult.SENT and SendResult.PENDING
    assert not SendResult.DROPPED and not SendResult.FAILED
    assert SendResult.SENT == "sent" and str(SendResult.FAILED) == "failed"


def test_a_stream_that_never_connected_drops_and_says_why():
    dp = dataplane("localhost", 8282, "stream", "key")
    for result in (dp.send("x"), dp.send_binary(b"x"), dp.send_partial(b"x", True), dp.update_config("r", "a")):
        assert result is SendResult.DROPPED
    assert "not active" in dp.last_send_error
    assert asyncio.run(dp.send_async("x")) is SendResult.DROPPED


def test_text_binary_and_fragments_are_sent(stream):
    dp, text, binary = stream
    assert dp.send("hello") is SendResult.SENT
    assert dp.last_send_error is None
    assert dp.send_binary(b"\x00\x01") is SendResult.SENT
    assert dp.send_partial(b"ab", False) is SendResult.PENDING
    assert dp.send_partial(b"cd", True) is SendResult.SENT
    assert _wait(lambda: text == ["hello"] and binary == [b"\x00\x01", b"abcd"]), (text, binary)
    assert dp.get_metrics()["messages_sent"] == 3


def test_a_write_that_raises_is_failed_and_the_stream_is_no_longer_active(stream):
    dp, _, _ = stream

    class Broken:
        async def send(self, data):
            raise OSError("connection reset by peer")

        async def close(self, *a, **kw):
            pass

    dp.ws = Broken()
    assert dp.send("x") is SendResult.FAILED
    assert "connection reset by peer" in dp.last_send_error
    assert not dp.is_active()
    assert dp.send("y") is SendResult.DROPPED               # nothing is written to a stream that is not active


class Slow:
    def __init__(self, seconds):
        self.seconds = seconds

    async def send(self, data):
        await asyncio.sleep(self.seconds)

    async def close(self, *a, **kw):
        pass


def test_a_send_slower_than_its_limit_is_failed_within_the_limit(stream):
    dp, _, _ = stream
    dp.ws = Slow(30)
    t0 = time.time()
    assert dp.send("x", timeout=0.3) is SendResult.FAILED
    assert time.time() - t0 < 2.0
    assert "0.3 s" in dp.last_send_error
    assert not dp.is_active(), "the frame may be half written: the stream reconnects"


def test_a_slow_send_within_the_limit_is_sent_and_the_stream_stays_up(stream):
    dp, _, _ = stream
    dp.ws = Slow(0.6)                                       # back-pressure: slow, not broken
    assert dp.send("x", timeout=5) is SendResult.SENT
    assert dp.is_active()


def test_the_limit_comes_from_the_stream_the_environment_or_thirty_seconds(monkeypatch):
    monkeypatch.delenv("CRESCO_DATAPLANE_SEND_TIMEOUT", raising=False)
    assert dataplane("localhost", 8282, "s", "k").send_timeout == 30.0 == dpmod.DEFAULT_SEND_TIMEOUT_S
    assert dataplane("localhost", 8282, "s", "k", send_timeout=2).send_timeout == 2.0
    monkeypatch.setenv("CRESCO_DATAPLANE_SEND_TIMEOUT", "120")
    assert dataplane("localhost", 8282, "s", "k").send_timeout == 120.0
    assert dataplane("localhost", 8282, "s", "k", send_timeout=2).send_timeout == 2.0
    for bad in ("soon", "0", "-1"):
        monkeypatch.setenv("CRESCO_DATAPLANE_SEND_TIMEOUT", bad)
        with pytest.raises(ValueError):
            dataplane("localhost", 8282, "s", "k")
    with pytest.raises(ValueError):
        dataplane("localhost", 8282, "s", "k", send_timeout=0)


def test_a_message_that_lost_a_fragment_is_dropped_whole(stream):
    dp, _, binary = stream
    assert dp.send_partial(b"1", False) is SendResult.PENDING
    dp.isActive = False                                     # the stream drops while the message is being built
    assert dp.send_partial(b"2", False) is SendResult.DROPPED
    dp.isActive = True                                      # and is back before the message ends
    assert dp.send_partial(b"3", False) is SendResult.DROPPED
    assert "earlier fragment" in dp.last_send_error
    assert dp.send_partial(b"4", True) is SendResult.DROPPED    # its final fragment ends the dropped message
    assert dp.send_partial(b"5", False) is SendResult.PENDING   # the next message is whole
    assert dp.send_partial(b"6", True) is SendResult.SENT
    assert _wait(lambda: len(binary) >= 1)
    time.sleep(0.3)
    assert binary == [b"56"], "no fragment of the dropped message went out"
