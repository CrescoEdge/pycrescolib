"""
Base classes for the Cresco library to reduce code duplication.
"""
import json
import logging
from typing import Dict, Any, Optional

import backoff

# Set up logging
logger = logging.getLogger(__name__)

class CrescoMessageBase:
    """Base class for all Cresco message interactions."""
    
    def __init__(self, messaging):
        """Initialize with a messaging interface.
        
        Args:
            messaging: The messaging interface to use for communication
        """
        self.messaging = messaging
    
    def _prepare_message(self, 
                        message_type: str, 
                        message_event_type: str, 
                        is_rpc: bool,
                        payload: Dict[str, Any], 
                        **kwargs) -> Dict[str, Any]:
        """Prepare a message to be sent.
        
        Args:
            message_type: Type of message
            message_event_type: Event type
            is_rpc: Whether to expect a response
            payload: Message payload
            **kwargs: Additional message info parameters
            
        Returns:
            Dict containing the formatted message
        """
        message_info = {
            'message_type': message_type,
            'message_event_type': message_event_type,
            'is_rpc': is_rpc,
            **kwargs
        }
        
        message = {
            'message_info': message_info,
            'message_payload': payload
        }
        
        return message
    
    @backoff.on_exception(backoff.expo,
                         (ConnectionError, TimeoutError),
                         max_tries=3)
    def send_message(self, 
                     message_type: str, 
                     message_event_type: str,
                     is_rpc: bool, 
                     payload: Dict[str, Any], 
                     **kwargs) -> Optional[Dict[str, Any]]:
        """Send a message to the Cresco framework with retry capability.
        
        Args:
            message_type: Type of message
            message_event_type: Event type
            is_rpc: Whether to expect a response
            payload: Message payload
            **kwargs: Additional message parameters
            
        Returns:
            Response dict if is_rpc is True, otherwise None
        """
        message = self._prepare_message(message_type, message_event_type, is_rpc, payload, **kwargs)
        
        json_message = json.dumps(message)
        logger.debug(f"Sending message: {json_message}")
        
        try:
            self.messaging.ws_interface.ws.send(json_message)
            
            if is_rpc:
                response = self.messaging.ws_interface.ws.recv()
                json_response = json.loads(response)
                logger.debug(f"Received response: {json_response}")
                return json_response
                
        except Exception as e:
            logger.error(f"Error in send_message: {e}")
            raise
            
        return None

class WebSocketContextManager:
    """Context manager for WebSocket connections."""
    
    def __init__(self, url, service_key, ssl_verify=True):
        """Initialize the WebSocket context manager.
        
        Args:
            url: The WebSocket URL
            service_key: Service key for authentication
            ssl_verify: Whether to verify SSL certificates
        """
        self.url = url
        self.service_key = service_key
        self.ssl_verify = ssl_verify
        self.ws = None
        
    async def __aenter__(self):
        """Connect to WebSocket on entering context."""
        # Connection will be implemented in subclasses
        pass
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close WebSocket on exiting context."""
        if self.ws and self.ws.open:
            await self.ws.close()
            logger.debug("WebSocket connection closed")
