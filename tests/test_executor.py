"""
Executor submodule tests (parity with the Java client's ExecutorTest).

Locks the outgoing wire messages against the executor plugin's contract (executor e5b91a6: config_process with
stdin, run_process, status_process, end_process, and write_stdin with data_b64 / close_stdin and its 10 / 9 / 8
replies), plugin-id resolution through the global controller, and the dataplane refusing a stream that would write
stdin.
"""
import base64
import json
from collections import deque

import pytest

from pycrescolib.dataplane import dataplane, stdin_stream_refusal
from pycrescolib.executor import executor, EXECUTOR_PLUGIN_NAME, MAX_STDIN_WRITE, StdinWriteError
from pycrescolib.globalcontroller import globalcontroller
from pycrescolib.messaging import messaging_sync
from pycrescolib.utils import compress_param

from tests.conformance_util import CaptureWS


class ScriptedWS(CaptureWS):
    """Records every outgoing message; replies from a queue (default '{}')."""

    def __init__(self):
        super().__init__('{}')
        self.replies = deque()

    def send_direct(self, message, timeout=8.0):
        self.sent.append(message)
        return self.replies.popleft() if self.replies else '{}'


@pytest.fixture
def env():
    ws = ScriptedWS()
    ms = messaging_sync(ws)
    ex = executor(ms, globalcontroller(ms))
    yield ws, ex
    ws.close()


def reply(**kw):
    return json.dumps(kw)


def sent(ws, i):
    return json.loads(ws.sent[i])


def plugins_reply(plugin_id):
    plugins = [{'pluginname': 'io.cresco.example', 'name': 'plugin-other'}]
    if plugin_id is not None:
        plugins.append({'pluginname': EXECUTOR_PLUGIN_NAME, 'name': plugin_id})
    return reply(pluginslist=compress_param(json.dumps({'plugins': plugins})))


def assert_route(m, event_type, action, plugin='pe'):
    info, payload = m['message_info'], m['message_payload']
    assert info['message_type'] == 'global_plugin_msgevent'
    assert info['message_event_type'] == event_type
    assert (info['dst_region'], info['dst_agent'], info['dst_plugin']) == ('R', 'A', plugin)
    assert info['is_rpc'] == 'true'
    assert payload['action'] == action
    return payload


def written(payload):
    return base64.b64decode(payload['data_b64']) if 'data_b64' in payload else b''


def test_config_process_asks_for_stdin_and_reports_it(env):
    ws, ex = env
    ws.replies.append(reply(config_status='true', stdin='true'))
    assert ex.config_process('R', 'A', 'job-1', 'cat', stdin=True, plugin_id='pe') == \
        {'config_status': True, 'stdin': True, 'error_msg': None}
    p = assert_route(sent(ws, 0), 'CONFIG', 'config_process')
    assert (p['stream_name'], p['command'], p['stdin'], p['metrics']) == ('job-1', 'cat', 'true', 'false')
    ws.replies.append(reply(config_status='false', error='true', error_msg='Runner already exist stream_name: job-1'))
    out = ex.config_process('R', 'A', 'job-1', 'cat', plugin_id='pe')
    assert out['config_status'] is False and 'already exist' in out['error_msg']
    assert sent(ws, 1)['message_payload']['stdin'] == 'false'


def test_run_status_and_end(env):
    ws, ex = env
    ws.replies.extend([reply(status='true'), reply(run_status='true'), reply(end_status='true'), reply(status='false')])
    assert ex.run_process('R', 'A', 'job-1', plugin_id='pe') is True
    assert ex.status_process('R', 'A', 'job-1', plugin_id='pe') is True
    assert ex.end_process('R', 'A', 'job-1', plugin_id='pe') is True
    assert ex.run_process('R', 'A', 'job-1', plugin_id='pe') is False
    assert assert_route(sent(ws, 0), 'EXEC', 'run_process')['stream_name'] == 'job-1'
    assert_route(sent(ws, 1), 'CONFIG', 'status_process')
    assert_route(sent(ws, 2), 'CONFIG', 'end_process')


def test_write_stdin_sends_text_with_a_newline_and_bytes_as_they_are(env):
    ws, ex = env
    ws.replies.extend([reply(status='10', status_desc='written')] * 3)
    assert ex.write_stdin('R', 'A', 'job-1', 'ls -l', plugin_id='pe') == 6
    p = assert_route(sent(ws, 0), 'EXEC', 'write_stdin')
    assert p['stream_name'] == 'job-1' and written(p) == b'ls -l\n'
    assert 'close_stdin' not in p and 'data' not in p
    assert ex.write_stdin('R', 'A', 'job-1', 'no newline é', newline=False, plugin_id='pe') == len('no newline é'.encode())
    assert written(sent(ws, 1)['message_payload']) == 'no newline é'.encode()
    assert ex.write_stdin('R', 'A', 'job-1', b'\x00\xff\n', close=True, plugin_id='pe') == 3
    p = sent(ws, 2)['message_payload']
    assert written(p) == b'\x00\xff\n' and p['close_stdin'] == 'true'


def test_large_input_goes_in_ordered_writes_within_the_executors_bound(env):
    ws, ex = env
    data = bytes(range(256)) * ((2 * MAX_STDIN_WRITE + 1000) // 256 + 1)
    ws.replies.extend([reply(status='10')] * 3)
    assert ex.write_stdin('R', 'A', 'job-1', data, close=True, plugin_id='pe') == len(data)
    assert len(ws.sent) == 3
    payloads = [sent(ws, i)['message_payload'] for i in range(3)]
    assert all(len(written(p)) <= MAX_STDIN_WRITE for p in payloads)
    assert b''.join(written(p) for p in payloads) == data
    assert ['close_stdin' in p for p in payloads] == [False, False, True], "stdin closes after the last write only"


def test_close_stdin_sends_no_data(env):
    ws, ex = env
    ws.replies.append(reply(status='10'))
    ex.close_stdin('R', 'A', 'job-1', plugin_id='pe')
    p = assert_route(sent(ws, 0), 'EXEC', 'write_stdin')
    assert p['close_stdin'] == 'true' and 'data_b64' not in p
    assert ex.write_stdin('R', 'A', 'job-1', None, plugin_id='pe') == 0
    assert len(ws.sent) == 1, "nothing to write and nothing to close: no message"


@pytest.mark.parametrize("refusal,desc", [
    ('not-owner', 'refused: only the caller that started the runner, an admin or infra may write its stdin'),
    ('no-stdin', 'this runner takes no stdin (config_process stdin=true)'),
    ('not-running', 'the process is not running, or its stdin is closed')])
def test_a_refusal_raises_with_the_executors_reason(env, refusal, desc):
    ws, ex = env
    ws.replies.append(reply(status='9', refusal=refusal, status_desc=desc))
    with pytest.raises(StdinWriteError) as e:
        ex.write_stdin('R', 'A', 'job-1', 'x', plugin_id='pe')
    assert e.value.refusal == refusal and e.value.status == '9' and e.value.written == 0
    assert refusal in str(e.value)


def test_a_refusal_at_the_agents_door_is_reported_with_its_status(env):
    ws, ex = env
    ws.replies.append(reply(status_code='403', status_desc='unauthorized: write_stdin needs admin or infra (caller api:t/bob[user])'))
    with pytest.raises(StdinWriteError) as e:
        ex.write_stdin('R', 'A', 'job-1', 'x', plugin_id='pe')
    assert e.value.status == '403' and 'needs admin or infra' in str(e.value)


def test_a_refusal_midway_reports_what_was_written(env):
    ws, ex = env
    ws.replies.extend([reply(status='10'), reply(status='9', refusal='not-running', status_desc='closed')])
    with pytest.raises(StdinWriteError) as e:
        ex.write_stdin('R', 'A', 'job-1', b'a' * (MAX_STDIN_WRITE + 10), plugin_id='pe')
    assert e.value.written == MAX_STDIN_WRITE
    assert len(ws.sent) == 2


def test_no_reply_is_an_error_not_a_silent_loss(env):
    ws, ex = env
    ws.replies.append('{}')
    with pytest.raises(StdinWriteError) as e:
        ex.write_stdin('R', 'A', 'job-1', 'x', plugin_id='pe')
    assert e.value.status is None and 'no reply' in str(e.value)
    ws.replies.append(reply(status='8', status_desc='data_b64 is not base64'))
    with pytest.raises(StdinWriteError, match='not base64'):
        ex.write_stdin('R', 'A', 'job-1', 'x', plugin_id='pe')


def test_the_plugin_is_found_by_name(env):
    ws, ex = env
    ws.replies.extend([plugins_reply('plugin-exec'), reply(status='10')])
    ex.write_stdin('R', 'A', 'job-1', 'x')
    assert sent(ws, 0)['message_payload']['action'] == 'listplugins'
    assert_route(sent(ws, 1), 'EXEC', 'write_stdin', plugin='plugin-exec')
    ws.replies.append(plugins_reply(None))
    with pytest.raises(LookupError):
        ex.write_stdin('R', 'A', 'job-1', 'x')
    with pytest.raises(TypeError):
        ex.write_stdin('R', 'A', 'job-1', 42, plugin_id='pe')


def test_the_dataplane_never_writes_stdin():
    for t in ('input', 'input-0123456789abcdef'):
        cfg = json.dumps({'ident_key': 'stream_name', 'ident_id': 'job-1', 'io_type_key': 'type', 'input_id': t})
        assert 'write_stdin' in stdin_stream_refusal(cfg)
        with pytest.raises(ValueError, match='write_stdin'):
            dataplane('localhost', 1, cfg, service_key='k')
    for ok in (json.dumps({'ident_key': 'stream_name', 'ident_id': 'job-1', 'io_type_key': 'type', 'input_id': 'output'}),
               json.dumps({'ident_key': 'stream_name', 'ident_id': 'job-1', 'io_type_key': 'kind', 'input_id': 'input'}),
               "stream_name='job-1'", 'job-1'):
        assert stdin_stream_refusal(ok) is None
        dataplane('localhost', 1, ok, service_key='k')
