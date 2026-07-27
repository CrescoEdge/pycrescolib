import json
import logging
import os
import time
from typing import Dict, List, Tuple, Optional, Any
from urllib import request

from .utils import decompress_param


class StunnelDirect:
    def __init__(self, client, logger=None):
        """
        Initialize the StunnelDirect class with a Cresco client
        """
        self.client = client
        if logger:
            self.logger = logger
        else:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)

    def create_tunnel(self, stunnel_id: str, src_region: str, src_agent: str, src_port: str,
                      dst_region: str, dst_agent: str, dst_host: str, dst_port: str,
                      buffer_size: str) -> dict | None:
        self.logger.info("Attempting to create tunnel using existing system plugins.")
        src_plugin_id, dst_plugin_id = self._find_existing_stunnel_plugins(src_region, src_agent, dst_region, dst_agent)

        if src_plugin_id and dst_plugin_id:
            self.logger.info(f"Found existing stunnel plugins: src_plugin_id={src_plugin_id}, dst_plugin_id={dst_plugin_id}")
            return self._configure_existing_tunnel(stunnel_id, src_region, src_agent, src_port,
                                            dst_region, dst_agent, dst_host, dst_port,
                                            buffer_size, src_plugin_id, dst_plugin_id)
        else:
            self.logger.error("PROCESS FAILED: Could not find the required existing system stunnel plugins.")
            self.logger.error("Please ensure that stunnel plugins are running on both the source and destination agents and that their names start with 'system-' or 'systems-'.")

    def _find_existing_stunnel_plugins(self, src_region: str, src_agent: str, dst_region: str, dst_agent: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            self.logger.info("Finding stunnel plugins for source and destination agents.")
            src_plugin_id = self.find_existing_stunnel_plugin(src_region, src_agent)
            dst_plugin_id = self.find_existing_stunnel_plugin(dst_region, dst_agent)
            return src_plugin_id, dst_plugin_id
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while finding stunnel plugins: {e}", exc_info=True)
            return None, None

    def _configure_existing_tunnel(self, stunnel_id: str, src_region: str, src_agent: str, src_port: str,
                                   dst_region: str, dst_agent: str, dst_host: str, dst_port: str,
                                   buffer_size: str, src_plugin_id: str, dst_plugin_id: str) -> dict:
        try:
            self.logger.info(f"Configuring existing tunnel {stunnel_id} from {src_region}/{src_agent} to {dst_region}/{dst_agent}")
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'configsrctunnel',
                'action_src_port': src_port,
                'action_dst_host': dst_host,
                'action_dst_port': dst_port,
                'action_dst_region': dst_region,
                'action_dst_agent': dst_agent,
                'action_dst_plugin': dst_plugin_id,
                'action_buffer_size': buffer_size,
                'action_stunnel_id': stunnel_id,
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, src_region, src_agent, src_plugin_id)
            self.logger.info(f"Tunnel configuration result: {result}")
            if 'stunnel_config' in result:
                return json.loads(decompress_param(result['stunnel_config']))
        except Exception as e:
            self.logger.error(f"Error configuring existing tunnel: {e}")
            return {}

    def find_existing_stunnel_plugin(self, region: str, agent: str) -> Optional[str]:
        try:
            self.logger.info(f"Querying plugins for agent: {region}/{agent}")
            all_plugins = self.client.agents.list_plugin_agent(region, agent)

            for plugin in all_plugins:
                current_plugin_id = plugin.get("plugin_id", "")
                if plugin.get("pluginname") == "io.cresco.stunnel" and \
                        (current_plugin_id.startswith("system-") or current_plugin_id.startswith("systems-")):
                    self.logger.info(f"Found stunnel plugin '{current_plugin_id}' on agent {region}/{agent}.")
                    return current_plugin_id

            return None
        except Exception as e:
            self.logger.error(f"Error finding stunnel plugin on {region}/{agent}: {e}", exc_info=True)
            return None

    def get_tunnel_list(self, src_region: str, src_agent: str, src_plugin_id: str) -> dict | None:
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'listtunnels',
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, src_region, src_agent, src_plugin_id)
            if 'tunnels' in result:
                return json.loads(result['tunnels'])
        except Exception as e:
            self.logger.error(f"Error configuring existing tunnel: {e}")
            return {}

    def get_tunnel_status(self, src_region: str, src_agent: str, src_plugin_id: str, stunnel_id: str) -> dict | None:
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'gettunnelstatus',
                'action_stunnel_id': stunnel_id
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, src_region, src_agent, src_plugin_id)
            if 'tunnel_status' in result:
                return result['tunnel_status']
        except Exception as e:
            self.logger.error(f"Error configuring existing tunnel: {e}")
            return {}

    def get_tunnel_config(self, src_region: str, src_agent: str, src_plugin_id: str, stunnel_id: str) -> dict | None:
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'gettunnelconfig',
                'action_stunnel_id': stunnel_id
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, src_region, src_agent, src_plugin_id)
            if 'tunnel_config' in result:
                return json.loads(result['tunnel_config'])
        except Exception as e:
            self.logger.error(f"Error getting tunnel config: {e}")
            return {}

    def remove_src_tunnel(self, src_region: str, src_agent: str, src_plugin_id: str, stunnel_id: str) -> dict | None:
        """
        Remove a source tunnel from the stunnel plugin.
        Sends 'removesrctunnel' CONFIG action to the stunnel plugin.
        """
        try:
            self.logger.info(f"Removing source tunnel {stunnel_id} from {src_region}/{src_agent}")
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'removesrctunnel',
                'action_stunnel_id': stunnel_id
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, src_region, src_agent, src_plugin_id)
            self.logger.info(f"Remove source tunnel result: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error removing source tunnel: {e}")
            return None

    def remove_dst_tunnel(self, dst_region: str, dst_agent: str, dst_plugin_id: str, stunnel_id: str) -> dict | None:
        """
        Remove a destination tunnel from the stunnel plugin.
        Sends 'removedsttunnel' CONFIG action to the stunnel plugin.
        """
        try:
            self.logger.info(f"Removing destination tunnel {stunnel_id} from {dst_region}/{dst_agent}")
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'removedsttunnel',
                'action_stunnel_id': stunnel_id
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, dst_region, dst_agent, dst_plugin_id)
            self.logger.info(f"Remove destination tunnel result: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error removing destination tunnel: {e}")
            return None

    def remove_tunnel(self, stunnel_id: str, src_region: str, src_agent: str, src_plugin_id: str,
                      dst_region: str, dst_agent: str, dst_plugin_id: str) -> dict:
        """
        Remove both source and destination tunnels.
        This is a convenience method that removes the src and dst tunnels in sequence.
        
        Args:
            stunnel_id: The tunnel ID to remove
            src_region: Source region
            src_agent: Source agent
            src_plugin_id: Source plugin ID
            dst_region: Destination region
            dst_agent: Destination agent
            dst_plugin_id: Destination plugin ID
        
        Returns:
            Dict with src_removal and dst_removal results
        """
        self.logger.info(f"Removing tunnel {stunnel_id}")
        response = {
            "stunnel_id": stunnel_id,
            "src_removal": None,
            "dst_removal": None,
            "dst_plugin_resolved": None,
            "fully_removed": False,
        }
        
        try:
            # Resolve destination plugin when destination location is known but plugin was not supplied.
            final_dst_plugin_id = dst_plugin_id
            if not final_dst_plugin_id and dst_region and dst_agent:
                final_dst_plugin_id = self.find_existing_stunnel_plugin(dst_region, dst_agent)
                response["dst_plugin_resolved"] = final_dst_plugin_id
                if final_dst_plugin_id:
                    self.logger.info(
                        f"Resolved destination plugin for {dst_region}/{dst_agent}: {final_dst_plugin_id}"
                    )

            # Remove source tunnel
            if src_region and src_agent and src_plugin_id:
                self.logger.info(f"Removing source tunnel from {src_region}/{src_agent}")
                src_result = self.remove_src_tunnel(
                    src_region=src_region,
                    src_agent=src_agent,
                    src_plugin_id=src_plugin_id,
                    stunnel_id=stunnel_id
                )
                response["src_removal"] = src_result
            else:
                self.logger.warning("Missing source info - skipping source tunnel removal")
            
            # Remove destination tunnel
            if dst_region and dst_agent and final_dst_plugin_id:
                self.logger.info(f"Removing destination tunnel from {dst_region}/{dst_agent}")
                dst_result = self.remove_dst_tunnel(
                    dst_region=dst_region,
                    dst_agent=dst_agent,
                    dst_plugin_id=final_dst_plugin_id,
                    stunnel_id=stunnel_id
                )
                response["dst_removal"] = dst_result
            else:
                self.logger.info("Destination plugin not provided - skipping destination tunnel removal")

            response["fully_removed"] = bool(response["src_removal"] and response["dst_removal"])
        
        except Exception as e:
            self.logger.error(f"Error removing tunnel {stunnel_id}: {e}", exc_info=True)
            response["error"] = str(e)
        
        return response


class StunnelCADL:
    def __init__(self, client, logger=None):
        self.client = client
        if logger:
            self.logger = logger
        else:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)

    def create_tunnel(self, stunnel_id, src_region, src_agent, src_port, dst_region, dst_agent, dst_host, dst_port, buffer_size) -> None:
        self.logger.info(f"Starting multi-node stunnel deployment with controller at {dst_region}/{dst_agent}")

        try:
            # Note this just pushes the plugins to the agent(s) it does not establish stunnel configurations
            jar_file_path = '/Users/cody/IdeaProjects/stunnel/target/stunnel-1.2-SNAPSHOT.jar'
            reply = self.upload_plugin(jar_file_path)

            config_str = decompress_param(reply['configparams'])
            self.logger.info(f"Plugin config: {config_str}")

            configparams = json.loads(config_str)

            cadl = {
                'pipeline_id': '0',
                'pipeline_name': stunnel_id,
                'nodes': [],
                'edges': []
            }

            params0 = {
                'pluginname': configparams['pluginname'],
                'md5': configparams['md5'],
                'version': configparams['version'],
                'location_region': src_region,
                'location_agent': src_agent,
            }

            node0 = {
                'type': 'dummy',
                'node_name': 'SRC Plugin',
                'node_id': 0,
                'isSource': False,
                'workloadUtil': 0,
                'params': params0
            }

            params1 = {
                'pluginname': configparams['pluginname'],
                'md5': configparams['md5'],
                'version': configparams['version'],
                'location_region': dst_region,
                'location_agent': dst_agent,
            }

            node1 = {
                'type': 'dummy',
                'node_name': 'DST Plugin',
                'node_id': 1,
                'isSource': False,
                'workloadUtil': 0,
                'params': params1
            }

            edge0 = {
                'edge_id': 0,
                'node_from': 0,
                'node_to': 1,
                'params': {}
            }

            cadl['nodes'].append(node0)
            cadl['nodes'].append(node1)
            cadl['edges'].append(edge0)

            reply = self.client.globalcontroller.submit_pipeline(cadl)
            pipeline_id = reply['gpipeline_id']

            pipeline_config = self.client.globalcontroller.get_pipeline_info(pipeline_id)
            self.logger.info(f"Pipeline Config: {pipeline_config}")

            is_online = self.wait_for_pipeline(pipeline_id)
            if is_online:
                self.logger.info("Multi-node file repository pycrescolib_test completed successfully")
            else:
                self.logger.info("Multi-node file repository pycrescolib_test failed")

            dst_plugin = pipeline_config['nodes'][1]['node_id']
            src_plugin = pipeline_config['nodes'][0]['node_id']

            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'configsrctunnel',
                'action_src_port': src_port,
                'action_dst_host': dst_host,
                'action_dst_port': dst_port,
                'action_dst_region': dst_region,
                'action_dst_agent': dst_agent,
                'action_dst_plugin': dst_plugin,
                'action_buffer_size': buffer_size,
                'action_stunnel_id': stunnel_id,
            }

            result = self.client.messaging.global_plugin_msgevent(True, message_event_type, message_payload, src_region, src_agent, src_plugin)
            print(result)

        except Exception as e:
            self.logger.error(f"Error in filerepo_deploy_multi_node: {e}", exc_info=True)

    def get_plugin_from_git(self, src_url: str, force: bool = False) -> str:
        dst_file = src_url.rsplit('/', 1)[1]
        os.makedirs("plugins", exist_ok=True)
        dst_path = os.path.join("plugins", dst_file)

        if force or not os.path.exists(dst_path):
            self.logger.info(f"Downloading {dst_file} plugin from {src_url}")
            try:
                request.urlretrieve(src_url, dst_path)
                self.logger.info(f"Downloaded {dst_file} successfully")
            except Exception as e:
                self.logger.error(f"Failed to download {dst_file}: {e}")
                raise
        else:
            self.logger.info(f"Using existing plugin file: {dst_path}")

        return dst_path

    def upload_plugin(self, jar_path: str) -> Dict[str, Any]:
        self.logger.info(f"Uploading plugin {jar_path} to global controller")
        try:
            reply = self.client.globalcontroller.upload_plugin_global(jar_path)
            self.logger.info(f"Upload status: {reply.get('status_code', 'unknown')}")
            return reply
        except Exception as e:
            self.logger.error(f"Error uploading plugin: {e}")
            raise

    def wait_for_pipeline(self, pipeline_id: str, target_status: int = 10, timeout: int = 60) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                status = self.client.globalcontroller.get_pipeline_status(pipeline_id)
                if status == target_status:
                    self.logger.info(f"Pipeline {pipeline_id} reached status {target_status}")
                    return True
                self.logger.info(f"Waiting for pipeline {pipeline_id} to reach status {target_status}, current: {status}")
                time.sleep(2)
            except Exception as e:
                self.logger.error(f"Error checking pipeline status: {e}")
                time.sleep(2)

        self.logger.error(f"Timeout waiting for pipeline {pipeline_id} to reach status {target_status}")
        return False