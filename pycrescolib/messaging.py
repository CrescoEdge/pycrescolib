"""
Messaging implementation for Cresco communications with direct response handling.
"""
import json
import logging
import asyncio
import time
import traceback
import threading
from typing import Dict, Any, Optional, Union
import concurrent.futures

from .base_classes import CrescoMessageBase

# Setup logging
logger = logging.getLogger(__name__)


class messaging(CrescoMessageBase):
    """Messaging class for Cresco communication."""

    def __init__(self, ws_interface):
        """Initialize messaging with a WebSocket interface.

        Args:
            ws_interface: WebSocket interface for communication
        """
        self.ws_interface = ws_interface
        self._lock = asyncio.Lock()  # For thread safety

    async def _send_message(self, message_info: Dict[str, Any], message_payload: Dict[str, Any]) -> Optional[
        Dict[str, Any]]:
        """Send a message via WebSocket with comprehensive logging for diagnostics.

        Args:
            message_info: Message metadata
            message_payload: Message content

        Returns:
            Response dict if is_rpc is True, otherwise None
        """
        message = {
            'message_info': message_info,
            'message_payload': message_payload
        }

        try:
            # Prepare message
            json_message = json.dumps(message)
            message_type = message_info.get('message_type', 'unknown')
            message_event = message_info.get('message_event_type', 'unknown')
            is_rpc = message_info.get('is_rpc', False)

            # Log formatted message details for better diagnostics
            logger.info(f"Sending {message_type}/{message_event} (RPC: {is_rpc})")

            if 'dst_region' in message_info:
                logger.info(
                    f"Destination: region={message_info.get('dst_region')}, agent={message_info.get('dst_agent')}")

            # Log action for easier debugging
            if 'action' in message_payload:
                logger.info(f"Action: {message_payload['action']}")

            # Send message
            try:
                if is_rpc:
                    # For RPC calls, use send which also receives the response
                    response = await self.ws_interface.send(json_message)

                    logger.debug(f"Received response of length {len(response)}")
                    try:
                        parsed_response = json.loads(response)
                        logger.debug(
                            f"Response keys: {list(parsed_response.keys()) if isinstance(parsed_response, dict) else 'Not a dict'}")

                        # Log response details
                        if isinstance(parsed_response, dict):
                            if 'status_code' in parsed_response:
                                logger.info(f"Response status code: {parsed_response.get('status_code')}")
                            if 'error' in parsed_response:
                                logger.warning(f"Error in response: {parsed_response.get('error')}")

                        return parsed_response
                    except json.JSONDecodeError as e:
                        # Log more details about the invalid JSON
                        logger.error(f"Invalid JSON response: {response[:1000]}...")
                        logger.error(f"JSON error: {e}")
                        raise ValueError(f"Invalid JSON response from server: {e}")
                else:
                    # For non-RPC calls, just send
                    await self.ws_interface.send_async(json_message)
                    return None
            except TimeoutError as e:
                logger.error(f"Timeout during message exchange: {e}")
                logger.error(f"Operation was: {message_type}/{message_event}")
                raise
            except ConnectionError as e:
                logger.error(f"Connection error during message exchange: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error in message exchange: {type(e).__name__}: {e}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                raise

        except Exception as e:
            logger.error(f"Error in _send_message: {type(e).__name__}: {e}")
            raise

        return None

    async def global_controller_msgevent(self,
                                         is_rpc: bool,
                                         message_event_type: str,
                                         message_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send message to global controller.

        Args:
            is_rpc: Whether to expect a response
            message_event_type: Type of message event
            message_payload: Message content

        Returns:
            Response if is_rpc is True, otherwise None
        """
        message_info = {
            'message_type': 'global_controller_msgevent',
            'message_event_type': message_event_type,
            'is_rpc': is_rpc
        }

        return await self._send_message(message_info, message_payload)

    # Other async message methods remain the same

    def get_region(self) -> str:
        """Get the region from the connection."""
        return self.ws_interface.get_region()

    def get_agent(self) -> str:
        """Get the agent from the connection."""
        return self.ws_interface.get_agent()

    def get_plugin(self) -> str:
        """Get the plugin from the connection."""
        return self.ws_interface.get_plugin()


class messaging_sync(messaging):
    """Synchronous wrapper for async messaging functions."""

    def __init__(self, ws_interface):
        """Initialize with a WebSocket interface.

        Args:
            ws_interface: WebSocket interface for communication
        """
        super().__init__(ws_interface)
        self._operation_lock = threading.RLock()  # Reentrant lock for operations
        self._failed_connection = False  # Flag to track if connection has failed

    def global_controller_msgevent(self, is_rpc, message_event_type, message_payload, timeout=8.0, region_id: Optional[str] = None, agent_id: Optional[str] = None):
        """Synchronous wrapper for global_controller_msgevent using direct send.

        Args:
            is_rpc: Whether to expect a response
            message_event_type: Type of message event
            message_payload: Message content
            timeout: Timeout in seconds (default: 8.0)

        Returns:
            Response if is_rpc is True, otherwise None
        """
        # Don't attempt if we know the connection is bad
        if self._failed_connection:
            logger.warning("Not attempting to send message due to known connection failure")
            raise ConnectionError("WebSocket connection has failed")

        with self._operation_lock:  # Thread safety
            try:
                # Prepare message info
                message_info = {
                    'message_type': 'global_controller_msgevent',
                    'message_event_type': message_event_type,
                    'is_rpc': is_rpc
                }
                if (region_id is not None) and (agent_id is not None):
                    message_info['region_id'] = region_id
                    message_info['agent_id'] = agent_id

                # Create complete message
                message = {
                    'message_info': message_info,
                    'message_payload': message_payload
                }

                # Convert to JSON
                json_message = json.dumps(message)

                # Log the operation
                logger.info(f"Sending global_controller_msgevent/{message_event_type} (RPC: {is_rpc})")
                if 'action' in message_payload:
                    logger.info(f"Action: {message_payload['action']}")

                if is_rpc:
                    # For RPC calls, use the direct synchronous send
                    try:
                        response_text = self.ws_interface.send_direct(json_message, timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        # Mark connection as failed for subsequent calls
                        self._failed_connection = True
                        logger.error(f"Connection failure during send_direct: {e}")
                        # Return empty dict instead of raising to allow operation to continue
                        return {}

                    # Parse response
                    try:
                        response = json.loads(response_text)
                        return response
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {response_text[:200]}...")
                        return {}
                else:
                    # For non-RPC calls, use the WebSocket's own async send via run_coroutine_threadsafe
                    # on the WebSocket's own event loop
                    if not self.ws_interface._loop or self.ws_interface._loop.is_closed():
                        logger.error("Event loop is closed or not initialized")
                        self._failed_connection = True
                        return None

                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_interface.send_async(json_message),
                            self.ws_interface._loop
                        )
                        future.result(timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        self._failed_connection = True
                        logger.error(f"Connection failure during async send: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error in global_controller_msgevent: {e}")
                self._failed_connection = True
                return {} if is_rpc else None

    def regional_controller_msgevent(self, is_rpc, message_event_type, message_payload, timeout=8.0, region_id: Optional[str] = None, agent_id: Optional[str] = None):
        """Synchronous wrapper for global_controller_msgevent using direct send.

        Args:
            is_rpc: Whether to expect a response
            message_event_type: Type of message event
            message_payload: Message content
            timeout: Timeout in seconds (default: 8.0)

        Returns:
            Response if is_rpc is True, otherwise None
        """
        # Don't attempt if we know the connection is bad
        if self._failed_connection:
            logger.warning("Not attempting to send message due to known connection failure")
            raise ConnectionError("WebSocket connection has failed")

        with self._operation_lock:  # Thread safety
            try:
                # Prepare message info
                message_info = {
                    'message_type': 'regional_controller_msgevent',
                    'message_event_type': message_event_type,
                    'is_rpc': is_rpc
                }
                if (region_id is not None) and (agent_id is not None):
                    message_info['region_id'] = region_id
                    message_info['agent_id'] = agent_id

                # Create complete message
                message = {
                    'message_info': message_info,
                    'message_payload': message_payload
                }

                # Convert to JSON
                json_message = json.dumps(message)

                # Log the operation
                logger.info(f"Sending regional_controller_msgevent/{message_event_type} (RPC: {is_rpc})")
                if 'action' in message_payload:
                    logger.info(f"Action: {message_payload['action']}")

                if is_rpc:
                    # For RPC calls, use the direct synchronous send
                    try:
                        response_text = self.ws_interface.send_direct(json_message, timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        # Mark connection as failed for subsequent calls
                        self._failed_connection = True
                        logger.error(f"Connection failure during send_direct: {e}")
                        # Return empty dict instead of raising to allow operation to continue
                        return {}

                    # Parse response
                    try:
                        response = json.loads(response_text)
                        return response
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {response_text[:200]}...")
                        return {}
                else:
                    # For non-RPC calls, use the WebSocket's own async send via run_coroutine_threadsafe
                    # on the WebSocket's own event loop
                    if not self.ws_interface._loop or self.ws_interface._loop.is_closed():
                        logger.error("Event loop is closed or not initialized")
                        self._failed_connection = True
                        return None

                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_interface.send_async(json_message),
                            self.ws_interface._loop
                        )
                        future.result(timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        self._failed_connection = True
                        logger.error(f"Connection failure during async send: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error in global_controller_msgevent: {e}")
                self._failed_connection = True
                return {} if is_rpc else None

    # Other synchronous message methods follow the same pattern
    # Implement with improved error handling for each type of message

    def global_agent_msgevent(self, is_rpc, message_event_type, message_payload, dst_region, dst_agent, timeout=8.0):
        """Synchronous wrapper for global_agent_msgevent using direct send."""
        if self._failed_connection:
            logger.warning("Not attempting to send message due to known connection failure")
            return {} if is_rpc else None

        with self._operation_lock:  # Thread safety
            try:
                # Prepare message info
                message_info = {
                    'message_type': 'global_agent_msgevent',
                    'message_event_type': message_event_type,
                    'dst_region': dst_region,
                    'dst_agent': dst_agent,
                    'is_rpc': is_rpc
                }

                # Create complete message
                message = {
                    'message_info': message_info,
                    'message_payload': message_payload
                }

                # Convert to JSON
                json_message = json.dumps(message)

                # Log the operation
                logger.info(
                    f"Sending global_agent_msgevent/{message_event_type} to {dst_region}/{dst_agent} (RPC: {is_rpc})")
                if 'action' in message_payload:
                    logger.info(f"Action: {message_payload['action']}")

                if is_rpc:
                    # For RPC calls, use the direct synchronous send
                    try:
                        response_text = self.ws_interface.send_direct(json_message, timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        # Mark connection as failed for subsequent calls
                        self._failed_connection = True
                        logger.error(f"Connection failure during send_direct: {e}")
                        # Return empty dict instead of raising
                        return {}

                    # Parse response
                    try:
                        response = json.loads(response_text)
                        return response
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {response_text[:200]}...")
                        return {}
                else:
                    # For non-RPC calls, use the WebSocket's own async send
                    if not self.ws_interface._loop or self.ws_interface._loop.is_closed():
                        logger.error("Event loop is closed or not initialized")
                        self._failed_connection = True
                        return None

                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_interface.send_async(json_message),
                            self.ws_interface._loop
                        )
                        future.result(timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        self._failed_connection = True
                        logger.error(f"Connection failure during async send: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error in global_agent_msgevent: {e}")
                self._failed_connection = True
                return {} if is_rpc else None

    async def plugin_msgevent(self, is_rpc: bool, message_event_type: str, message_payload: Dict[str, Any],
                              plugin_name: str) -> Optional[Dict[str, Any]]:
        """Send message to a plugin.

        Args:
            is_rpc: Whether to expect a response
            message_event_type: Type of message event
            message_payload: Message content
            plugin_name: Name of the plugin

        Returns:
            Response if is_rpc is True, otherwise None
        """
        message_info = {
            'message_type': 'plugin_msgevent',
            'message_event_type': message_event_type,
            'plugin_name': plugin_name,
            'is_rpc': is_rpc
        }


        return await self._send_message(message_info, message_payload)

    def plugin_msgevent(self, is_rpc, message_event_type, message_payload, plugin_name, timeout=8.0):
        """Synchronous wrapper for plugin_msgevent using direct send.

        Args:
            is_rpc: Whether to expect a response
            message_event_type: Type of message event
            message_payload: Message content
            plugin_name: Name of the plugin
            timeout: Timeout in seconds (default: 8.0)

        Returns:
            Response if is_rpc is True, otherwise None
        """
        if self._failed_connection:
            logger.warning("Not attempting to send message due to known connection failure")
            return {} if is_rpc else None

        with self._operation_lock:  # Thread safety
            try:
                # Prepare message info
                message_info = {
                    'message_type': 'plugin_msgevent',
                    'message_event_type': message_event_type,
                    'dst_plugin': plugin_name,
                    'is_rpc': is_rpc
                }

                # Create complete message
                message = {
                    'message_info': message_info,
                    'message_payload': message_payload
                }

                # Convert to JSON
                json_message = json.dumps(message)

                # Log the operation
                logger.info(f"Sending plugin_msgevent/{message_event_type} to plugin {plugin_name} (RPC: {is_rpc})")
                if 'action' in message_payload:
                    logger.info(f"Action: {message_payload['action']}")

                if is_rpc:
                    # For RPC calls, use the direct synchronous send
                    try:
                        response_text = self.ws_interface.send_direct(json_message, timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        # Mark connection as failed for subsequent calls
                        self._failed_connection = True
                        logger.error(f"Connection failure during send_direct: {e}")
                        return {}

                    # Parse response
                    try:
                        response = json.loads(response_text)
                        return response
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {response_text[:200]}...")
                        return {}
                else:
                    # For non-RPC calls, use WebSocket's async send
                    if not self.ws_interface._loop or self.ws_interface._loop.is_closed():
                        logger.error("Event loop is closed or not initialized")
                        self._failed_connection = True
                        return None

                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_interface.send_async(json_message),
                            self.ws_interface._loop
                        )
                        future.result(timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        self._failed_connection = True
                        logger.error(f"Connection failure during async send: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error in plugin_msgevent: {e}")
                self._failed_connection = True
                return {} if is_rpc else None

    def global_plugin_msgevent(self, is_rpc, message_event_type, message_payload, dst_region, dst_agent, dst_plugin,
                               timeout=8.0):
        """Synchronous wrapper for sending a message to a specific plugin on a specific agent."""
        if self._failed_connection:
            logger.warning("Not attempting to send message due to known connection failure")
            return {} if is_rpc else None

        with self._operation_lock:
            try:
                message_info = {
                    'message_type': 'global_plugin_msgevent',
                    'message_event_type': message_event_type,
                    'dst_region': dst_region,
                    'dst_agent': dst_agent,
                    'dst_plugin': dst_plugin,
                    'is_rpc': is_rpc
                }
                message = {
                    'message_info': message_info,
                    'message_payload': message_payload
                }
                json_message = json.dumps(message)
                logger.info(
                    f"Sending global_plugin_msgevent/{message_event_type} to {dst_region}/{dst_agent}/{dst_plugin} (RPC: {is_rpc})")
                if 'action' in message_payload:
                    logger.info(f"Action: {message_payload['action']}")

                if is_rpc:
                    try:
                        response_text = self.ws_interface.send_direct(json_message, timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        self._failed_connection = True
                        logger.error(f"Connection failure during send_direct: {e}")
                        return {}

                    try:
                        response = json.loads(response_text)
                        return response
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {response_text[:200]}...")
                        return {}
                else:
                    if not self.ws_interface._loop or self.ws_interface._loop.is_closed():
                        logger.error("Event loop is closed or not initialized")
                        self._failed_connection = True
                        return None

                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_interface.send_async(json_message),
                            self.ws_interface._loop
                        )
                        future.result(timeout=timeout)
                    except (ConnectionError, TimeoutError, concurrent.futures.TimeoutError) as e:
                        self._failed_connection = True
                        logger.error(f"Connection failure during async send: {e}")
                    return None
            except Exception as e:
                logger.error(f"Error in global_plugin_msgevent: {e}")
                self._failed_connection = True
                return {} if is_rpc else None

    def reset_connection_state(self):
        """Reset the connection state flag."""
        with self._operation_lock:
            self._failed_connection = False
            logger.info("Connection state reset")

    def close(self):
        """Clean up resources."""
        # No more thread management here - let ws_interface handle its resources
        pass