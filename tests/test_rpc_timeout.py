"""The client asks the server to wait for an RPC as long as the client itself will."""
import asyncio
import json
import threading

from pycrescolib.wc_interface import ws_interface


def _stubbed():
    ws = ws_interface()
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    ws._loop = loop
    ws.connected = lambda: True
    sent = []

    async def fake_send_receive(message, timeout, rpc_id=None):
        sent.append(message)
        return json.dumps({'client_rpc_id': rpc_id, 'status': '10'})

    ws._send_receive = fake_send_receive
    return ws, loop, sent


def test_rpc_timeout_is_sent_with_the_request():
    ws, loop, sent = _stubbed()
    try:
        ws.send_direct(json.dumps({'message_info': {'is_rpc': 'true'}, 'message_payload': {'action': 'core.publish'}}), timeout=600)
        env = json.loads(sent[0])
        assert env['message_info']['rpc_timeout_ms'] == '599000'
        assert env['message_payload']['client_rpc_id']
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_short_timeouts_still_leave_a_second_floor():
    ws, loop, sent = _stubbed()
    try:
        ws.send_direct(json.dumps({'message_info': {'is_rpc': 'true'}, 'message_payload': {'action': 'x'}}), timeout=1.5)
        assert json.loads(sent[0])['message_info']['rpc_timeout_ms'] == '1000'
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_an_explicit_server_timeout_is_kept():
    ws, loop, sent = _stubbed()
    try:
        ws.send_direct(json.dumps({'message_info': {'is_rpc': 'true', 'rpc_timeout_ms': '5000'}, 'message_payload': {}}), timeout=60)
        assert json.loads(sent[0])['message_info']['rpc_timeout_ms'] == '5000'
    finally:
        loop.call_soon_threadsafe(loop.stop)
