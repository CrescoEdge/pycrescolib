"""
Agents module for interacting with Cresco agents.
"""
import json
import logging
from typing import Dict, Any, List, Optional, Union

from .base_classes import CrescoMessageBase
from .utils import compress_param, decompress_param, get_jar_info, encode_data, json_serialize, json_deserialize, read_file_bytes

# Setup logging
logger = logging.getLogger(__name__)

class agents(CrescoMessageBase):
    """Agents class for Cresco agent operations."""

    def __init__(self, messaging):
        """Initialize with messaging interface.
        
        Args:
            messaging: Messaging interface
        """
        super().__init__(messaging)

    def is_controller_active(self, dst_region: str, dst_agent: str) -> bool:
        """Check if a controller is active.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            True if controller is active, False otherwise
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'iscontrolleractive'}

            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return bool(reply.get('is_controller_active', False))
        except Exception as e:
            logger.error(f"Error checking if controller is active: {e}")
            return False

    def get_controller_status(self, dst_region: str, dst_agent: str) -> Dict[str, Any]:
        """Get controller status.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            Controller status information
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'getcontrollerstatus'}

            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            logger.debug(f"Controller status response: {reply}")
            return reply.get('controller_status', {})
        except Exception as e:
            logger.error(f"Error getting controller status: {e}")
            return {}

    def add_plugin_agent(self, dst_region: str, dst_agent: str, configparams: Dict[str, Any], edges: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add a plugin to an agent.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            configparams: Plugin configuration parameters
            edges: Optional edge definitions
            
        Returns:
            Response containing status and plugin ID
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'pluginadd',
                'configparams': compress_param(json_serialize(configparams))
            }

            if edges is not None:
                message_payload['edges'] = compress_param(json_serialize(edges))

            logger.info(f"Adding plugin to {dst_region}/{dst_agent}")
            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error adding plugin agent: {e}")
            raise

    def remove_plugin_agent(self, dst_region: str, dst_agent: str, plugin_id: str) -> Dict[str, Any]:
        """Remove a plugin from an agent.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            plugin_id: Plugin ID to remove
            
        Returns:
            Response containing status
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'pluginremove',
                'pluginid': plugin_id
            }

            logger.info(f"Removing plugin {plugin_id} from {dst_region}/{dst_agent}")
            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error removing plugin agent: {e}")
            raise

    def list_plugin_agent(self, dst_region: str, dst_agent: str) -> List[Dict[str, Any]]:
        """List plugins on an agent.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            List of plugins
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {'action': 'pluginlist'}

            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            
            if 'plugin_list' in reply:
                return json_deserialize(decompress_param(reply['plugin_list']))
            return []
        except Exception as e:
            logger.error(f"Error listing plugins: {e}")
            return []

    def status_plugin_agent(self, dst_region: str, dst_agent: str, plugin_id: str) -> Dict[str, Any]:
        """Get plugin status.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            plugin_id: Plugin ID
            
        Returns:
            Plugin status information
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'pluginstatus',
                'pluginid': plugin_id
            }

            logger.debug(f"Checking status of plugin {plugin_id} on {dst_region}/{dst_agent}")
            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error getting plugin status: {e}")
            return {}

    def get_agent_info(self, dst_region: str, dst_agent: str) -> Dict[str, Any]:
        """Get agent information.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            Agent information
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {'action': 'getagentinfo'}

            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply.get('agent-data', {})
        except Exception as e:
            logger.error(f"Error getting agent info: {e}")
            return {}

    def get_agent_log(self, dst_region: str, dst_agent: str) -> Dict[str, Any]:
        """Get agent logs.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            Agent logs
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'getlog'}

            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error getting agent log: {e}")
            return {}

    def repo_pull_plugin_agent(self, dst_region: str, dst_agent: str, jar_file_path: str) -> Dict[str, Any]:
        """Pull a plugin from the repository to an agent.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            jar_file_path: Path to JAR file
            
        Returns:
            Response containing status
        """
        try:
            # Get data from jar
            configparams = get_jar_info(jar_file_path)
            
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'pluginrepopull',
                'configparams': compress_param(json_serialize(configparams))
            }

            logger.info(f"Pulling plugin {configparams.get('pluginname')} to {dst_region}/{dst_agent}")
            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error pulling plugin from repo: {e}")
            raise

    def upload_plugin_agent(self, dst_region: str, dst_agent: str, jar_file_path: str) -> Dict[str, Any]:
        """Upload a plugin to an agent.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
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
                'action': 'pluginupload',
                'configparams': compress_param(json_serialize(configparams)),
                'jardata': encode_data(jar_data)
            }

            logger.info(f"Uploading plugin {configparams.get('pluginname')} to {dst_region}/{dst_agent}")
            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error uploading plugin: {e}")
            raise

    def update_plugin_agent(self, dst_region: str, dst_agent: str, jar_file_path: str) -> Dict[str, Any]:
        """Update a plugin on an agent.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            jar_file_path: Path to JAR file
            
        Returns:
            Response containing status
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'controllerupdate',
                'jar_file_path': jar_file_path
            }

            logger.info(f"Updating plugin on {dst_region}/{dst_agent}")
            reply = self.messaging.global_agent_msgevent(False, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error updating plugin: {e}")
            raise

    def get_broadcast_discovery(self, dst_region: str, dst_agent: str) -> Dict[str, Any]:
        """Get broadcast discovery information.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            Broadcast discovery information
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'getbroadcastdiscovery'}

            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            return reply
        except Exception as e:
            logger.error(f"Error getting broadcast discovery: {e}")
            return {}

    def cepadd(self, 
              input_stream: str, 
              input_stream_desc: str, 
              output_stream: str, 
              output_stream_desc: str, 
              query: str, 
              dst_region: str, 
              dst_agent: str) -> Dict[str, Any]:
        """Add a CEP (Complex Event Processing) query.
        
        Args:
            input_stream: Input stream name
            input_stream_desc: Input stream description
            output_stream: Output stream name
            output_stream_desc: Output stream description
            query: CEP query
            dst_region: Destination region
            dst_agent: Destination agent
            
        Returns:
            Response containing status
        """
        try:
            cepparams = {
                'input_stream': input_stream,
                'input_stream_desc': input_stream_desc,
                'output_stream': output_stream,
                'output_stream_desc': output_stream_desc,
                'query': query
            }

            message_event_type = 'CONFIG'
            message_payload = {
                'action': 'cepadd',
                'cepparams': compress_param(json_serialize(cepparams))
            }

            logger.info(f"Adding CEP query to {dst_region}/{dst_agent}")
            logger.debug(f"CEP parameters: {cepparams}")
            
            reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
            logger.debug(f"CEP add response: {reply}")
            
            return reply
        except Exception as e:
            logger.error(f"Error adding CEP query: {e}")
            raise
