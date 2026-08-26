"""
Dataplane implementation for Cresco communications with binary data support.
"""
import concurrent
import ssl
import json
import time
import logging
import asyncio
import base64
from typing import Dict, Any, Optional, Callable, Union, BinaryIO
import websockets
import backoff
from contextlib import asynccontextmanager

# Setup logging
logger = logging.getLogger(__name__)


class dataplane:
    """Dataplane class for streaming data in Cresco."""

    def __init__(self, host: str, port: int, stream_name: str, service_key: str, callback: Optional[Callable] = None,
                 binary_callback: Optional[Callable] = None):
        self.host = host
        self.port = port
        self.stream_name = stream_name
        self.ws = None
        self.isActive = False
        self.message_count = 0
        # B-2 unified metrics: client-side dataplane counters, exposed via get_metrics().
        self.bytes_received = 0
        self.bytes_sent = 0
        self.messages_sent = 0
        self.callback = callback  # For text messages
        self.binary_callback = binary_callback  # For binary messages
        self._task = None
        self._running = False
        self._reconnect_task = None
        self._lock = asyncio.Lock()
        self._service_key = service_key  # Use the provided service key
        self._event_loop = asyncio.new_event_loop()
        self._partial_fragments = []  # accumulates send_partial() fragments until complete=True

    def is_active(self) -> bool:
        """Check if dataplane is active.

        Returns:
            True if active, False otherwise
        """
        return self.isActive

    def connected(self) -> bool:
        """Check if the dataplane is connected.

        Returns:
            True if connected, False otherwise
        """
        return self.isActive

    async def _message_handler(self):
        """Handle incoming messages, with support for both text and binary."""
        while self._running:
            try:
                if self.ws:
                    try:
                        message = await self.ws.recv()
                        # Defensive copy: with compression disabled, websockets can hand back a
                        # bytearray/memoryview backed by a reusable read buffer. Because we dispatch
                        # the callback via run_in_executor (i.e. later), the buffer can be recycled
                        # under us and the payload seen by the callback is corrupted. Snapshot it.
                        if isinstance(message, (bytearray, memoryview)):
                            message = bytes(message)
                        logger.debug(f"Raw dataplane message received, type: {type(message)}")

                        # Handle activation message
                        if self.message_count == 0:
                            try:
                                # Activation message should be text/JSON
                                if isinstance(message, str):
                                    json_incoming = json.loads(message)
                                    if int(json_incoming.get('status_code', 0)) == 10:
                                        self.isActive = True
                                        logger.info(f"Dataplane {self.stream_name} activated")
                                else:
                                    # Not expected to get binary for activation
                                    logger.warning("Received binary data for activation message")
                            except json.JSONDecodeError:
                                logger.error(f"Invalid JSON in activation message")
                        # Handle regular messages
                        else:
                            if isinstance(message, bytes):
                                # Binary message
                                if self.binary_callback:
                                    try:
                                        await asyncio.get_event_loop().run_in_executor(None, self.binary_callback, message)
                                    except Exception as e:
                                        logger.error(f"Error in binary callback: {e}")
                                elif self.callback:
                                    # Fall back to the regular callback if binary_callback is not set
                                    logger.warning("Received binary data but no binary_callback set, using regular callback")
                                    try:
                                        await asyncio.get_event_loop().run_in_executor(None, self.callback, message)
                                    except Exception as e:
                                        logger.error(f"Error in callback with binary data: {e}")
                                else:
                                    logger.info(f"Binary dataplane message received (no callback): {len(message)} bytes")
                            else:
                                # Text message
                                if self.callback:
                                    try:
                                        await asyncio.get_event_loop().run_in_executor(None, self.callback, message)
                                    except Exception as e:
                                        logger.error(f"Error in callback: {e}")
                                else:
                                    logger.info(f"Dataplane message (no callback): {message[:200]}...")

                        self.message_count += 1
                        try:
                            self.bytes_received += len(message)
                        except Exception:
                            pass
                    except websockets.ConnectionClosed:
                        logger.warning(f"Dataplane connection closed for {self.stream_name}")
                        self.isActive = False
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Error receiving message: {e}")
                        self.isActive = False
                        await asyncio.sleep(1)
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in dataplane message handler: {e}")
                await asyncio.sleep(1)

    async def _reconnect_monitor(self):
        """Monitor the connection and attempt to reconnect if necessary."""
        await asyncio.sleep(2)  # Initial delay before monitoring starts
        while self._running:
            try:
                if not self.isActive or self.ws is None:
                    logger.warning(f"Dataplane connection lost for {self.stream_name}, attempting to reconnect...")
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
            ws_url = f'wss://{self.host}:{self.port}/api/dataplane'

            # Setup SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # Headers for authentication
            headers = {'cresco_service_key': self._service_key}

            # Close any prior socket before replacing it: silently overwriting leaked the old
            # connection and its server-side session on every reconnect (visible as an endless
            # stream of new client sessions on the wsapi side).
            if self.ws is not None:
                try:
                    await self.ws.close()
                except Exception:
                    pass
                self.ws = None

            # Connect. compression=None disables permessage-deflate: the dataplane carries
            # mostly binary/incompressible payloads, and per-message deflate is a large CPU cost
            # on both ends that caps throughput (it was the dominant dataplane bottleneck).
            self.ws = await websockets.connect(
                ws_url,
                ssl=ssl_context,
                additional_headers=headers,
                compression=None
            )

            # Re-arm activation: the FIRST frame of EVERY (re)connected session is the
            # activation status, and the handler gates on message_count == 0. Without this
            # reset a reconnected stream misroutes the status frame as data and can never
            # re-activate (the client looks connected while dropping everything).
            self.message_count = 0
            self.isActive = False

            # Send the stream handshake as a JSON config map. The wsapi DataPlaneWsHandler only
            # populates StreamInfo.identKey/identId (and builds a valid JMS selector) when the
            # first frame is a JSON map with "ident_key"; the raw stream-name form leaves
            # identKey NULL, which makes published frames throw "Property name cannot be empty
            # or null" AND makes subscriber selectors invalid (the raw name is used verbatim as
            # a JMS selector and matches nothing). Mirrors the Java reference client and the
            # cppcrescolib fix (CrescoEdge/cppcrescolib@537c0d3).
            import json as _json
            # Callers pass either a plain stream name (wrap it in the config map) or a full
            # config-map JSON (send AS-IS: wrapping it again would make the entire JSON string
            # the stream identity, so two endpoints whose configs differ by a single byte of
            # whitespace would silently land on different streams and never see each other).
            handshake = None
            try:
                parsed = _json.loads(self.stream_name)
                if isinstance(parsed, dict) and "ident_key" in parsed:
                    handshake = self.stream_name
            except Exception:
                pass
            if handshake is None:
                handshake = _json.dumps({
                    "ident_key": "stream_name",
                    "ident_id": self.stream_name,
                    "io_type_key": "type",
                    "output_id": "output",
                    "input_id": "output",
                })
            await self.ws.send(handshake)
            logger.info(f"Connected to dataplane stream: {self.stream_name}")

            return True
        except Exception as e:
            logger.error(f"Dataplane connection error: {e}")
            return False

    def connect(self):
        """Connect to the dataplane stream."""

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

                # No need to wait for activation before returning - start async task instead
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
            logger.warning(f"Timeout waiting for dataplane {self.stream_name} activation")

        return self.isActive

    async def _wait_for_activation(self):
        """Wait for the dataplane to become active."""
        while not self.isActive and self._running:
            await asyncio.sleep(0.1)

    async def send_async(self, data: Union[str, bytes]):
        """Send data asynchronously, supporting both text and binary.

        Args:
            data: Data to send, can be string or bytes
        """
        if not self.isActive:
            logger.warning("Dataplane not active, cannot send data")
            return

        try:
            async with self._lock:
                await self.ws.send(data)
                try:
                    self.bytes_sent += len(data)
                    self.messages_sent += 1
                except Exception:
                    pass
                if isinstance(data, bytes):
                    logger.debug(f"Sent binary data to dataplane: {len(data)} bytes")
                else:
                    logger.debug(f"Sent text data to dataplane: {data[:100]}...")
        except Exception as e:
            logger.error(f"Error sending data to dataplane: {e}")
            self.isActive = False

    def get_metrics(self) -> dict:
        """B-2 unified metrics: client-side dataplane counters for this stream connection.

        Returns:
            dict of messages/bytes sent and received on this dataplane connection.
        """
        return {
            'stream_name': self.stream_name,
            'messages_received': self.message_count,
            'messages_sent': self.messages_sent,
            'bytes_received': self.bytes_received,
            'bytes_sent': self.bytes_sent,
            'active': self.isActive,
        }

    def send(self, data: Union[str, bytes]):
        """Send data synchronously, supporting both text and binary.

        Args:
            data: Data to send, can be string or bytes
        """
        if not self.isActive:
            logger.warning("Dataplane not active, cannot send data")
            return

        # Use event loop to send data
        future = asyncio.run_coroutine_threadsafe(self.send_async(data), self._event_loop)

        try:
            # Wait for result with timeout
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Error sending data to dataplane: {e}")
            self.isActive = False

    async def send_binary_async(self, data: bytes):
        """Send binary data asynchronously.

        Args:
            data: Binary data to send
        """
        if not isinstance(data, bytes):
            raise TypeError("Data must be bytes for send_binary_async")
        await self.send_async(data)

    def send_binary(self, data: bytes):
        """Send binary data synchronously.

        Args:
            data: Binary data to send
        """
        if not isinstance(data, bytes):
            raise TypeError("Data must be bytes for send_binary")
        self.send(data)

    def send_binary_file(self, file_path: str):
        """Read and send a binary file.

        Args:
            file_path: Path to the binary file
        """
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            self.send_binary(data)
            logger.info(f"Sent binary file {file_path} ({len(data)} bytes)")
        except Exception as e:
            logger.error(f"Error sending binary file {file_path}: {e}")
            raise

    async def send_partial_async(self, data: bytes, complete: bool):
        """Send a binary payload as a fragmented WebSocket message asynchronously.

        Each call appends a fragment; when complete is True the accumulated fragments are
        flushed as a single fragmented binary message. Mirrors the Java send_partial(data,
        complete) partial-frame streaming API.

        Args:
            data: Binary fragment to append
            complete: True when this is the final fragment (triggers the send)
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("Data must be bytes for send_partial_async")
        if not self.isActive:
            logger.warning("Dataplane not active, cannot send data")
            return

        try:
            async with self._lock:
                self._partial_fragments.append(bytes(data))
                if complete:
                    fragments = self._partial_fragments
                    self._partial_fragments = []
                    await self.ws.send(fragments)
                    logger.debug(f"Sent fragmented binary message: {len(fragments)} fragment(s)")
        except Exception as e:
            logger.error(f"Error sending partial data to dataplane: {e}")
            self.isActive = False

    def send_partial(self, data: bytes, complete: bool):
        """Send a binary payload as a fragmented WebSocket message synchronously.

        Each call appends a fragment; when complete is True the accumulated fragments are
        flushed as a single fragmented binary message. Mirrors the Java send_partial(data,
        complete) partial-frame streaming API.

        Args:
            data: Binary fragment to append
            complete: True when this is the final fragment (triggers the send)
        """
        if not self.isActive:
            logger.warning("Dataplane not active, cannot send data")
            return

        future = asyncio.run_coroutine_threadsafe(self.send_partial_async(data, complete), self._event_loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Error sending partial data to dataplane: {e}")
            self.isActive = False

    def update_config(self, dst_region: str, dst_agent: str):
        """Update the dataplane stream configuration.

        Args:
            dst_region: Target region
            dst_agent: Target agent
        """
        self.send(f'{dst_region},{dst_agent},Trace,default')

    def close(self):
        """Close the dataplane connection with proper task cleanup."""
        logger.info(f"Closing dataplane {self.stream_name}...")

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

        logger.info(f"Dataplane {self.stream_name} closed")

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

    @asynccontextmanager
    async def connection_context(self):
        """Context manager for dataplane connections.

        Yields:
            The dataplane instance
        """
        try:
            self.connect()
            yield self
        finally:
            self.close()