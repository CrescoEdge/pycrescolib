"""
Base classes for the Cresco library to reduce code duplication.
"""
import json
import logging
from typing import Dict, Any, Optional

import backoff

# Set up logging
logger = logging.getLogger(__name__)

class CrescoQueryError(RuntimeError):
    """An inventory/lookup query could not be answered.

    Raised when the reply to a listing RPC (plugins, agents, regions, pipelines) is an error
    reply, is missing the field a successful reply always carries, or is not a reply at all.
    It means "could not ask", which is different from "asked, and the answer is empty":
    callers that act on the answer (e.g. deploy a plugin when it is not loaded) must not
    treat it as "none". Transport failures raise TimeoutError / ConnectionError instead.
    """


def require_reply_field(reply: Any, field: str, what: str) -> Any:
    """Return reply[field], or raise CrescoQueryError when the query was not answered.

    A successful listing reply always carries its field (the controller sets it even for an
    empty list); an error reply carries 'error' / 'status_desc' instead (e.g. wsapi's 504 when
    the fabric did not answer in time).
    """
    if isinstance(reply, dict) and reply.get(field) is not None:
        return reply[field]
    if not isinstance(reply, dict):
        raise CrescoQueryError(f"{what}: no reply")
    reason = reply.get('error') or reply.get('status_desc') or f"reply has no '{field}'"
    status = reply.get('status') or reply.get('status_code')
    raise CrescoQueryError(f"{what}: {reason}" + (f" (status {status})" if status else ""))


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
