"""
Global controller module for interacting with Cresco global controller.
"""
import json
import logging
from typing import Dict, Any, List, Optional, Union

from .base_classes import CrescoMessageBase
from .utils import decompress_param, get_jar_info, compress_param, encode_data, json_serialize, json_deserialize, read_file_bytes

# Setup logging
logger = logging.getLogger(__name__)

class globalcontroller(CrescoMessageBase):
    """Global controller class for Cresco operations."""

    def __init__(self, messaging):
        """Initialize with messaging interface.

        Args:
            messaging: Messaging interface
        """
        super().__init__(messaging)

    def submit_pipeline(self, cadl: Dict[str, Any], tenant_id: str = '0') -> Dict[str, Any]:
        """Submit a pipeline.

        Args:
            cadl: Pipeline configuration in CADL format
            tenant_id: Tenant ID (default: '0')

        Returns:
            Response containing status and pipeline ID
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'gpipelinesubmit',
                'action_gpipeline': compress_param(json_serialize(cadl)),
                'action_tenantid': tenant_id
            }

            logger.info(f"Submitting pipeline for tenant {tenant_id}")
            retry = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
            return retry
        except Exception as e:
            logger.error(f"Error submitting pipeline: {e}")
            raise

    def remove_pipeline(self, pipeline_id: str) -> Dict[str, Any]:
        """Remove a pipeline.

        Args:
            pipeline_id: Pipeline ID to remove

        Returns:
            Response containing status
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'gpipelineremove',
                'action_pipelineid': pipeline_id
            }

            logger.info(f"Removing pipeline {pipeline_id}")
            retry = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
            return retry
        except Exception as e:
            logger.error(f"Error removing pipeline: {e}")
            raise

    def get_pipeline_list(self) -> List[Dict[str, Any]]:
        """Get a list of pipelines.

        Returns:
            List of pipelines
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'getgpipelinestatus'}

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'pipelineinfo' in reply:
                pipeline_info = json_deserialize(decompress_param(reply['pipelineinfo']))
                return pipeline_info.get('pipelines', [])
            return []
        except Exception as e:
            logger.error(f"Error getting pipeline list: {e}")
            return []

    def get_pipeline_info(self, pipeline_id: str) -> Dict[str, Any]:
        """Get pipeline information.

        Args:
            pipeline_id: Pipeline ID

        Returns:
            Pipeline information
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'getgpipeline',
                'action_pipelineid': pipeline_id
            }

            logger.debug(f"Getting info for pipeline {pipeline_id}")
            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'gpipeline' in reply:
                return json_deserialize(decompress_param(reply['gpipeline']))
            return {}
        except Exception as e:
            logger.error(f"Error getting pipeline info: {e}")
            return {}

    def get_pipeline_status(self, pipeline_id: str) -> int:
        """Get pipeline status.

        Args:
            pipeline_id: Pipeline ID

        Returns:
            Status code
        """
        try:
            reply = self.get_pipeline_info(pipeline_id)
            return int(reply.get('status_code', -1))
        except Exception as e:
            logger.error(f"Error getting pipeline status: {e}")
            return -1

    def get_pipeline_id_by_name(self, pipeline_name: str) -> Optional[str]:
        """Get a pipeline ID by its name.

        Args:
            pipeline_name: Pipeline name

        Returns:
            The pipeline ID if a pipeline with the given name exists, otherwise None
        """
        try:
            for pipeline in self.get_pipeline_list():
                if pipeline.get('pipeline_name') == pipeline_name:
                    return pipeline.get('pipeline_id')
            return None
        except Exception as e:
            logger.error(f"Error getting pipeline id by name: {e}")
            return None

    def get_pipeline_export(self, pipeline_id: str) -> Dict[str, Any]:
        """Export a pipeline.

        Args:
            pipeline_id: Pipeline ID

        Returns:
            Response containing the exported pipeline
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'getgpipelineexport',
                'action_pipelineid': pipeline_id
            }
            logger.debug(f"Exporting pipeline {pipeline_id}")
            return self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
        except Exception as e:
            logger.error(f"Error exporting pipeline: {e}")
            return {}

    def get_pipeline_is_assignment_info(self, inode_id: str, resource_id: str) -> Dict[str, Any]:
        """Get inode-to-resource assignment info.

        Args:
            inode_id: Inode ID
            resource_id: Resource ID

        Returns:
            Response containing assignment information
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'getisassignmentinfo',
                'action_inodeid': inode_id,
                'action_resourceid': resource_id
            }
            logger.debug(f"Getting assignment info for inode {inode_id} / resource {resource_id}")
            return self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
        except Exception as e:
            logger.error(f"Error getting assignment info: {e}")
            return {}

    def get_agent_list(self, dst_region: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get a list of agents.

        Args:
            dst_region: Optional destination region filter

        Returns:
            List of agents
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'listagents'}

            if dst_region is not None:
                message_payload['action_region'] = dst_region

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'agentslist' in reply:
                agent_list = json_deserialize(decompress_param(reply['agentslist']))
                return agent_list.get('agents', [])
            return []
        except Exception as e:
            logger.error(f"Error getting agent list: {e}")
            return []

    def get_agent_resources(self, dst_region: str, dst_agent: str) -> Dict[str, Any]:
        """Get agent resources.

        Args:
            dst_region: Destination region
            dst_agent: Destination agent

        Returns:
            Agent resources
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'resourceinfo',
                'action_region': dst_region,
                'action_agent': dst_agent
            }

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'resourceinfo' in reply:
                resource_info = json_deserialize(decompress_param(reply['resourceinfo']))
                agent_resource_info = resource_info.get('agentresourceinfo', [])

                if agent_resource_info and 'perf' in agent_resource_info[0]:
                    return json_deserialize(agent_resource_info[0]['perf'])
            return {}
        except Exception as e:
            logger.error(f"Error getting agent resources: {e}")
            return {}

    def get_metric_inventory(self, scope: str = 'global', dst_region: str = None, dst_agent: str = None,
                             include_plugins: bool = True, include_resource: bool = True,
                             timeout: float = 45.0) -> Dict[str, Any]:
        """B-2 unified metrics: pull the fabric's unified metric inventory.

        Merges each node's controller Micrometer groups (jvm/processor/netlink/controller/regional/global)
        with every plugin's getmetrics output and, optionally, the cpu/mem/disk resource summary.

        Args:
            scope: 'node' (one controller), 'region' (its region), or 'global' (whole mesh).
            dst_region: if given with dst_agent, target that agent's controller directly (node scope).
            dst_agent: see dst_region.
            include_plugins: include each node's plugin metrics (default True).
            include_resource: include the cpu/mem/disk resource summary (adds sysinfo RPC latency).
            timeout: RPC timeout in seconds; a whole-mesh scope=global aggregate fans out, so this
                defaults high (30s) rather than the usual 8s.

        Returns:
            The unified inventory as a dict (metrics_by_source keyed by "<region>_<agent>:<bundle>",
            plus optional resource_summary and children), or {} on failure.
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'getmetricinventory',
                'action_scope': scope if scope else 'node',
                'action_include_plugins': str(include_plugins).lower(),
                'action_include_resource': str(include_resource).lower(),
            }

            if dst_region is not None and dst_agent is not None:
                reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload,
                                                             dst_region, dst_agent, timeout)
            else:
                reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload,
                                                                  timeout)

            if reply and 'metricinventory' in reply:
                return json_deserialize(reply['metricinventory'])
            return {}
        except Exception as e:
            logger.error(f"Error getting metric inventory: {e}")
            return {}

    def get_plugin_repo_list(self) -> Dict[str, Any]:
        """Get the list of plugins available in the repositories.

        Returns:
            Mapping of repositories to their available plugins
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'listpluginsrepo'}

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'listpluginsrepo' in reply:
                return json_deserialize(decompress_param(reply['listpluginsrepo']))
            return {}
        except Exception as e:
            logger.error(f"Error getting plugin repo list: {e}")
            return {}

    def get_repo_plugins(self) -> Dict[str, Any]:
        """Get the list of plugins known to the repositories.

        Returns:
            Mapping containing the known plugins
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'listplugins'}

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'pluginslist' in reply:
                return json_deserialize(decompress_param(reply['pluginslist']))
            return {}
        except Exception as e:
            logger.error(f"Error getting repo plugins: {e}")
            return {}

    def upload_plugin_global(self, jar_file_path: str) -> Dict[str, Any]:
        """Upload a plugin to the global repository.

        Args:
            jar_file_path: Path to JAR file

        Returns:
            Response containing status
        """
        try:
            # Get data from jar
            configparams = get_jar_info(jar_file_path)

            # Read jar data
            jar_data = read_file_bytes(jar_file_path)

            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'savetorepo',
                'configparams': compress_param(json_serialize(configparams)),
                'jardata': encode_data(jar_data)
            }

            logger.info(f"Uploading plugin {configparams.get('pluginname')} to global repository")
            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
            return reply
        except Exception as e:
            logger.error(f"Error uploading plugin to global: {e}")
            raise

    def get_region_resources(self, dst_region: str) -> Dict[str, Any]:
        """Get region resources.

        Args:
            dst_region: Destination region

        Returns:
            Region resources
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {
                'action': 'resourceinfo',
                'action_region': dst_region
            }

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'resourceinfo' in reply:
                return json_deserialize(decompress_param(reply['resourceinfo']))
            return {}
        except Exception as e:
            logger.error(f"Error getting region resources: {e}")
            return {}

    def get_region_list(self) -> List[Dict[str, Any]]:
        """Get a list of regions.

        Returns:
            List of regions
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'listregions'}

            reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

            if 'regionslist' in reply:
                regions_list = json_deserialize(decompress_param(reply['regionslist']))
                return regions_list.get('regions', [])
            return []
        except Exception as e:
            logger.error(f"Error getting region list: {e}")
            return []
