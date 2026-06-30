"""
Improved WebSocket interface for Cresco library.
Uses direct WebSocket communication with proper thread and event loop handling.
"""
import ssl
import warnings

from cryptography import x509

import logging
import json
import asyncio
import time
import threading
import concurrent.futures
from typing import Optional, Dict, Any

import websockets

# Configure logging
logger = logging.getLogger(__name__)


class ws_interface:
    """WebSocket interface for Cresco communication with proper threading."""

    def __init__(self):
        """Initialize the WebSocket interface."""
        self.url = None
        self.ws = None
        self.region = None
        self.agent = None
        self.plugin = None
        self._loop = None
        self._thread = None
        self._running = False
        self._service_key = None
        self._verify_ssl = None
        self._connected = False
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._shutdown_flag = False  # Flag to indicate shutdown in progress

    def connect(self, url, service_key, verify_ssl=True):
        """Store connection parameters and initialize the event loop.

        Args:
            url: WebSocket URL
            service_key: Service key for authentication
            verify_ssl: Whether to verify SSL certificates

        Returns:
            True if connection setup was successful
        """
        self.url = url
        self._service_key = service_key
        self._verify_ssl = verify_ssl
        self._shutdown_flag = False

        logger.info(f"Preparing connection to {url}")

        # Set up event loop in a dedicated thread
        self._initialize_event_loop()

        # Perform actual connection
        future = asyncio.run_coroutine_threadsafe(
            self.connect_async(),
            self._loop
        )

        try:
            # Wait for result with timeout
            result = future.result(timeout=10.0)
            self._connected = result
            return result
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self._connected = False
            return False

    def _initialize_event_loop(self):
        """Initialize event loop in a dedicated thread."""
        with self._lock:
            if self._loop is None or self._thread is None or not self._thread.is_alive():
                # Create a new event loop
                self._loop = asyncio.new_event_loop()
                self._running = True

                # Start it in a dedicated thread
                def run_event_loop():
                    asyncio.set_event_loop(self._loop)
                    try:
                        self._loop.run_forever()
                    except Exception as e:
                        logger.error(f"Event loop error: {e}")
                    finally:
                        # Clean up tasks that might still be running
                        self._cleanup_pending_tasks()
                        self._loop.close()
                        logger.info("Event loop closed")
                        self._running = False

                self._thread = threading.Thread(target=run_event_loop, daemon=True)
                self._thread.start()

                # Wait for thread to start
                time.sleep(0.2)

    def _cleanup_pending_tasks(self):
        """Clean up any pending tasks in the event loop."""
        try:
            # Get all tasks in the loop
            if hasattr(asyncio, 'all_tasks'):
                pending_tasks = asyncio.all_tasks(self._loop)
            else:
                pending_tasks = asyncio.tasks._all_tasks(self._loop)

            if pending_tasks:
                logger.info(f"Cancelling {len(pending_tasks)} pending tasks")

                # Cancel all tasks
                for task in pending_tasks:
                    task.cancel()

                # Use run_until_complete to allow tasks to finish cancellation
                if not self._loop.is_closed():
                    # This gives tasks opportunity to handle cancellation
                    self._loop.run_until_complete(
                        asyncio.gather(*pending_tasks, return_exceptions=True)
                    )
            else:
                logger.info("No pending tasks to cancel")
        except Exception as e:
            logger.error(f"Error during task cleanup: {e}")

    async def connect_async(self):
        """Establish WebSocket connection asynchronously."""

        logger.info(f"Connecting to {self.url}")

        try:
            # Configure SSL
            ssl_context = None
            if self.url.startswith('wss://'):
                ssl_context = ssl.create_default_context()
                if not self._verify_ssl:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    logger.debug("SSL certificate verification disabled")

            # Connect to WebSocket with a timeout
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.url,
                    ssl=ssl_context if self.url.startswith('wss://') else None,
                    additional_headers={'cresco_service_key': self._service_key}
                ),
                timeout=8.0
            )

            # Extract certificate information
            try:
                # Get host and port from URL
                surl = self.url.split('/')[2].split(':')
                server_address = (surl[0], int(surl[1]))

                # Get server certificate
                pem_data = ssl.get_server_certificate(server_address)
                cert = x509.load_pem_x509_certificate(str.encode(pem_data))
                # Suppress all warnings from the 'cryptography' module
                ident_string = cert.subject.rfc4514_string().replace('CN=', '').split('_')

                # Set identity values
                self.region = ident_string[0]
                self.agent = ident_string[1]
                self.plugin = ident_string[2]

                logger.info(
                    f"Extracted identity from certificate: region={self.region}, agent={self.agent}, plugin={self.plugin}")
            except Exception as e:
                logger.error(f"Error extracting certificate info: {e}")
                # If extraction fails, set to None
                self.region = None
                self.agent = None
                self.plugin = None

            logger.info("WebSocket connection established successfully")
            return True
        except asyncio.TimeoutError:
            logger.error("Connection attempt timed out")
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    def connected(self):
        """Check if connected to the WebSocket server."""
        return self._connected and self.ws is not None and not self._shutdown_flag

    async def close_async(self):
        """Close the WebSocket connection asynchronously."""
        if self.ws:
            try:
                # Use a timeout to avoid hanging
                await asyncio.wait_for(self.ws.close(), timeout=2.0)
                logger.info("WebSocket connection closed")
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("WebSocket close operation timed out or was cancelled")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
            finally:
                self.ws = None
                self._connected = False

    def close(self):
        """Close the WebSocket connection and clean up resources."""
        # Set the shutdown flag to prevent new operations
        self._shutdown_flag = True
        self._connected = False

        if self.ws:
            # Close the WebSocket in the event loop
            try:
                # Use a timeout to prevent hanging forever
                future = asyncio.run_coroutine_threadsafe(
                    self.close_async(),
                    self._loop
                )
                future.result(timeout=3.0)
            except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                logger.warning("WebSocket close operation timed out")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

        # Stop the event loop with a timeout
        if self._loop and self._running:
            try:
                # First, clean up any pending tasks directly
                future = asyncio.run_coroutine_threadsafe(
                    self._cleanup_all_tasks(),
                    self._loop
                )
                try:
                    future.result(timeout=2.0)
                except Exception as e:
                    logger.error(f"Error during task cleanup: {e}")

                # Then stop the loop
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception as e:
                logger.error(f"Error stopping event loop: {e}")

        # Wait for thread to finish with a reasonable timeout
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("Event loop thread did not terminate cleanly")

    async def _cleanup_all_tasks(self):
        """Helper method to clean up all tasks in the event loop."""
        # This is run inside the event loop, so we can directly access and cancel tasks
        try:
            # Get all tasks that are not this one
            current_task = asyncio.current_task()
            if hasattr(asyncio, 'all_tasks'):
                all_tasks = asyncio.all_tasks(self._loop)
            else:
                all_tasks = asyncio.tasks._all_tasks(self._loop)

            tasks_to_cancel = [t for t in all_tasks if t is not current_task]

            if tasks_to_cancel:
                logger.info(f"Cancelling {len(tasks_to_cancel)} tasks")
                for task in tasks_to_cancel:
                    task.cancel()

                # Allow cancelled tasks to run their cancellation callbacks
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error in task cleanup: {e}")

    def send_direct(self, json_message, timeout=8.0):
        """Send a message and receive response synchronously.

        Args:
            json_message: JSON message as string
            timeout: Timeout in seconds

        Returns:
            Response text
        """
        if self._shutdown_flag:
            logger.error("Cannot send message during shutdown")
            raise ConnectionError("WebSocket is shutting down")

        if not self.connected():
            logger.error("WebSocket not connected")
            raise ConnectionError("WebSocket not connected")

        # Safe access to the event loop
        with self._lock:
            if not self._loop or self._loop.is_closed():
                logger.error("Event loop is closed or not initialized")
                raise RuntimeError("Event loop is closed or not initialized")

            # Create a future in the SAME thread as the event loop
            future = asyncio.run_coroutine_threadsafe(
                self._send_receive(json_message, timeout),
                self._loop
            )

            try:
                logger.info(f"Sending message directly")
                return future.result(timeout + 1.0)  # Add 1 sec buffer for future overhead
            except asyncio.TimeoutError:
                logger.error(f"Timeout waiting for response after {timeout} seconds")
                future.cancel()  # Cancel the operation to avoid hanging coroutines
                raise TimeoutError(f"Operation timed out after {timeout} seconds")
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                raise

    async def _send_receive(self, json_message, timeout):
        """Send a message and receive a response as a coroutine with timeout.

        Args:
            json_message: JSON message as string
            timeout: Timeout in seconds

        Returns:
            Response text
        """
        if not self.ws:
            raise ConnectionError("WebSocket not connected")

        try:
            # Send with timeout
            await asyncio.wait_for(self.ws.send(json_message), timeout=timeout / 2)
            # Receive with timeout
            return await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Operation timed out after {timeout} seconds")
            raise TimeoutError(f"Operation timed out after {timeout} seconds")
        except Exception as e:
            logger.error(f"Error in WebSocket send/receive: {e}")
            raise

    # Legacy methods for backward compatibility
    async def send_async(self, message):
        """Legacy async send method."""
        if not self.ws:
            logger.error("WebSocket not connected")
            raise ConnectionError("WebSocket not connected")

        await self.ws.send(message)
        return True

    async def recv_async(self):
        """Legacy async receive method."""
        if not self.ws:
            logger.error("WebSocket not connected")
            raise ConnectionError("WebSocket not connected")

        return await self.ws.recv()

    async def send(self, message):
        """Legacy send method that returns response."""
        await self.send_async(message)
        return await self.recv_async()

    async def recv(self):
        """Legacy receive method."""
        return await self.recv_async()

    def get_region(self):
        """Get the region from connection information."""
        return self.region

    def get_agent(self):
        """Get the agent from connection information."""
        return self.agent

    def get_plugin(self):
        """Get the plugin from connection information."""
        return self.plugin