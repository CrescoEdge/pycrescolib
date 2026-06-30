"""
Admin module for Cresco administrative operations.
"""
import logging
from typing import Dict, Any, Optional

from .base_classes import CrescoMessageBase

# Setup logging
logger = logging.getLogger(__name__)

class admin(CrescoMessageBase):
    """Admin class for Cresco administrative operations."""

    def __init__(self, messaging):
        """Initialize with messaging interface.
        
        Args:
            messaging: Messaging interface
        """
        super().__init__(messaging)

    def stopcontroller(self, dst_region: str, dst_agent: str) -> None:
        """Stop a controller.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {'action': 'stopcontroller'}

            logger.info(f"Stopping controller on {dst_region}/{dst_agent}")
            self.messaging.global_agent_msgevent(
                False, message_event_type, message_payload, dst_region, dst_agent
            )
        except Exception as e:
            logger.error(f"Error stopping controller: {e}")
            raise

    def restartcontroller(self, dst_region: str, dst_agent: str) -> None:
        """Restart a controller.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {'action': 'restartcontroller'}

            logger.info(f"Restarting controller on {dst_region}/{dst_agent}")
            self.messaging.global_agent_msgevent(
                False, message_event_type, message_payload, dst_region, dst_agent
            )
        except Exception as e:
            logger.error(f"Error restarting controller: {e}")
            raise

    def restartframework(self, dst_region: str, dst_agent: str) -> None:
        """Restart the framework.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {'action': 'restartframework'}

            logger.info(f"Restarting framework on {dst_region}/{dst_agent}")
            self.messaging.global_agent_msgevent(
                False, message_event_type, message_payload, dst_region, dst_agent
            )
        except Exception as e:
            logger.error(f"Error restarting framework: {e}")
            raise

    def killjvm(self, dst_region: str, dst_agent: str) -> None:
        """Kill the JVM process.
        
        Args:
            dst_region: Destination region
            dst_agent: Destination agent
        """
        try:
            message_event_type = 'CONFIG'
            message_payload = {'action': 'killjvm'}

            logger.warning(f"Killing JVM on {dst_region}/{dst_agent}")
            self.messaging.global_agent_msgevent(
                False, message_event_type, message_payload, dst_region, dst_agent
            )
        except Exception as e:
            logger.error(f"Error killing JVM: {e}")
            raise
