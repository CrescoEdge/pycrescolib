"""Application recipe: deploy a stunnel tunnel via a CADL pipeline.

This is an *application-specific* deployment workflow, kept out of the core
`client.stunnel` submodule on purpose. The core submodule assumes the stunnel
plugin is already loaded on both agents and just configures the tunnel. This
recipe instead *deploys* the plugin through the global scheduler first:

  1. upload the stunnel jar to the global repo,
  2. submit a CADL pipeline that schedules a stunnel instance onto the source
     and destination agents,
  3. wait for the pipeline to go ACTIVE (status 10),
  4. resolve the scheduled plugin ids by name and configure the tunnel.

It replaces the ad-hoc `StunnelCADL` class from the 1.3-vaiden branch: the same
deploy-then-configure flow, but built on the standardized `client.stunnel`
submodule and `globalcontroller.find_plugin` (the reliable, log-free plugin-id
resolution) instead of hardcoded paths and manual pipeline-node digging.

Usage:
    python stunnel_pipeline_deploy.py <host> <service_key> <stunnel_jar_path>
"""

import json
import sys
import time

from pycrescolib.clientlib import clientlib
from pycrescolib.utils import decompress_param

PIPELINE_ACTIVE = 10  # CADL pipeline status code for "running"


def wait_for_pipeline(client, pipeline_id, target=PIPELINE_ACTIVE, timeout=60):
    """Poll until the pipeline reaches `target` status, or timeout. Returns bool."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.globalcontroller.get_pipeline_status(pipeline_id)
        if status == target:
            return True
        print(f"  pipeline {pipeline_id}: status {status}, waiting for {target}...")
        time.sleep(2)
    return False


def deploy_stunnel_pipeline(client, stunnel_id, jar_path,
                            src_region, src_agent, src_port,
                            dst_region, dst_agent, dst_host, dst_port,
                            buffer_size="256"):
    """Upload the stunnel plugin, schedule it on both agents via a CADL pipeline,
    then configure the tunnel. Returns (pipeline_id, create_reply)."""

    # 1) Upload the jar to the global repo; the reply carries the plugin's
    #    scheduling coordinates (pluginname / md5 / version) we place into the CADL.
    reply = client.globalcontroller.upload_plugin_global(jar_path)
    configparams = json.loads(decompress_param(reply["configparams"]))
    print(f"uploaded {configparams['pluginname']} v{configparams['version']} (md5={configparams['md5']})")

    def stunnel_node(node_id, name, region, agent):
        return {
            "type": "dummy",
            "node_name": name,
            "node_id": node_id,
            "isSource": False,
            "workloadUtil": 0,
            "params": {
                "pluginname": configparams["pluginname"],
                "md5": configparams["md5"],
                "version": configparams["version"],
                "location_region": region,
                "location_agent": agent,
            },
        }

    # 2) Submit a CADL pipeline that pins one stunnel instance to each agent.
    cadl = {
        "pipeline_id": "0",
        "pipeline_name": stunnel_id,
        "nodes": [
            stunnel_node(0, "stunnel-src", src_region, src_agent),
            stunnel_node(1, "stunnel-dst", dst_region, dst_agent),
        ],
        "edges": [{"edge_id": 0, "node_from": 0, "node_to": 1, "params": {}}],
    }
    pipeline_id = client.globalcontroller.submit_pipeline(cadl)["gpipeline_id"]
    print(f"submitted pipeline {pipeline_id}")

    # 3) Wait for both stunnel instances to come up.
    if not wait_for_pipeline(client, pipeline_id):
        raise RuntimeError(f"pipeline {pipeline_id} did not reach ACTIVE")
    print(f"pipeline {pipeline_id} ACTIVE")

    # 4) Configure the tunnel. The stunnel submodule auto-resolves the freshly
    #    scheduled plugin ids by name (find_plugin), so we never dig them out of
    #    the pipeline node structure or scrape logs.
    create_reply = client.stunnel.create_tunnel(
        stunnel_id, src_region, src_agent, src_port,
        dst_region, dst_agent, dst_host, dst_port, buffer_size,
    )
    print(f"tunnel {stunnel_id}: {create_reply}")
    return pipeline_id, create_reply


def teardown(client, stunnel_id, pipeline_id, src_region, src_agent, dst_region, dst_agent):
    """Remove the tunnel (both ends) and the pipeline that scheduled it."""
    client.stunnel.remove_tunnel(stunnel_id, src_region, src_agent, dst_region, dst_agent)
    client.globalcontroller.remove_pipeline(pipeline_id)
    print(f"removed tunnel {stunnel_id} and pipeline {pipeline_id}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <host> <service_key> <stunnel_jar_path>")
        sys.exit(1)
    host, service_key, jar_path = sys.argv[1], sys.argv[2], sys.argv[3]

    client = clientlib(host, 8282, service_key, verify_ssl=False)
    if not client.connect():
        print("failed to connect")
        sys.exit(1)
    try:
        # Edit these coordinates for your mesh.
        pipeline_id, _ = deploy_stunnel_pipeline(
            client, "example-tunnel", jar_path,
            src_region="edge-region1", src_agent="client-1a", src_port="5000",
            dst_region="edge-region4", dst_agent="client-4a",
            dst_host="127.0.0.1", dst_port="22",
        )
        # teardown(client, "example-tunnel", pipeline_id,
        #          "edge-region1", "client-1a", "edge-region4", "client-4a")
    finally:
        client.close()
