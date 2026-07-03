"""
Reply-parsing tests for the Python client.

The conformance suite locks the *outgoing* message; these lock the *incoming* decode path:
given a canned reply, each method must return the correctly-decoded value (decompress + parse).
"""
import json

from pycrescolib.utils import compress_param, json_serialize
from tests.conformance_util import build


def _client(reply_obj):
    return build(json.dumps(reply_obj))


def test_get_pipeline_list_decodes_compressed_pipelines():
    c = _client({'pipelineinfo': compress_param(json_serialize({'pipelines': [{'pipeline_id': '1', 'pipeline_name': 'p'}]}))})
    assert c['globalcontroller'].get_pipeline_list() == [{'pipeline_id': '1', 'pipeline_name': 'p'}]
    c['ws'].close()


def test_get_pipeline_list_empty_when_missing():
    c = _client({})
    assert c['globalcontroller'].get_pipeline_list() == []
    c['ws'].close()


def test_get_pipeline_status_reads_status_code():
    c = _client({'gpipeline': compress_param(json_serialize({'status_code': 10}))})
    assert c['globalcontroller'].get_pipeline_status('PID') == 10
    c['ws'].close()


def test_get_agent_list_decodes_compressed_agents():
    c = _client({'agentslist': compress_param(json_serialize({'agents': [{'agent_id': 'a1'}]}))})
    assert c['globalcontroller'].get_agent_list() == [{'agent_id': 'a1'}]
    c['ws'].close()


def test_list_plugin_agent_decodes_compressed_list():
    c = _client({'plugin_list': compress_param(json_serialize([{'name': 'plug'}]))})
    assert c['agents'].list_plugin_agent('R', 'A') == [{'name': 'plug'}]
    c['ws'].close()


def test_is_controller_active_true():
    c = _client({'is_controller_active': 'true'})
    assert c['agents'].is_controller_active('R', 'A') is True
    c['ws'].close()


def test_is_controller_active_false_when_absent():
    c = _client({})
    assert c['agents'].is_controller_active('R', 'A') is False
    c['ws'].close()


def test_get_pipeline_id_by_name_matches():
    c = _client({'pipelineinfo': compress_param(json_serialize(
        {'pipelines': [{'pipeline_id': '1', 'pipeline_name': 'alpha'}, {'pipeline_id': '2', 'pipeline_name': 'beta'}]}))})
    assert c['globalcontroller'].get_pipeline_id_by_name('beta') == '2'
    c['ws'].close()


def test_get_global_info_reads_region_and_agent():
    c = _client({'global_region': 'gr', 'global_agent': 'ga'})
    assert c['api'].get_global_info() == ('gr', 'ga')
    c['ws'].close()
