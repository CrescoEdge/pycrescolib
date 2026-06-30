"""
API module for Cresco API operations.
"""
import logging
from typing import Dict, Any, Optional, Tuple

from .base_classes import CrescoMessageBase

# Setup logging
logger = logging.getLogger(__name__)

class api(CrescoMessageBase):
    """API class for Cresco API operations."""

    def __init__(self, messaging):
        """Initialize with messaging interface.
        
        Args:
            messaging: Messaging interface
        """
        super().__init__(messaging)
        self.global_region = None
        self.global_agent = None

    def get_api_region_name(self) -> str:
        """Get the API region name.
        
        Returns:
            Region name
        """
        return self.messaging.get_region()

    def get_api_agent_name(self) -> str:
        """Get the API agent name.
        
        Returns:
            Agent name
        """
        return self.messaging.get_agent()

    def get_api_plugin_name(self) -> str:
        """Get the API plugin name.
        
        Returns:
            Plugin name
        """
        return self.messaging.get_plugin()

    def get_global_region(self) -> Optional[str]:
        """Get the global region.
        
        Returns:
            Global region or None
        """
        if self.global_region is None:
            self.get_global_info()

        return self.global_region

    def get_global_agent(self) -> Optional[str]:
        """Get the global agent.
        
        Returns:
            Global agent or None
        """
        if self.global_agent is None:
            self.get_global_info()

        return self.global_agent

    def get_global_info(self) -> Tuple[Optional[str], Optional[str]]:
        """Get global information.
        
        Returns:
            Tuple of (global_region, global_agent)
        """
        try:
            message_event_type = 'EXEC'
            message_payload = {'action': 'globalinfo'}

            plugin_name = self.get_api_plugin_name()
            logger.debug(f"Getting global info for plugin {plugin_name}")
            
            reply = self.messaging.plugin_msgevent(True, message_event_type, message_payload, plugin_name)
            
            self.global_region = reply.get('global_region')
            self.global_agent = reply.get('global_agent')
            
            return self.global_region, self.global_agent
        except Exception as e:
            logger.error(f"Error getting global info: {e}")
            return None, None
