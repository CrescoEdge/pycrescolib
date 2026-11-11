"""
The three wrappers that share one send path (agent_msgevent, regional_agent_msgevent, regional_plugin_msgevent) raise
what went wrong, like the global_* calls. Before 1.5.0 they returned {} for a dead socket and for an unanswered RPC,
which a caller reads as "an empty answer".
"""
import asyncio

import pytest
import websockets

from pycrescolib import wc_interface as wc
from pycrescolib.messaging import messaging_sync
from pycrescolib.wc_interface import ws_interface


class ClosedWS:
    async def send(self, message):
        raise websockets.exceptions.ConnectionClosedError(None, None)

    async def recv(self):
        raise websockets.exceptions.ConnectionClosedError(None, None)


class SilentWS:
    """Takes every request and never answers."""

    async def send(self, message):
        pass

    async def recv(self):
        await asyncio.sleep(3600)


def _transport(ws):
    t = ws_interface()
    t._initialize_event_loop()
    t.ws = ws
    t._connected = True
    return t


CALLS = [
    ("agent_msgevent", lambda m, **kw: m.agent_msgevent(True, "EXEC", {"action": "x"}, **kw)),
    ("regional_agent_msgevent", lambda m, **kw: m.regional_agent_msgevent(True, "EXEC", {"action": "x"}, "a1", **kw)),
    ("regional_plugin_msgevent",
     lambda m, **kw: m.regional_plugin_msgevent(True, "EXEC", {"action": "x"}, "a1", "p1", **kw)),
]


@pytest.mark.parametrize("name,call", CALLS)
def test_a_dead_socket_is_a_connection_error_not_an_empty_answer(name, call):
    t = _transport(ClosedWS())
    try:
        m = messaging_sync(t)
        with pytest.raises(ConnectionError):
            call(m)
        with pytest.raises(ConnectionError):               # and it stays an error on the next call
            call(m)
    finally:
        t._loop.call_soon_threadsafe(t._loop.stop)


@pytest.mark.parametrize("name,call", CALLS)
def test_an_unanswered_rpc_is_a_timeout_and_the_socket_stays_usable(name, call):
    t = _transport(SilentWS())
    try:
        m = messaging_sync(t)
        with pytest.raises(TimeoutError):
            call(m, timeout=0.4)
        assert t.connected(), "no answer in time is not a dead socket"
        with pytest.raises(TimeoutError):                  # the next call asks again; it is not refused as broken
            call(m, timeout=0.4)
    finally:
        t._loop.call_soon_threadsafe(t._loop.stop)


def test_a_socket_that_is_replaced_is_closed(monkeypatch):
    """connect_async used to overwrite the socket it held: the old connection, and wsapi's session for it, stayed open."""
    closed = []

    class OldWS:
        async def close(self):
            closed.append("old")

    class NewWS:
        transport = None

    async def fake_connect(url, host, port, tls, credentials, **kwargs):
        assert closed == ["old"], "the old socket is closed before the new one is opened"
        return NewWS()

    monkeypatch.setattr(wc, "connect_websocket", fake_connect)
    t = ws_interface()
    t.url = "wss://127.0.0.1:1/api/apisocket"
    t._tls = wc.TrustSettings(verify=False)
    t._credentials = wc.Credentials(service_key="k")
    t.ws = OldWS()
    assert asyncio.run(t.connect_async())
    assert closed == ["old"] and isinstance(t.ws, NewWS)
