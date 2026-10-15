"""
"Not loaded" vs "couldn't ask" (both clients; mirror of the Java InventoryErrorsTest).

An inventory query that fails -- transport timeout (e.g. right after a global restart), a wsapi
failure reply (status 504 "no reply within ..."), an agent-side status_code 9, or a reply without
the list -- must raise, never look like an empty inventory. And deploy_plugin must never add a
plugin unless the inventory was actually read and confirmed absent (observed before the fix: a
listplugins timeout -> [] -> "not loaded" -> a second stunnel instance).
"""
import json

import pytest

from pycrescolib.agents import agents
from pycrescolib.base_classes import CrescoQueryError
from pycrescolib.globalcontroller import globalcontroller
from pycrescolib.messaging import messaging_sync
from pycrescolib.stunnel import stunnel, STUNNEL_PLUGIN_NAME
from pycrescolib.utils import compress_param

from tests.test_stunnel import ScriptedWS, plugins_reply, agent_plugins_reply, reply

TIMEOUT = object()   # scripted "no reply": send_direct raises TimeoutError


class FailingWS(ScriptedWS):
    def send_direct(self, message, timeout=8.0):
        self.sent.append(message)
        r = self.replies.popleft() if self.replies else '{}'
        if r is TIMEOUT:
            raise TimeoutError("no reply within 8.0 s")
        return r


# wsapi's reply when the fabric does not answer in time (ApiSocketWsHandler.failure)
GATEWAY_TIMEOUT = reply(action='listplugins', status='504', status_desc='no reply within 30000 ms',
                        error='no reply within 30000 ms; the operation may still complete')
AGENT_LIST_FAILED = reply(action='pluginlist', status_code='9', status_desc='Plugins Could Not Be Listed')


@pytest.fixture
def env():
    ws = FailingWS()
    ms = messaging_sync(ws)
    gc, ag = globalcontroller(ms), agents(ms)
    yield ws, gc, ag, stunnel(ms, gc, ag)
    ws.close()


def actions(ws):
    return [json.loads(m)['message_payload'].get('action') for m in ws.sent]


# ---------------------------------------------------------------- listings raise on failure

@pytest.mark.parametrize('failure,exc', [(TIMEOUT, TimeoutError), (GATEWAY_TIMEOUT, CrescoQueryError),
                                         ('{}', CrescoQueryError), ('not json', CrescoQueryError)])
def test_list_plugins_raises_on_failure(env, failure, exc):
    ws, gc, _, _ = env
    ws.replies.append(failure)
    with pytest.raises(exc):
        gc.list_plugins('R', 'A')


def test_find_plugin_propagates_failure_but_answers_none_when_absent(env):
    ws, gc, _, _ = env
    ws.replies.extend([TIMEOUT, plugins_reply(None)])
    with pytest.raises(TimeoutError):
        gc.find_plugin('R', 'A', STUNNEL_PLUGIN_NAME)
    assert gc.find_plugin('R', 'A', STUNNEL_PLUGIN_NAME) is None      # asked: not loaded


def test_wsapi_failure_reason_is_in_the_error(env):
    ws, gc, _, _ = env
    ws.replies.append(GATEWAY_TIMEOUT)
    with pytest.raises(CrescoQueryError, match='no reply within 30000 ms.*status 504'):
        gc.list_plugins('R', 'A')


@pytest.mark.parametrize('failure,exc', [(TIMEOUT, TimeoutError), (AGENT_LIST_FAILED, CrescoQueryError)])
def test_agent_plugin_list_raises_on_failure(env, failure, exc):
    ws, _, ag, _ = env
    ws.replies.extend([failure, failure])
    with pytest.raises(exc):
        ag.list_plugin_agent('R', 'A')
    with pytest.raises(exc):
        ag.find_plugin('R', 'A', STUNNEL_PLUGIN_NAME)


def test_agent_find_plugin_reads_plugin_id(env):
    ws, _, ag, _ = env
    ws.replies.append(agent_plugins_reply('plugin-7'))
    assert ag.find_plugin('R', 'A', STUNNEL_PLUGIN_NAME) == 'plugin-7'


@pytest.mark.parametrize('call', [lambda gc: gc.get_agent_list(), lambda gc: gc.get_region_list(),
                                  lambda gc: gc.get_pipeline_list(),
                                  lambda gc: gc.get_pipeline_id_by_name('p')])
def test_other_inventories_raise_on_failure(env, call):
    ws, gc, _, _ = env
    ws.replies.extend([GATEWAY_TIMEOUT, TIMEOUT])
    with pytest.raises(CrescoQueryError):
        call(gc)
    with pytest.raises(TimeoutError):
        call(gc)


def test_empty_answers_are_still_empty(env):
    ws, gc, _, _ = env
    ws.replies.extend([reply(agentslist=compress_param(json.dumps({'agents': []}))),
                       reply(regionslist=compress_param(json.dumps({'regions': []}))),
                       reply(pipelineinfo=compress_param(json.dumps({'pipelines': []}))),
                       plugins_reply(None)])
    assert gc.get_agent_list() == []
    assert gc.get_region_list() == []
    assert gc.get_pipeline_id_by_name('p') is None
    assert [p['pluginname'] for p in gc.list_plugins('R', 'A')] == ['io.cresco.example']


# ---------------------------------------------------------------- deploy_plugin never blind-adds

@pytest.mark.parametrize('failure,exc', [(TIMEOUT, TimeoutError), (GATEWAY_TIMEOUT, CrescoQueryError),
                                         ('{}', CrescoQueryError)])
def test_deploy_plugin_does_not_add_when_global_inventory_fails(env, failure, exc):
    ws, _, _, st = env
    ws.replies.append(failure)
    with pytest.raises(exc):
        st.deploy_plugin('R', 'A')
    assert actions(ws) == ['listplugins']          # no pluginadd / pluginupload


@pytest.mark.parametrize('failure,exc', [(TIMEOUT, TimeoutError), (AGENT_LIST_FAILED, CrescoQueryError)])
def test_deploy_plugin_does_not_add_when_agent_confirmation_fails(env, failure, exc):
    ws, _, _, st = env
    ws.replies.extend([plugins_reply(None), failure])
    with pytest.raises(exc):
        st.deploy_plugin('R', 'A', 'unused.jar')
    assert actions(ws) == ['listplugins', 'pluginlist']


def test_deploy_plugin_uses_agent_copy_the_global_does_not_list_yet(env):
    # right after a global restart the global's view can lag the agent: never start a second copy
    ws, _, _, st = env
    ws.replies.extend([plugins_reply(None), agent_plugins_reply('plugin-running')])
    assert st.deploy_plugin('R', 'A') == 'plugin-running'
    assert actions(ws) == ['listplugins', 'pluginlist']


def test_deploy_plugin_retry_after_failure_adds_once(env):
    ws, _, _, st = env
    ws.replies.extend([TIMEOUT,
                       plugins_reply(None), agent_plugins_reply(None), reply(status_code='10', pluginid='p1'),
                       plugins_reply('p1')])
    with pytest.raises(TimeoutError):
        st.deploy_plugin('R', 'A')
    assert st.deploy_plugin('R', 'A') == 'p1'
    assert st.deploy_plugin('R', 'A') == 'p1'
    assert actions(ws).count('pluginadd') == 1


# ---------------------------------------------------------------- stunnel lookups

def test_stunnel_lookup_failure_raises_but_absent_plugin_is_empty(env):
    ws, _, _, st = env
    ws.replies.extend([GATEWAY_TIMEOUT, plugins_reply(None)])
    with pytest.raises(CrescoQueryError):
        st.get_tunnel_list('R', 'A')
    assert st.get_tunnel_list('R', 'A') == []      # asked: stunnel not loaded


def test_create_tunnel_lookup_failure_raises_without_configuring(env):
    ws, _, _, st = env
    ws.replies.extend([plugins_reply('ps'), TIMEOUT])
    with pytest.raises(TimeoutError):
        st.create_tunnel('t1', 'R', 'A', '2222', 'R2', 'B', 'localhost', '22')
    assert 'configsrctunnel' not in actions(ws)
