"""
A control socket the server closed (e.g. a global restart) must surface as ConnectionError and flip
connected() to False -- never an empty reply. Before, websockets' ConnectionClosed escaped as a generic
error that messaging_sync turned into {} while connected() stayed True: the client never reconnected and
its inventory calls read "no plugins" (observed live: list_plugins == [] for the whole restart window).
"""
import pytest
import websockets

from pycrescolib.globalcontroller import globalcontroller
from pycrescolib.messaging import messaging_sync
from pycrescolib.wc_interface import ws_interface


class ClosedWS:
    async def send(self, message):
        raise websockets.exceptions.ConnectionClosedError(None, None)

    async def recv(self):
        raise websockets.exceptions.ConnectionClosedError(None, None)


@pytest.fixture
def transport():
    t = ws_interface()
    t._initialize_event_loop()
    t.ws = ClosedWS()
    t._connected = True
    yield t
    t._loop.call_soon_threadsafe(t._loop.stop)


def test_closed_socket_raises_connection_error_and_reports_disconnected(transport):
    assert transport.connected()
    with pytest.raises(ConnectionError):
        transport.send_direct('{"message_info": {}, "message_payload": {"action": "x"}}', timeout=2.0)
    assert not transport.connected(), "callers must see the dead transport and reconnect"


def test_inventory_on_a_closed_socket_raises_instead_of_answering_empty(transport):
    gc = globalcontroller(messaging_sync(transport))
    with pytest.raises(ConnectionError):
        gc.list_plugins('R', 'A')
    with pytest.raises(ConnectionError):           # and stays an error, not {} on the next call
        gc.find_plugin('R', 'A', 'io.cresco.stunnel')
