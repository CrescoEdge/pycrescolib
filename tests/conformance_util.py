"""
Shared conformance harness for the Python client.

The clients are thin wrappers that build a JSON envelope ({message_info, message_payload})
and hand it to the transport. This harness injects a capturing fake transport, invokes a
public method, and returns the *normalized* outgoing message so it can be compared -- for
regression (against the golden corpus) and for cross-language parity (the Java suite compares
its own output to the same golden).

Normalization makes the comparison content-based, not byte-based:
  * gzip+base64 compressed payload fields are decompressed and JSON-parsed (Python gzip and
    Java Deflater produce different bytes for the same content, so we compare the *content*);
  * comparison is done on parsed objects, so JSON key ordering does not matter.

The CASES list is the canonical set of API calls under test. gen_golden.py turns it into
golden_messages.json; test_conformance.py replays it and asserts against the golden.
"""
import asyncio
import json
import logging
import os
import threading

# The normalizer probes every payload string with decompress_param to detect compressed fields;
# plain strings fail decompression by design, so silence that expected error spam.
logging.getLogger('pycrescolib.utils').setLevel(logging.CRITICAL)

from pycrescolib.messaging import messaging_sync
from pycrescolib.admin import admin
from pycrescolib.api import api
from pycrescolib.agents import agents
from pycrescolib.globalcontroller import globalcontroller
from pycrescolib.utils import decompress_param

# Shared fixture jar (a byte-identical copy lives in the Java repo at
# src/test/resources/conformance/example-plugin.jar) so get_jar_info -> {pluginname, version, md5}
# and the base64 jardata are identical on both sides. Its absolute path is machine-specific, so the
# normalizer replaces it with the token "<JAR_PATH>" (update_plugin_agent embeds the raw path).
JAR_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'example-plugin.jar')


class CaptureWS:
    """Fake transport: records every outgoing JSON message and returns a canned reply."""

    def __init__(self, reply='{}', region='test-region', agent='test-agent', plugin='test-plugin'):
        self.sent = []
        self._reply = reply
        self._region, self._agent, self._plugin = region, agent, plugin
        # background event loop so the non-RPC (send_async) path works in tests
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def send_direct(self, message, timeout=8.0):
        self.sent.append(message)
        return self._reply

    async def send_async(self, message):
        self.sent.append(message)

    def get_region(self):
        return self._region

    def get_agent(self):
        return self._agent

    def get_plugin(self):
        return self._plugin

    def close(self):
        self._loop.call_soon_threadsafe(self._loop.stop)


def build(reply='{}'):
    """Build the submodule handles wired to a fresh capturing transport."""
    ws = CaptureWS(reply)
    ms = messaging_sync(ws)
    return {
        'ws': ws,
        'messaging': ms,
        'admin': admin(ms),
        'api': api(ms),
        'agents': agents(ms),
        'globalcontroller': globalcontroller(ms),
    }


def _normalize_value(value):
    """Canonicalize a payload value: compressed JSON -> parsed object; fixture path -> token."""
    if isinstance(value, str):
        if value == JAR_PATH:
            return '<JAR_PATH>'
        try:
            decompressed = decompress_param(value)
            return json.loads(decompressed)
        except Exception:
            return value
    return value


def normalize_message(raw_json):
    """Parse a captured outgoing message and canonicalize its compressed payload fields."""
    msg = json.loads(raw_json)
    payload = msg.get('message_payload', {})
    if isinstance(payload, dict):
        msg['message_payload'] = {k: _normalize_value(v) for k, v in payload.items()}
    return msg


def invoke(case):
    """Run one CASE against a fresh mock client; return the normalized outgoing message."""
    clients = build()
    target = clients[case['target']]
    getattr(target, case['method'])(*case['args'])
    assert clients['ws'].sent, f"{case['name']}: no message was sent"
    result = normalize_message(clients['ws'].sent[-1])
    clients['ws'].close()
    return result


# The canonical set of calls under test. Every messaging routing variant + every non-file
# submodule method. File-upload methods (need real jars, non-deterministic binary payloads)
# are covered separately in test_file_methods.py -- see that file for the documented scope.
CASES = [
    # --- messaging routing variants (public, no submodule wrapper) ---
    {'name': 'messaging.global_controller_msgevent', 'target': 'messaging',
     'method': 'global_controller_msgevent', 'args': [True, 'EXEC', {'action': 'x'}]},
    {'name': 'messaging.regional_controller_msgevent', 'target': 'messaging',
     'method': 'regional_controller_msgevent', 'args': [True, 'EXEC', {'action': 'x'}]},
    {'name': 'messaging.global_agent_msgevent', 'target': 'messaging',
     'method': 'global_agent_msgevent', 'args': [True, 'EXEC', {'action': 'x'}, 'R', 'A']},
    {'name': 'messaging.regional_agent_msgevent', 'target': 'messaging',
     'method': 'regional_agent_msgevent', 'args': [True, 'EXEC', {'action': 'x'}, 'A']},
    {'name': 'messaging.agent_msgevent', 'target': 'messaging',
     'method': 'agent_msgevent', 'args': [True, 'EXEC', {'action': 'x'}]},
    {'name': 'messaging.global_plugin_msgevent', 'target': 'messaging',
     'method': 'global_plugin_msgevent', 'args': [True, 'EXEC', {'action': 'x'}, 'R', 'A', 'P']},
    {'name': 'messaging.regional_plugin_msgevent', 'target': 'messaging',
     'method': 'regional_plugin_msgevent', 'args': [True, 'EXEC', {'action': 'x'}, 'A', 'P']},
    {'name': 'messaging.plugin_msgevent', 'target': 'messaging',
     'method': 'plugin_msgevent', 'args': [True, 'EXEC', {'action': 'x'}, 'P']},

    # --- admin ---
    {'name': 'admin.stopcontroller', 'target': 'admin', 'method': 'stopcontroller', 'args': ['R', 'A']},
    {'name': 'admin.restartcontroller', 'target': 'admin', 'method': 'restartcontroller', 'args': ['R', 'A']},
    {'name': 'admin.restartframework', 'target': 'admin', 'method': 'restartframework', 'args': ['R', 'A']},
    {'name': 'admin.killjvm', 'target': 'admin', 'method': 'killjvm', 'args': ['R', 'A']},

    # --- api ---
    {'name': 'api.get_global_info', 'target': 'api', 'method': 'get_global_info', 'args': []},

    # --- agents (non-file) ---
    {'name': 'agents.is_controller_active', 'target': 'agents', 'method': 'is_controller_active', 'args': ['R', 'A']},
    {'name': 'agents.get_controller_status', 'target': 'agents', 'method': 'get_controller_status', 'args': ['R', 'A']},
    {'name': 'agents.add_plugin_agent', 'target': 'agents', 'method': 'add_plugin_agent',
     'args': ['R', 'A', {'pluginname': 'io.cresco.example'}, None]},
    {'name': 'agents.add_plugin_agent_edges', 'target': 'agents', 'method': 'add_plugin_agent',
     'args': ['R', 'A', {'pluginname': 'io.cresco.example'}, {'edge': '1'}]},
    {'name': 'agents.remove_plugin_agent', 'target': 'agents', 'method': 'remove_plugin_agent', 'args': ['R', 'A', 'PID']},
    {'name': 'agents.list_plugin_agent', 'target': 'agents', 'method': 'list_plugin_agent', 'args': ['R', 'A']},
    {'name': 'agents.status_plugin_agent', 'target': 'agents', 'method': 'status_plugin_agent', 'args': ['R', 'A', 'PID']},
    {'name': 'agents.get_agent_info', 'target': 'agents', 'method': 'get_agent_info', 'args': ['R', 'A']},
    {'name': 'agents.get_agent_log', 'target': 'agents', 'method': 'get_agent_log', 'args': ['R', 'A']},
    {'name': 'agents.get_broadcast_discovery', 'target': 'agents', 'method': 'get_broadcast_discovery', 'args': ['R', 'A']},
    {'name': 'agents.cepadd', 'target': 'agents', 'method': 'cepadd',
     'args': ['istream', 'idesc', 'ostream', 'odesc', 'select * from istream', 'R', 'A']},

    # --- globalcontroller (non-file) ---
    {'name': 'globalcontroller.submit_pipeline', 'target': 'globalcontroller', 'method': 'submit_pipeline',
     'args': [{'pipeline_name': 'p', 'nodes': [], 'edges': []}, '0']},
    {'name': 'globalcontroller.remove_pipeline', 'target': 'globalcontroller', 'method': 'remove_pipeline', 'args': ['PID']},
    {'name': 'globalcontroller.get_pipeline_list', 'target': 'globalcontroller', 'method': 'get_pipeline_list', 'args': []},
    {'name': 'globalcontroller.get_pipeline_info', 'target': 'globalcontroller', 'method': 'get_pipeline_info', 'args': ['PID']},
    {'name': 'globalcontroller.get_pipeline_export', 'target': 'globalcontroller', 'method': 'get_pipeline_export', 'args': ['PID']},
    {'name': 'globalcontroller.get_pipeline_is_assignment_info', 'target': 'globalcontroller',
     'method': 'get_pipeline_is_assignment_info', 'args': ['INODE', 'RES']},
    {'name': 'globalcontroller.get_agent_list', 'target': 'globalcontroller', 'method': 'get_agent_list', 'args': [None]},
    {'name': 'globalcontroller.get_agent_list_region', 'target': 'globalcontroller', 'method': 'get_agent_list', 'args': ['R']},
    {'name': 'globalcontroller.get_agent_resources', 'target': 'globalcontroller', 'method': 'get_agent_resources', 'args': ['R', 'A']},
    {'name': 'globalcontroller.get_region_resources', 'target': 'globalcontroller', 'method': 'get_region_resources', 'args': ['R']},
    {'name': 'globalcontroller.get_region_list', 'target': 'globalcontroller', 'method': 'get_region_list', 'args': []},
    {'name': 'globalcontroller.get_plugin_repo_list', 'target': 'globalcontroller', 'method': 'get_plugin_repo_list', 'args': []},
    {'name': 'globalcontroller.get_repo_plugins', 'target': 'globalcontroller', 'method': 'get_repo_plugins', 'args': []},

    # --- B-2 unified metrics + capability catalog ---
    {'name': 'globalcontroller.get_metric_inventory', 'target': 'globalcontroller', 'method': 'get_metric_inventory',
     'args': ['global', None, None, True, True]},
    {'name': 'globalcontroller.get_metric_inventory_node', 'target': 'globalcontroller', 'method': 'get_metric_inventory',
     'args': ['node', 'R', 'A', True, False]},
    {'name': 'globalcontroller.get_capability_inventory', 'target': 'globalcontroller', 'method': 'get_capability_inventory',
     'args': ['global', None, None, True, False]},

    # --- plugin-jar (file) methods: use the shared fixture jar so configparams/jardata are deterministic ---
    {'name': 'agents.repo_pull_plugin_agent', 'target': 'agents', 'method': 'repo_pull_plugin_agent',
     'args': ['R', 'A', JAR_PATH]},
    {'name': 'agents.upload_plugin_agent', 'target': 'agents', 'method': 'upload_plugin_agent',
     'args': ['R', 'A', JAR_PATH]},
    {'name': 'agents.update_plugin_agent', 'target': 'agents', 'method': 'update_plugin_agent',
     'args': ['R', 'A', JAR_PATH]},
    {'name': 'globalcontroller.upload_plugin_global', 'target': 'globalcontroller', 'method': 'upload_plugin_global',
     'args': [JAR_PATH]},
]
