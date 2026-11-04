"""
Client library for Cresco framework interaction with improved resource management.
"""
import logging
import asyncio
import time
import threading
import concurrent.futures
from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager

from .admin import admin
from .agents import agents
from .api import api
from .dataplane import dataplane
from .executor import executor
from .filerepo import filerepo
from .globalcontroller import globalcontroller
from .logstreamer import logstreamer
from .messaging import messaging_sync as messaging
from .stunnel import stunnel
from .tls import Credentials, TrustSettings
from .wc_interface import ws_interface

# Setup logging
logger = logging.getLogger(__name__)


class clientlib:
    """Client library for interacting with Cresco framework."""

    def __init__(self, host: str, port: int, service_key: Optional[str] = None, verify_ssl: Optional[bool] = None, *,
                 ca_file: Optional[str] = None, fingerprint=None, check_hostname: bool = True,
                 user: Optional[str] = None, password: Optional[str] = None):
        """Initialize the client library.

        Every connection this client opens (the API socket, dataplanes and log streams) verifies the wsapi
        server certificate and sends the same credentials. See :mod:`pycrescolib.tls`.

        Args:
            host: Host address
            port: Port number
            service_key: the wsapi service key (an admin of the agent's tenant). Omit it when giving
                ``user`` and ``password``.
            verify_ssl: True verifies the server certificate; False turns verification off (the credentials then
                go to whoever answers, and every connection logs a WARNING). Not given: verified when ``ca_file``,
                ``fingerprint`` or a ``CRESCO_TLS_*`` variable is set, otherwise per
                :data:`pycrescolib.tls.VERIFY_BY_DEFAULT`.
            ca_file: PEM file of trusted certificates (the wsapi writes its own certificate to ws.crt.pem).
            fingerprint: pinned SHA-256 or SHA-384 fingerprint of the wsapi certificate (from ws.fingerprint),
                or a list / comma-separated string of them.
            check_hostname: with ``ca_file`` or the system trust store, check the host name (default True).
            user: per-user credential name (from the wsapi credential store).
            password: per-user credential password.

        Without ``ca_file`` and ``fingerprint`` the environment variables CRESCO_TLS_FINGERPRINT and
        CRESCO_TLS_CA_FILE apply, then (when verifying) the system trust store (and SSL_CERT_FILE).

        Raises:
            pycrescolib.tls.TLSConfigError: unusable trust settings
            ValueError: missing or conflicting credentials
        """
        self.host = host
        self.port = port
        self.service_key = service_key
        self.tls = TrustSettings(verify=verify_ssl, ca_file=ca_file, fingerprint=fingerprint,
                                 check_hostname=check_hostname)
        self.verify_ssl = self.tls.verify
        self.credentials = Credentials(service_key=service_key, user=user, password=password)
        self._lock = threading.RLock()  # Reentrant lock for thread safety

        # Use dictionaries to track resources with identifiers
        self._dataplanes = {}  # stream_name -> dataplane instance
        self._logstreamers = {}  # optional_name -> logstreamer instance

        # Create WebSocket interface first - it will create its own event loop
        self.ws_interface = ws_interface()

        # Setup components with the WebSocket interface after it's initialized
        self.messaging = messaging(self.ws_interface)
        self.agents = agents(self.messaging)
        self.admin = admin(self.messaging)
        self.api = api(self.messaging)
        self.globalcontroller = globalcontroller(self.messaging)
        self.stunnel = stunnel(self.messaging, self.globalcontroller, self.agents)
        self.filerepo = filerepo(self)
        self.executor = executor(self.messaging, self.globalcontroller)

        logger.info(f"Clientlib initialized for {host}:{port} (TLS trust: {self.tls.describe()})")

    @property
    def last_error(self) -> Optional[str]:
        """Why the last connect() failed (certificate, credentials, network), or None."""
        return self.ws_interface.last_error

    def connect(self) -> bool:
        """Connect to the WebSocket server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Reset the messaging connection state if method exists
            if hasattr(self.messaging, 'reset_connection_state'):
                self.messaging.reset_connection_state()

            ws_url = f'wss://{self.host}:{self.port}/api/apisocket'

            # Connect using the WebSocket interface
            connection_result = self.ws_interface.connect(ws_url, tls=self.tls, credentials=self.credentials)

            if connection_result:
                # Sleep briefly to ensure connection is fully established
                time.sleep(0.5)

                # Verify the connection is working properly
                if self.ws_interface.connected():
                    logger.info("Connection verified successfully")
                    return True
                else:
                    logger.warning("Connection reported success but verification failed")
                    return False
            else:
                logger.warning("Connection attempt failed")
                return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    def connected(self) -> bool:
        """Check if connected to the WebSocket server.

        Returns:
            True if connected, False otherwise
        """
        try:
            return self.ws_interface.connected()
        except Exception as e:
            logger.error(f"Error checking connection status: {e}")
            return False

    def get_dataplane(self, stream_name: str, callback: Optional[Callable] = None,
                      binary_callback: Optional[Callable] = None) -> dataplane:
        """Create or retrieve a dataplane instance for streaming data.

        Args:
            stream_name: Name of the stream (acts as an identifier)
            callback: Function for text messages
            binary_callback: Function for binary messages

        Returns:
            Dataplane instance
        """
        with self._lock:
            # Check if we already have a dataplane with this stream name
            if stream_name in self._dataplanes:
                logger.info(f"Returning existing dataplane for stream: {stream_name}")
                return self._dataplanes[stream_name]

            # Create new dataplane
            dp = dataplane(self.host, self.port, stream_name, None, callback, binary_callback,
                           tls=self.tls, credentials=self.credentials)
            logger.debug(f"Created dataplane for stream: {stream_name}")

            # Store with stream name as key
            self._dataplanes[stream_name] = dp
            return dp

    def close_dataplane(self, stream_name: str) -> bool:
        """Close and remove a specific dataplane by stream name.

        Args:
            stream_name: Name of the stream to close

        Returns:
            True if successfully closed, False if not found or error
        """
        with self._lock:
            # Check if the dataplane exists
            if stream_name not in self._dataplanes:
                logger.warning(f"Dataplane for stream '{stream_name}' not found")
                return False

            try:
                # Close the dataplane
                self._dataplanes[stream_name].close()
                # Remove from tracking dictionary
                del self._dataplanes[stream_name]
                logger.info(f"Closed and removed dataplane for stream: {stream_name}")
                return True
            except Exception as e:
                logger.error(f"Error closing dataplane '{stream_name}': {e}")
                return False

    def get_logstreamer(self, name: Optional[str] = None, callback: Optional[Callable] = None) -> logstreamer:
        """Create or retrieve a logstreamer instance.

        Args:
            name: Optional name to identify this logstreamer
            callback: Optional callback for message handling

        Returns:
            Logstreamer instance
        """
        with self._lock:
            # Generate a default name if none provided
            if name is None:
                name = f"logstreamer_{len(self._logstreamers)}"

            # Check if we already have a logstreamer with this name
            if name in self._logstreamers:
                logger.info(f"Returning existing logstreamer: {name}")
                return self._logstreamers[name]

            # Create new logstreamer
            ls = logstreamer(self.host, self.port, None, callback, tls=self.tls, credentials=self.credentials)
            logger.debug(f"Created logstreamer: {name}")

            # Store with name as key
            self._logstreamers[name] = ls
            return ls

    def close_logstreamer(self, name: str) -> bool:
        """Close and remove a specific logstreamer by name.

        Args:
            name: Name of the logstreamer to close

        Returns:
            True if successfully closed, False if not found or error
        """
        with self._lock:
            # Check if the logstreamer exists
            if name not in self._logstreamers:
                logger.warning(f"Logstreamer '{name}' not found")
                return False

            try:
                # Close the logstreamer
                self._logstreamers[name].close()
                # Remove from tracking dictionary
                del self._logstreamers[name]
                logger.info(f"Closed and removed logstreamer: {name}")
                return True
            except Exception as e:
                logger.error(f"Error closing logstreamer '{name}': {e}")
                return False

    def close(self):
        """Close the WebSocket connection and clean up all resources."""
        logger.info("Closing clientlib connection and resources")

        with self._lock:
            # Close all tracked dataplanes
            for stream_name, dp in list(self._dataplanes.items()):
                try:
                    dp.close()
                    logger.debug(f"Closed dataplane: {stream_name}")
                except Exception as e:
                    logger.error(f"Error closing dataplane '{stream_name}': {e}")
            self._dataplanes.clear()

            # Close all tracked logstreamers
            for name, ls in list(self._logstreamers.items()):
                try:
                    ls.close()
                    logger.debug(f"Closed logstreamer: {name}")
                except Exception as e:
                    logger.error(f"Error closing logstreamer '{name}': {e}")
            self._logstreamers.clear()

            # Close WebSocket interface
            if self.ws_interface:
                try:
                    self.ws_interface.close()
                except Exception as e:
                    logger.error(f"Error closing WebSocket interface: {e}")

    def get_active_dataplanes(self):
        """Get a list of active dataplane stream names.

        Returns:
            List of stream names
        """
        with self._lock:
            return list(self._dataplanes.keys())

    def get_active_logstreamers(self):
        """Get a list of active logstreamer names.

        Returns:
            List of logstreamer names
        """
        with self._lock:
            return list(self._logstreamers.keys())

    @contextmanager
    def connection(self):
        """Context manager for client connections.

        Yields:
            The client instance
        """
        connection_successful = False
        try:
            # Attempt to connect
            connection_successful = self.connect()
            if not connection_successful:
                raise ConnectionError("Failed to connect to Cresco server")

            # Connection succeeded, yield the client
            yield self
        finally:
            # Always close the connection when exiting the context
            if connection_successful:
                self.close()