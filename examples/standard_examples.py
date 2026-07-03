"""
Standardized Cresco client examples (Python).

Every example here has a byte-for-byte counterpart in the Java client
(clientlib: example/standard/StandardExamples.java) with the same function name,
the same step-by-step structure, and the same narrative comments. Only the
language syntax differs. Edit HOST/PORT/SERVICE_KEY, then run one example.
"""
import time

from pycrescolib.clientlib import clientlib

HOST = '127.0.0.1'
PORT = 8282
SERVICE_KEY = 'a-service-key'


def new_client():
    """Create a connected client, or None if the connection failed."""
    client = clientlib(HOST, PORT, SERVICE_KEY, verify_ssl=False)
    if not client.connect():
        print('Failed to connect')
        return None
    return client


def example_connect():
    """Connect, print API identity, list the mesh, disconnect."""
    client = new_client()
    if client is None:
        return

    # 1. Print the API identity of the agent hosting the wsapi plugin.
    print('region:', client.api.get_api_region_name())
    print('agent :', client.api.get_api_agent_name())
    print('plugin:', client.api.get_api_plugin_name())

    # 2. Print the global controller identity.
    print('global region:', client.api.get_global_region())
    print('global agent :', client.api.get_global_agent())

    # 3. List the regions and the agents.
    print('regions:', client.globalcontroller.get_region_list())
    print('agents :', client.globalcontroller.get_agent_list())

    # 4. Disconnect.
    client.close()


def example_pipeline():
    """Submit a CADL pipeline, poll status, fetch info, export, then remove it."""
    client = new_client()
    if client is None:
        return

    # 1. Define a minimal CADL pipeline.
    cadl = {'pipeline_id': '0', 'pipeline_name': 'example-pipeline', 'nodes': [], 'edges': []}

    # 2. Submit the pipeline for tenant 0.
    reply = client.globalcontroller.submit_pipeline(cadl, '0')
    pipeline_id = reply.get('gpipeline_id')
    print('submitted pipeline:', pipeline_id)

    # 3. Poll until the pipeline is active (status code 10).
    for _ in range(30):
        status = client.globalcontroller.get_pipeline_status(pipeline_id)
        print('status:', status)
        if status == 10:
            break
        time.sleep(1)

    # 4. Fetch full info and an export of the pipeline.
    print('info  :', client.globalcontroller.get_pipeline_info(pipeline_id))
    print('export:', client.globalcontroller.get_pipeline_export(pipeline_id))

    # 5. Remove the pipeline and disconnect.
    client.globalcontroller.remove_pipeline(pipeline_id)
    client.close()


def example_plugin_lifecycle(dst_region, dst_agent, jar_file_path):
    """Add a plugin to an agent, list/status it, then remove it."""
    client = new_client()
    if client is None:
        return

    # 1. Upload the plugin jar to the agent's repo, then add it as a plugin.
    info = client.agents.repo_pull_plugin_agent(dst_region, dst_agent, jar_file_path)
    print('repo pull:', info)
    configparams = {'pluginname': 'example', 'jarfile': jar_file_path}
    added = client.agents.add_plugin_agent(dst_region, dst_agent, configparams, None)
    plugin_id = added.get('pluginid')
    print('added plugin:', plugin_id)

    # 2. List plugins on the agent and check this plugin's status.
    print('plugins:', client.agents.list_plugin_agent(dst_region, dst_agent))
    print('status :', client.agents.status_plugin_agent(dst_region, dst_agent, plugin_id))

    # 3. Remove the plugin and disconnect.
    client.agents.remove_plugin_agent(dst_region, dst_agent, plugin_id)
    client.close()


def example_dataplane(stream_query):
    """Open a dataplane stream, send text + binary + a fragmented message, receive via callback."""
    client = new_client()
    if client is None:
        return

    # 1. Open a dataplane for the stream query, printing anything received.
    def on_message(message):
        print('dataplane recv:', message)

    dp = client.get_dataplane(stream_query, on_message)
    dp.connect()
    time.sleep(2)

    # 2. Send a text message, a binary message, and a fragmented (partial) message.
    dp.send('hello dataplane')
    dp.send_binary(b'\x00\x01\x02\x03')
    dp.send_partial(b'part-1', False)
    dp.send_partial(b'part-2', True)
    time.sleep(2)

    # 3. Close the stream and disconnect.
    client.close_dataplane(stream_query)
    client.close()


def example_logstreamer(dst_region, dst_agent):
    """Attach a log streamer, set the log config (incl. a per-baseclass level), stream logs."""
    client = new_client()
    if client is None:
        return

    # 1. Attach a log streamer, printing anything received.
    def on_message(message):
        print('log:', message)

    ls = client.get_logstreamer('example', on_message)
    ls.connect()
    time.sleep(2)

    # 2. Set the log configuration, then raise one base class to Trace.
    ls.update_config(dst_region, dst_agent)
    ls.update_config_class(dst_region, dst_agent, 'Trace', 'io.cresco.agent')
    time.sleep(5)

    # 3. Close the stream and disconnect.
    client.close_logstreamer('example')
    client.close()


def example_admin(dst_region, dst_agent):
    """Check an agent's controller, then restart its framework (guarded)."""
    client = new_client()
    if client is None:
        return

    # 1. Only act if the target agent's controller is active.
    if client.agents.is_controller_active(dst_region, dst_agent):
        print('controller status:', client.agents.get_controller_status(dst_region, dst_agent))

        # 2. Restart the OSGi framework on the target agent.
        client.admin.restartframework(dst_region, dst_agent)
    else:
        print('controller not active on', dst_region, '/', dst_agent)

    # 3. Disconnect.
    client.close()


if __name__ == '__main__':
    # Run the connect example by default; call the others with your own region/agent/jar/stream.
    example_connect()
