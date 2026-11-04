"""
Log streamer implementation for Cresco communications.
"""
import concurrent
import json
import time
import logging
import asyncio
from typing import Dict, Any, Optional, Callable, Union
import websockets
import backoff
from contextlib import asynccontextmanager

from .dataplane import dataplane as _dataplane
from .tls import Credentials, TrustSettings, connect_websocket

# Setup logging
logger = logging.getLogger(__name__)

class logstreamer:
    """Log streamer class for streaming logs in Cresco."""

    def __init__(self, host: str, port: int, service_key: Optional[str] = None, callback: Optional[Callable] = None,
                 *, tls: Optional[TrustSettings] = None, credentials: Optional[Credentials] = None):
        """A log stream. Prefer :meth:`pycrescolib.clientlib.clientlib.get_logstreamer`, which passes the
        client's trust settings and credentials.

        Args:
            tls: how the server certificate is verified (default: verified, see :mod:`pycrescolib.tls`)
            credentials: what the stream authenticates with (default: ``service_key``)
        """
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
        self._tls = tls if tls is not None else TrustSettings()
        self._credentials = credentials if credentials is not None else Credentials(service_key=service_key)
        self.last_error = None  # why the last connect failed (certificate, credentials, network), or None
        self._event_loop = asyncio.new_event_loop()
        self._thread = None

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

            # Close any prior socket before replacing it: silently overwriting leaked the old
            # connection and its server-side session on every reconnect.
            if self.ws is not None:
                try:
                    await self.ws.close()
                except Exception:
                    pass
                self.ws = None

            # Connect
            # TLS verified per the client's trust settings; the credentials go only to a server that passed it
            self.ws = await connect_websocket(ws_url, self.host, self.port, self._tls, self._credentials)

            # Re-arm activation: the FIRST frame of EVERY (re)connected session is the
            # activation status, and the handler gates on message_count == 0. Without this
            # reset a reconnected stream can never re-activate.
            self.message_count = 0
            self.isActive = False

            logger.info("Connected to log streamer")
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = str(e)
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

    async def send_async(self, message: str):
        """Send a message over the log stream asynchronously.

        Args:
            message: Message to send
        """
        if not self.ws:
            logger.warning("Log streamer not connected, cannot send")
            return

        try:
            async with self._lock:
                await self.ws.send(message)
                logger.debug(f"Sent log stream message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error sending log stream message: {e}")
            self.isActive = False

    def send(self, message: str):
        """Send a message over the log stream synchronously.

        Args:
            message: Message to send
        """
        future = asyncio.run_coroutine_threadsafe(self.send_async(message), self._event_loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Error sending log stream message: {e}")
            self.isActive = False

    def connected(self) -> bool:
        """Check if the log streamer is connected.

        Returns:
            True if connected, False otherwise
        """
        return self.isActive

    def connect(self):
        """Connect to the log streamer.

        Returns:
            True once the stream is active; False otherwise (``last_error`` says why when the connection failed).
        """
        import threading
        import time

        if self._event_loop.is_closed():
            self._event_loop = asyncio.new_event_loop()
            self._lock = asyncio.Lock()
        loop = self._event_loop
        first_attempt_done = threading.Event()
        first_attempt_ok = []

        def run():
            self._running = True
            asyncio.set_event_loop(loop)
            try:
                connect_task = loop.create_task(self._connect())
                loop.run_until_complete(connect_task)
                ok = bool(connect_task.result())
                first_attempt_ok.append(ok)
                if ok:
                    self._task = loop.create_task(self._message_handler())
                    self._reconnect_task = loop.create_task(self._reconnect_monitor())
                    loop.create_task(self._wait_for_activation())
                first_attempt_done.set()
                if ok:
                    loop.run_forever()
            except Exception as e:
                logger.error(f"Log streamer event loop error: {e}")
            finally:
                first_attempt_done.set()
                self._running = False
                _dataplane._shutdown_loop(loop)

        thread = threading.Thread(target=run, daemon=True, name="pycrescolib-logstreamer")
        self._thread = thread
        thread.start()

        deadline = time.time() + 5.0
        while not self.isActive and time.time() < deadline:
            if first_attempt_done.is_set() and first_attempt_ok == [False]:
                break
            time.sleep(0.05)

        if not self.isActive:
            if first_attempt_ok == [False]:
                logger.error(f"Log streamer could not connect: {self.last_error}")
            else:
                logger.warning("Timeout waiting for log streamer activation")

        return self.isActive

    async def _wait_for_activation(self):
        """Wait for the log streamer to become active."""
        while not self.isActive and self._running:
            await asyncio.sleep(0.1)

    def close(self):
        """Close the log streamer connection, stop its event loop and close the loop. Idempotent."""
        import threading
        logger.info("Closing log streamer...")

        self._running = False
        self.isActive = False
        loop = self._event_loop
        if loop.is_closed():
            return

        if loop.is_running():
            if self._task:
                loop.call_soon_threadsafe(self._task.cancel)
            if self._reconnect_task:
                loop.call_soon_threadsafe(self._reconnect_task.cancel)
            cleanup_future = asyncio.run_coroutine_threadsafe(self._cleanup_all_tasks(), loop)
            try:
                cleanup_future.result(timeout=2.0)
            except concurrent.futures.TimeoutError:
                logger.warning("Cleanup tasks timed out")
            except Exception as e:
                logger.error(f"Error during task cleanup: {e}")
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
            t = self._thread
            if t is not None and t is not threading.current_thread():
                t.join(timeout=3.0)
                if t.is_alive():
                    logger.warning("Log streamer event loop thread did not stop")
        elif self._thread is None or not self._thread.is_alive():
            _dataplane._shutdown_loop(loop)

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
