"""
The API socket takes replies up to 64 MiB (wsapi's own limit for that socket). Before 1.5.0 it had websockets' default
of 1 MiB: a larger reply (the inventory of a large fabric) closed the connection with 1009.
"""
import json

import pytest

from pycrescolib import wc_interface as wc
from pycrescolib.clientlib import clientlib
from tests.tls_util import WssServer, make_cert


@pytest.fixture(scope="module")
def server_cert():
    return make_cert()


def _big_reply(size):
    def reply(frame):
        rpc_id = json.loads(frame)["message_payload"]["client_rpc_id"]
        return json.dumps({"client_rpc_id": rpc_id, "blob": "x" * size})
    return reply


def test_a_reply_of_three_mebibytes_arrives(server_cert, monkeypatch):
    monkeypatch.delenv("CRESCO_API_MAX_MESSAGE", raising=False)
    with WssServer(server_cert, api_reply=_big_reply(3 * 1024 * 1024)) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", fingerprint=server_cert.fingerprint())
        try:
            assert c.connect()
            reply = c.messaging.global_controller_msgevent(True, "EXEC", {"action": "inventory"})
            assert len(reply["blob"]) == 3 * 1024 * 1024
            assert c.connected()
        finally:
            c.close()


def test_the_limit_is_configurable_and_a_reply_over_it_is_a_connection_error(server_cert, monkeypatch):
    monkeypatch.setenv("CRESCO_API_MAX_MESSAGE", str(64 * 1024))
    with WssServer(server_cert, api_reply=_big_reply(256 * 1024)) as srv:
        c = clientlib("127.0.0.1", srv.port, "sk-test", fingerprint=server_cert.fingerprint())
        try:
            assert c.connect()
            with pytest.raises(ConnectionError):
                c.messaging.global_controller_msgevent(True, "EXEC", {"action": "inventory"})
        finally:
            c.close()


def test_the_default_is_wsapis_limit_and_a_bad_value_is_refused(monkeypatch):
    monkeypatch.delenv("CRESCO_API_MAX_MESSAGE", raising=False)
    assert wc.api_max_message() == 64 * 1024 * 1024
    monkeypatch.setenv("CRESCO_API_MAX_MESSAGE", "1048576")
    assert wc.api_max_message() == 1048576
    for bad in ("lots", "0", "-5"):
        monkeypatch.setenv("CRESCO_API_MAX_MESSAGE", bad)
        with pytest.raises(ValueError):
            wc.api_max_message()
