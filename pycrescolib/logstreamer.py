"""
Log streamer implementation for Cresco communications.
"""
import concurrent
import ssl
import json
import time
import logging
import asyncio
from typing import Dict, Any, Optional, Callable, Union
import websockets
import backoff
from contextlib import asynccontextmanager

# Setup logging
logger = logging.getLogger(__name__)

class logstreamer:
    """Log streamer class for streaming logs in Cresco."""

    def __init__(self, host: str, port: int, service_key: str, callback: Optional[Callable] = None):
        self.host = host
        self.port = port
        self.ws = None
        self.isActive = False
        self.message_count = 0
        self.callback = callback
        self._task = None
        self._running = False
        self._reconnect_task = None
        self._lock = asyncio.Lock()
        self._service_key = service_key  # Use the provided service key
        self._event_loop = asyncio.new_event_loop()

    async def _message_handler(self):
        """Handle incoming messages."""
        while self._running:
            try:
                if self.ws:
                    try:
                        message = await self.ws.recv()
                        logger.debug(f"Raw log message received: {message[:100]}...")

                        # Handle activation message
                        if self.message_count == 0:
                            try:
                                json_incoming = json.loads(message)
                                if int(json_incoming.get('status_code', 0)) == 10:
                                    self.isActive = True
                                    logger.info("Log streamer activated")
                            except json.JSONDecodeError:
                                logger.error(f"Invalid JSON in activation message: {message}")
                        # Handle regular messages
                        else:
                            if self.callback:
                                # Call the callback directly for better debugging
                                try:
                                    await asyncio.get_event_loop().run_in_executor(None, self.callback, message)
                                except Exception as e:
                                    logger.error(f"Error in callback: {e}")
                            else:
                                logger.info(f"Log message (no callback): {message[:200]}...")

                        self.message_count += 1
                    except Exception as e:
                        logger.error(f"Error receiving message: {e}")
                        await asyncio.sleep(1)
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in log streamer message handler: {e}")
                await asyncio.sleep(1)

    async def _reconnect_monitor(self):
        """Monitor the connection and attempt to reconnect if necessary."""
        await asyncio.sleep(2)
        while self._running:
            try:
                if not self.isActive or self.ws is None:
                    logger.warning("Log streamer connection lost, attempting to reconnect...")
                    self.isActive = False
                    await self._connect()
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in reconnect monitor: {e}")
                await asyncio.sleep(1)

    @backoff.on_exception(backoff.expo,
                         (ConnectionError, TimeoutError, websockets.ConnectionClosed),
                         max_tries=3)
    async def _connect(self) -> bool:
        """Connect to the WebSocket with retry logic.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            ws_url = f'wss://{self.host}:{self.port}/api/logstreamer'

            # Setup SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # Headers for authentication
            headers = {'cresco_service_key': self._service_key}

            # Connect
            self.ws = await websockets.connect(
                ws_url,
                ssl=ssl_context,
                additional_headers=headers
            )

            logger.info("Connected to log streamer")
            return True
        except Exception as e:
            logger.error(f"Log streamer connection error: {e}")
            return False

    async def update_config_async(self, dst_region: str, dst_agent: str):
        """Update log configuration asynchronously."""
        if not self.ws:
            logger.warning("Log streamer not connected, cannot update config")
            return

        message = f'{dst_region},{dst_agent},Trace,default'

        try:
            await self.ws.send(message)
            logger.info(f"Sent log stream configuration: {message}")
        except Exception as e:
            logger.error(f"Error updating log config: {e}")
            self.isActive = False

    async def update_config_class_async(self, dst_region: str, dst_agent: str, loglevel: str, baseclass: str):
        """Update log configuration with class detail asynchronously.

        Args:
            dst_region: Target region
            dst_agent: Target agent
            loglevel: Log level
            baseclass: Base class
        """
        if not self.ws:
            logger.warning("Log streamer not connected, cannot update config")
            return

        message = f'{dst_region},{dst_agent},{loglevel},{baseclass}'

        try:
            async with self._lock:
                await self.ws.send(message)
                logger.debug(f"Updated log config: {message}")
        except Exception as e:
            logger.error(f"Error updating log config: {e}")
            self.isActive = False

    def update_config(self, dst_region: str, dst_agent: str):
        """Update log configuration synchronously.
        
        Args:
            dst_region: Target region
            dst_agent: Target agent
        """
        # Use event loop to send config update
        future = asyncio.run_coroutine_threadsafe(
            self.update_config_async(dst_region, dst_agent), 
            self._event_loop
        )
        
        try:
            # Wait for result with timeout
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Error updating log config: {e}")
            self.isActive = False


    def update_config_class(self, dst_region: str, dst_agent: str, loglevel: str, baseclass: str):
        """Update log configuration with class detail synchronously.
        
        Args:
            dst_region: Target region
            dst_agent: Target agent
            loglevel: Log level
            baseclass: Base class
        """
        # Use event loop to send config update
        future = asyncio.run_coroutine_threadsafe(
            self.update_config_class_async(dst_region, dst_agent, loglevel, baseclass), 
            self._event_loop
        )
        
        try:
            # Wait for result with timeout
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Error updating log config: {e}")
            self.isActive = False

    def connect(self):
        """Connect to the log streamer."""

        def run():
            self._running = True

            # Setup and start the event loop
            asyncio.set_event_loop(self._event_loop)

            # Create tasks
            connect_task = self._event_loop.create_task(self._connect())
            self._event_loop.run_until_complete(connect_task)

            if connect_task.result():
                self._task = self._event_loop.create_task(self._message_handler())
                self._reconnect_task = self._event_loop.create_task(self._reconnect_monitor())

                # No need to wait for activation before returning in the main thread
                # Just start the activation check task
                self._event_loop.create_task(self._wait_for_activation())

            # Run event loop forever
            self._event_loop.run_forever()

        # Start in a separate thread to avoid blocking
        import threading
        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        # Wait for activation with a timeout
        import time
        start_time = time.time()
        timeout = 5.0  # 5 second timeout

        while not self.isActive and time.time() - start_time < timeout:
            time.sleep(0.1)

        if not self.isActive:
            logger.warning("Timeout waiting for log streamer activation")

        return self.isActive

    async def _wait_for_activation(self):
        """Wait for the log streamer to become active."""
        while not self.isActive and self._running:
            await asyncio.sleep(0.1)

    def close(self):
        """Close the log streamer connection with proper task cleanup."""
        logger.info("Closing log streamer...")

        # Signal shutdown
        self._running = False
        self.isActive = False

        # First, cancel regular tasks
        if self._task:
            self._event_loop.call_soon_threadsafe(self._task.cancel)
        if self._reconnect_task:
            self._event_loop.call_soon_threadsafe(self._reconnect_task.cancel)

        # Create and run a cleanup task
        cleanup_future = asyncio.run_coroutine_threadsafe(
            self._cleanup_all_tasks(),
            self._event_loop
        )

        try:
            # Give it a short time to complete
            cleanup_future.result(timeout=1.0)
        except concurrent.futures.TimeoutError:
            logger.warning("Cleanup tasks timed out")
        except Exception as e:
            logger.error(f"Error during task cleanup: {e}")

        # Stop the event loop
        try:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            # Wait briefly for the event loop to stop
            import time
            time.sleep(0.2)
        except Exception as e:
            logger.error(f"Error stopping event loop: {e}")

        logger.info("Log streamer closed")

    async def _cleanup_all_tasks(self):
        """Clean up all tasks in the event loop."""
        try:
            # Close the WebSocket connection
            if self.ws:
                try:
                    await asyncio.shield(self.ws.close(code=1000))
                except Exception as e:
                    logger.error(f"Error closing WebSocket: {e}")

            # Cancel all tasks except this one
            current = asyncio.current_task()
            tasks = [task for task in asyncio.all_tasks(self._event_loop)
                     if task is not current]

            if tasks:
                logger.debug(f"Cancelling {len(tasks)} pending tasks")
                for task in tasks:
                    task.cancel()

                # Wait for tasks to complete cancellation (with timeout)
                await asyncio.wait(tasks, timeout=0.5)

            return True
        except Exception as e:
            logger.error(f"Error in task cleanup: {e}")
            return False

    async def _close_ws(self):
        """Close the WebSocket connection without waiting for confirmation."""
        try:
            await self.ws.close(code=1000)
        except Exception as e:
            logger.error(f"Error in WebSocket close: {e}")

    @asynccontextmanager
    async def connection_context(self):
        """Context manager for log streamer connections.
        
        Yields:
            The log streamer instance
        """
        try:
            self.connect()
            yield self
        finally:
            self.close()
