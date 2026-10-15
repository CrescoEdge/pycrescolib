"""
Stunnel submodule tests (parity with the Java client's StunnelTest).

Locks the outgoing wire messages against the stunnel plugin's real PluginExecutor contract
(action names, MsgEvent type, action_* params, routing) and the reply decode path, including
plugin-id auto-resolution through the global controller and deploy_plugin (pluginadd / pluginupload).
"""
import json
from collections import deque

import pytest

from pycrescolib.agents import agents
from pycrescolib.globalcontroller import globalcontroller
from pycrescolib.messaging import messaging_sync
from pycrescolib.stunnel import stunnel, STUNNEL_PLUGIN_NAME, STUNNEL_EMBEDDED_JAR
from pycrescolib.utils import compress_param, decompress_param, get_jar_info

from tests.conformance_util import CaptureWS, JAR_PATH


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
    st = stunnel(ms, globalcontroller(ms), agents(ms))
    yield ws, st
    ws.close()


def reply(**kw):
    return json.dumps(kw)


def plugins_reply(plugin_id):
    plugins = [{'pluginname': 'io.cresco.example', 'name': 'plugin-other'}]
    if plugin_id is not None:
        plugins.append({'pluginname': STUNNEL_PLUGIN_NAME, 'name': plugin_id})
    return reply(pluginslist=compress_param(json.dumps({'plugins': plugins})))


def agent_plugins_reply(plugin_id):
    """The agent's own pluginlist reply (rows carry plugin_id / pluginname)."""
    rows = [{'pluginname': 'io.cresco.example', 'plugin_id': 'plugin-other'}]
    if plugin_id is not None:
        rows.append({'pluginname': STUNNEL_PLUGIN_NAME, 'plugin_id': plugin_id})
    return reply(status_code='10', plugin_list=compress_param(json.dumps(rows)))


def sent(ws, i):
    return json.loads(ws.sent[i])


def assert_plugin_route(m, event_type, action, region, agent, plugin):
    info, payload = m['message_info'], m['message_payload']
    assert info['message_type'] == 'global_plugin_msgevent'
    assert info['message_event_type'] == event_type
    assert (info['dst_region'], info['dst_agent'], info['dst_plugin']) == (region, agent, plugin)
    assert info['is_rpc'] == 'true'
    assert payload['action'] == action


def test_create_tunnel_optional_params(env):
    ws, st = env
    cfg = {'stunnel_id': 't1', 'src_port': '2222'}
    ws.replies.append(reply(status='10', stunnel_id='t1', stunnel_config=compress_param(json.dumps(cfg))))
    out = st.create_tunnel('t1', 'R', 'A', '2222', 'R2', 'B', 'localhost', '22', '65536',
                           src_plugin_id='ps', dst_plugin_id='pd', watchdog_timeout='5000',
                           performance_report_rate='1000')
    assert out == cfg
    m = sent(ws, 0)
    assert_plugin_route(m, 'CONFIG', 'configsrctunnel', 'R', 'A', 'ps')
    p = m['message_payload']
    assert p['action_dst_plugin'] == 'pd' and p['action_buffer_size'] == '65536'
    assert p['action_watchdog_timeout'] == '5000' and p['action_performance_report_rate'] == '1000'


def test_create_tunnel_omits_unset_tuning(env):
    ws, st = env
    st.create_tunnel('t1', 'R', 'A', '2222', 'R2', 'B', 'localhost', '22', None,
                     src_plugin_id='ps', dst_plugin_id='pd')
    p = sent(ws, 0)['message_payload']
    assert 'action_buffer_size' not in p
    assert 'action_watchdog_timeout' not in p and 'action_performance_report_rate' not in p


def test_tunnel_health_check(env):
    ws, st = env
    ws.replies.extend([reply(status='10'), reply(status='9', status_desc='Tunnel config not found locally for t1')])
    assert st.tunnel_health_check('R', 'A', 't1', 'ps') is True
    assert st.tunnel_health_check('R', 'A', 't1', 'ps') is False
    m = sent(ws, 0)
    assert_plugin_route(m, 'EXEC', 'tunnelhealthcheck', 'R', 'A', 'ps')
    assert m['message_payload']['action_stunnel_id'] == 't1'


def test_tunnel_health_check_without_plugin_is_false(env):
    ws, st = env
    ws.replies.append(plugins_reply(None))
    assert st.tunnel_health_check('R', 'A', 't1') is False
    assert len(ws.sent) == 1          # only the listplugins lookup


def test_get_metrics_resolves_plugin(env):
    ws, st = env
    ws.replies.extend([plugins_reply('plugin-src'), reply(status='10', metrics='{"tunnels":{"t1":{"bytes":5}}}')])
    assert st.get_metrics('R', 'A') == {'tunnels': {'t1': {'bytes': 5}}}
    lookup = sent(ws, 0)
    assert lookup['message_payload']['action'] == 'listplugins'
    m = sent(ws, 1)
    assert_plugin_route(m, 'EXEC', 'getmetrics', 'R', 'A', 'plugin-src')
    assert 'action_stunnel_id' not in m['message_payload']


def test_get_metrics_missing_is_none(env):
    ws, st = env
    ws.replies.append(reply(status='9'))
    assert st.get_metrics('R', 'A', 'ps') is None


def test_set_net_tuning(env):
    ws, st = env
    ws.replies.append(reply(status='10'))
    out = st.set_net_tuning('R', 'A', {'net_socket_buffer_bytes': 4194304, 'net_fc_window_bytes': '1048576'}, 'ps')
    assert out == {'status': '10'}
    m = sent(ws, 0)
    assert_plugin_route(m, 'CONFIG', 'nettuning', 'R', 'A', 'ps')
    assert m['message_payload']['net_socket_buffer_bytes'] == '4194304'   # MsgEvent params are strings
    assert m['message_payload']['net_fc_window_bytes'] == '1048576'


def test_remove_src_and_dst_three_arg(env):
    ws, st = env
    ws.replies.extend([plugins_reply('plugin-src'), reply(status='10'),
                       plugins_reply('plugin-dst'), reply(status='10')])
    assert st.remove_src_tunnel('R', 'A', 't1') == {'status': '10'}
    assert st.remove_dst_tunnel('R2', 'B', 't1') == {'status': '10'}
    assert_plugin_route(sent(ws, 1), 'CONFIG', 'removesrctunnel', 'R', 'A', 'plugin-src')
    assert_plugin_route(sent(ws, 3), 'CONFIG', 'removedsttunnel', 'R2', 'B', 'plugin-dst')
    assert sent(ws, 3)['message_payload']['action_stunnel_id'] == 't1'


def test_remove_tunnel_with_plugin_ids(env):
    ws, st = env
    ws.replies.extend([reply(status='10'), reply(status='10')])
    out = st.remove_tunnel('t1', 'R', 'A', 'R2', 'B', 'ps', 'pd')
    assert out == {'stunnel_id': 't1', 'src_removal': {'status': '10'}, 'dst_removal': {'status': '10'},
                   'fully_removed': True}
    assert len(ws.sent) == 2          # ids given: no lookups
    assert_plugin_route(sent(ws, 0), 'CONFIG', 'removesrctunnel', 'R', 'A', 'ps')
    assert_plugin_route(sent(ws, 1), 'CONFIG', 'removedsttunnel', 'R2', 'B', 'pd')


def test_deploy_plugin_is_noop_when_loaded(env):
    ws, st = env
    ws.replies.append(plugins_reply('plugin-src'))
    assert st.deploy_plugin('R', 'A') == 'plugin-src'
    assert len(ws.sent) == 1


def test_deploy_plugin_adds_embedded_jar_when_missing(env):
    ws, st = env
    ws.replies.extend([plugins_reply(None), agent_plugins_reply(None),
                       reply(status_code='10', pluginid='plugin-new')])
    assert st.deploy_plugin('R', 'A') == 'plugin-new'
    confirm = sent(ws, 1)             # "not loaded" confirmed with the agent before adding
    assert confirm['message_info']['message_type'] == 'global_agent_msgevent'
    assert confirm['message_payload']['action'] == 'pluginlist'
    add = sent(ws, 2)
    info = add['message_info']
    assert info['message_type'] == 'global_agent_msgevent' and info['message_event_type'] == 'CONFIG'
    assert (info['dst_region'], info['dst_agent']) == ('R', 'A')
    assert add['message_payload']['action'] == 'pluginadd'
    configparams = json.loads(decompress_param(add['message_payload']['configparams']))
    assert configparams == {'pluginname': STUNNEL_PLUGIN_NAME, 'jarfile': STUNNEL_EMBEDDED_JAR}


def test_deploy_plugin_uploads_jar(env):
    ws, st = env
    ws.replies.extend([plugins_reply(None), agent_plugins_reply(None),
                       reply(status_code='10', jar_file_path='/agent/repo/x.jar'),
                       reply(status_code='10', pluginid='plugin-up')])
    assert st.deploy_plugin('R', 'A', JAR_PATH) == 'plugin-up'
    assert sent(ws, 2)['message_payload']['action'] == 'pluginupload'
    add = sent(ws, 3)
    configparams = json.loads(decompress_param(add['message_payload']['configparams']))
    jar = get_jar_info(JAR_PATH)
    assert configparams == {'pluginname': STUNNEL_PLUGIN_NAME, 'jarfile': '/agent/repo/x.jar',
                            'version': str(jar['version']), 'md5': str(jar['md5'])}


def test_deploy_plugin_failed_upload_is_none(env):
    ws, st = env
    ws.replies.extend([plugins_reply(None), agent_plugins_reply(None), reply(status_code='9')])
    assert st.deploy_plugin('R', 'A', JAR_PATH) is None
    assert len(ws.sent) == 3          # no pluginadd after a failed upload
