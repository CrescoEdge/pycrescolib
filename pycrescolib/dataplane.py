"""
Dataplane implementation for Cresco communications with binary data support.
"""
import concurrent
import json
import os
import time
import logging
import asyncio
import base64
from typing import Dict, Any, Optional, Callable, Union, BinaryIO
import websockets
import backoff
from contextlib import asynccontextmanager

from .tls import (AuthenticationError, CertificateVerificationError, Credentials, TrustSettings,
                  connect_websocket)

#: How long a stream waits before reconnecting after wsapi refused its credentials (401/403), rate-limited its address
#: (429) or presented an untrusted certificate. Retrying every few seconds would only burn wsapi's failure budget for
#: this address (it locks an address out after repeated failures, which stops every client on the host).
PERMANENT_FAILURE_RETRY_S = 60.0

# Setup logging
logger = logging.getLogger(__name__)

#: wsapi activation status: the listener is active
STATUS_ACTIVE = 10
#: wsapi activation status: the broker refused the subscription (another tenant's stream, or a stream bound to
#: another recipient with cresco_to); the stream stays open for sending
STATUS_SUBSCRIPTION_REFUSED = 40


def stdin_stream_refusal(stream_name: str) -> Optional[str]:
    """Why a dataplane stream config would write a process's stdin (None when it does not).

    A JSON config with ``io_type_key`` ``type`` and ``input_id`` ``input`` or ``input-*`` tags every frame it sends as
    a process's stdin. The executor takes stdin only from its ``write_stdin`` action (:mod:`pycrescolib.executor`) and
    reads none from the dataplane, and wsapi refuses such a stream, so it is refused here before connecting.
    """
    try:
        cfg = json.loads(stream_name)
    except (TypeError, ValueError):
        return None
    if not isinstance(cfg, dict) or cfg.get("io_type_key") != "type":
        return None
    t = cfg.get("input_id")
    if isinstance(t, str) and (t == "input" or t.startswith("input-")):
        return (f"a process's stdin (type={t}) is not written on the dataplane: "
                f"use executor.write_stdin (the executor's write_stdin action)")
    return None


class DataplaneSubscriptionRefused(Exception):
    """The broker refused this dataplane subscription (wsapi status 40).

    Raised by :meth:`dataplane.connect` when the dataplane was given a callback (the caller wants to receive). A
    dataplane without callbacks is a sender: it stays connected and can still send.
    """

    def __init__(self, stream_name: str, reason: str):
        super().__init__(f"subscription to dataplane stream {stream_name!r} refused: {reason}")
        self.stream_name = stream_name
        self.reason = reason


class dataplane:
    """Dataplane class for streaming data in Cresco."""

    def __init__(self, host: str, port: int, stream_name: str, service_key: Optional[str] = None,
                 callback: Optional[Callable] = None, binary_callback: Optional[Callable] = None,
                 refused_callback: Optional[Callable[[str], None]] = None, *,
                 tls: Optional[TrustSettings] = None, credentials: Optional[Credentials] = None):
        """A dataplane stream. Prefer :meth:`pycrescolib.clientlib.clientlib.get_dataplane`, which passes the
        client's trust settings and credentials.

        Args:
            tls: how the server certificate is verified (default: verified, see :mod:`pycrescolib.tls`)
            credentials: what the stream authenticates with (default: ``service_key``)
        """
        refusal = stdin_stream_refusal(stream_name)
        if refusal is not None:
            raise ValueError(refusal)
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
        self._tls = tls if tls is not None else TrustSettings()
        self._credentials = credentials if credentials is not None else Credentials(service_key=service_key)
        self.last_error = None  # why the last connect failed (certificate, credentials, network), or None
        self._permanent_failure_at = None  # monotonic time of the last credential / certificate failure
        self._event_loop = asyncio.new_event_loop()
        self._thread = None
        self._partial_fragments = []  # accumulates send_partial() fragments until complete=True
        self.subscription_refused = None  # the broker's reason, when it refused this stream's subscription
        # called with the broker's reason on every refusal, the first connect and every reconnect alike
        self.refused_callback = refused_callback

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
                                    self._on_activation(json.loads(message))
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

    def _permanent_failure_due(self) -> bool:
        """True while the last failure (credentials, rate limit, certificate) is younger than PERMANENT_FAILURE_RETRY_S."""
        at = self._permanent_failure_at
        return at is not None and time.monotonic() - at < PERMANENT_FAILURE_RETRY_S

    async def _reconnect_monitor(self):
        """Monitor the connection and attempt to reconnect if necessary."""
        await asyncio.sleep(2)  # Initial delay before monitoring starts
        while self._running:
            try:
                if self.subscription_refused is not None and self._is_receiver():
                    # refused by policy: retrying every 5 s will not help; look again now and then (a policy can change)
                    await asyncio.sleep(60)
                    if not self._running:
                        break
                    await self._connect()
                    continue
                if not self.isActive or self.ws is None:
                    if self._permanent_failure_due():
                        await asyncio.sleep(5)
                        continue
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
            # TLS verified per the client's trust settings (CA file, pinned fingerprint, or the system store);
            # the credentials are sent only to a server that passed that check.
            self.ws = await connect_websocket(
                ws_url, self.host, self.port, self._tls, self._credentials,
                compression=None,
                # The websockets default (1 MiB) silently capped dataplane messages; the server accepts 1 GiB.
                # Bounded, not unlimited: each connection may buffer this much per message.
                max_size=int(os.environ.get("CRESCO_DATAPLANE_MAX_MESSAGE", 64 * 1024 * 1024)),
                write_limit=4 * 1024 * 1024
            )

            # Re-arm activation: the FIRST frame of EVERY (re)connected session is the
            # activation status, and the handler gates on message_count == 0. Without this
            # reset a reconnected stream misroutes the status frame as data and can never
            # re-activate (the client looks connected while dropping everything).
            self.message_count = 0
            self.isActive = False
            self.subscription_refused = None

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
                if "=" in self.stream_name:
                    # A JMS selector query (e.g. "cresco_msg_type='stunnel_trace'") must go RAW:
                    # the server's stream_query path uses it verbatim as the subscription
                    # selector. Wrapping it as an ident built the invalid selector
                    # stream_name='cresco_msg_type='stunnel_trace'' and the listener never
                    # activated (InvalidSelectorException server-side, silent to the client).
                    # Plain stream names never contain '='; selector queries always do.
                    # NOTE: a query-subscribed connection is receive-only — publishing needs
                    # an ident_key handshake so frames carry a routable identity.
                    handshake = self.stream_name
                else:
                    handshake = _json.dumps({
                        "ident_key": "stream_name",
                        "ident_id": self.stream_name,
                        "io_type_key": "type",
                        "output_id": "output",
                        "input_id": "output",
                    })
            await self.ws.send(handshake)
            logger.info(f"Connected to dataplane stream: {self.stream_name}")
            self.last_error = None
            self._permanent_failure_at = None

            return True
        except Exception as e:
            self.last_error = str(e)
            self._permanent_failure_at = (time.monotonic()
                                          if isinstance(e, (AuthenticationError, CertificateVerificationError)) else None)
            logger.error(f"Dataplane connection error: {e}")
            return False

    def connect(self):
        """Connect to the dataplane stream.

        Returns:
            True once the stream is active. False if it did not activate within 5 s or the connection failed
            (``last_error`` says why: an untrusted certificate, refused credentials, the network).

        Raises:
            DataplaneSubscriptionRefused: a receiver whose subscription the broker refused
        """
        import threading
        import time

        if self._event_loop.is_closed():
            # closed by an earlier close(): a fresh loop (and a lock bound to nothing yet) for this connect
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
                logger.error(f"Dataplane {self.stream_name} event loop error: {e}")
            finally:
                first_attempt_done.set()
                self._running = False
                self._shutdown_loop(loop)

        # Start in a separate thread to avoid blocking
        thread = threading.Thread(target=run, daemon=True, name=f"pycrescolib-dataplane")
        self._thread = thread
        thread.start()

        # Wait for activation with a timeout; stop waiting as soon as the first connection attempt failed
        deadline = time.time() + 5.0
        while not self.isActive and time.time() < deadline:
            if first_attempt_done.is_set() and first_attempt_ok == [False]:
                break
            time.sleep(0.05)

        if not self.isActive:
            if first_attempt_ok == [False]:
                logger.error(f"Dataplane {self.stream_name} could not connect: {self.last_error}")
            else:
                logger.warning(f"Timeout waiting for dataplane {self.stream_name} activation")

        self._raise_if_refused()
        return self.isActive

    @staticmethod
    def _shutdown_loop(loop) -> None:
        """Close an event loop that is no longer running: cancel what is left, then release its resources."""
        try:
            if loop.is_closed():
                return
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception as e:
            logger.debug(f"dataplane loop shutdown: {e}")
        finally:
            try:
                loop.close()
            except Exception as e:
                logger.debug(f"dataplane loop close: {e}")

    def _on_activation(self, status: Dict[str, Any]) -> None:
        """Apply the wsapi activation reply (the first frame of every session)."""
        code = int(status.get('status_code', 0))
        if code == STATUS_ACTIVE:
            self.isActive = True
            logger.info(f"Dataplane {self.stream_name} activated")
        elif code == STATUS_SUBSCRIPTION_REFUSED:
            self.subscription_refused = status.get('status_desc', 'subscription refused')
            if self._is_receiver():
                # a receiver that cannot receive is not active, whether this is the first session or a reconnect
                self.isActive = False
                logger.warning(f"Dataplane {self.stream_name}: {self.subscription_refused} (this receiver gets nothing)")
                if self.refused_callback:
                    try:
                        self.refused_callback(self.subscription_refused)
                    except Exception as e:
                        logger.error(f"Error in refused_callback: {e}")
            else:
                self.isActive = True  # a sender can still send
                logger.warning(f"Dataplane {self.stream_name}: {self.subscription_refused} (open for sending only)")

    def _is_receiver(self) -> bool:
        return bool(self.callback or self.binary_callback)

    def _raise_if_refused(self) -> None:
        """A receiver whose subscription was refused gets a typed error; a pure sender carries on."""
        if self.subscription_refused is not None and self._is_receiver():
            reason = self.subscription_refused
            try:
                self.close()
            except Exception:
                pass
            raise DataplaneSubscriptionRefused(self.stream_name, reason)

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
        """Close the dataplane connection, stop its event loop and close the loop.

        Idempotent. Before, close() stopped the loop but never closed it (nor joined its thread), so every
        dataplane leaked a selector, its socket pair and a thread.
        """
        import threading
        logger.info(f"Closing dataplane {self.stream_name}...")

        # Signal shutdown
        self._running = False
        self.isActive = False
        loop = self._event_loop
        if loop.is_closed():
            return

        if loop.is_running():
            # First, cancel regular tasks
            if self._task:
                loop.call_soon_threadsafe(self._task.cancel)
            if self._reconnect_task:
                loop.call_soon_threadsafe(self._reconnect_task.cancel)

            # Close the socket and cancel what is left, on the loop's own thread
            cleanup_future = asyncio.run_coroutine_threadsafe(self._cleanup_all_tasks(), loop)
            try:
                cleanup_future.result(timeout=2.0)
            except concurrent.futures.TimeoutError:
                logger.warning("Cleanup tasks timed out")
            except Exception as e:
                logger.error(f"Error during task cleanup: {e}")

            # Stop the loop; its thread then closes it (see connect.run)
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass  # closed meanwhile
            t = self._thread
            if t is not None and t is not threading.current_thread():
                t.join(timeout=3.0)
                if t.is_alive():
                    logger.warning(f"Dataplane {self.stream_name} event loop thread did not stop")
        elif self._thread is None or not self._thread.is_alive():
            # never connected (or its thread already ended): nothing runs the loop, close it here
            self._shutdown_loop(loop)

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