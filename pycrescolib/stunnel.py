"""Client-side helper for the io.cresco.stunnel plugin.

Wraps the stunnel plugin's CONFIG/EXEC actions (create / remove / list / status /
config / health check / metrics / network tuning) and its deployment as a
first-class client submodule, mirroring agents / admin / globalcontroller and the
Java client's crescoclient.core.Stunnel method for method. Plugin ids are resolved by name via globalcontroller.find_plugin, so
callers never have to scrape logs or know a plugin's system id.
"""
import json
import logging
from typing import Dict, Any, Optional, List

from .base_classes import CrescoMessageBase
from .utils import decompress_param, get_jar_info

logger = logging.getLogger(__name__)

STUNNEL_PLUGIN_NAME = "io.cresco.stunnel"
# Path of the stunnel jar embedded in the Cresco agent jar (used by deploy_plugin).
STUNNEL_EMBEDDED_JAR = "stunnel.jar"
# status the plugin returns on success
STATUS_OK = "10"
# keys the plugin's nettuning action reads (all integers); others are ignored by the plugin
NET_TUNING_KEYS = ("net_socket_buffer_bytes", "net_read_chunk_bytes", "net_write_high_water_bytes",
                   "net_fc_window_bytes", "net_trace_sample_n")


class stunnel(CrescoMessageBase):
    """Build and manage secure TCP tunnels across the Cresco mesh."""

    def __init__(self, messaging, globalcontroller, agents=None):
        super().__init__(messaging)
        self._gc = globalcontroller
        if agents is None:
            from .agents import agents as _agents
            agents = _agents(messaging)
        self._agents = agents

    def find_plugin(self, region: str, agent: str) -> Optional[str]:
        """Resolve the stunnel plugin_id loaded on an agent (or None).

        Uses the global controller's registration state (reliable) rather than a
        direct per-agent RPC, which can time out on edge nodes. None means the global
        answered "not loaded"; a failed query raises (CrescoQueryError / TimeoutError /
        ConnectionError, see globalcontroller.list_plugins).
        """
        return self._gc.find_plugin(region, agent, STUNNEL_PLUGIN_NAME)

    def deploy_plugin(self, region: str, agent: str, jar_file_path: Optional[str] = None) -> Optional[str]:
        """Ensure exactly one stunnel plugin is running on an agent; returns its plugin_id.

        A no-op when it is already loaded. Otherwise, with jar_file_path the jar is uploaded
        to the agent (pluginupload) and started from there; without it the stunnel jar
        embedded in the agent is started. No CADL pipeline: a direct pluginadd to the agent.

        Before adding, the agent itself is asked (pluginlist): the global's registration
        state can briefly lag the agent (e.g. right after a global restart, until the agent
        re-sends its plugin state), and "the global does not list it" must not start a
        second copy.

        Returns:
            The plugin_id, or None if the upload/add was attempted and failed.

        Raises:
            CrescoQueryError, TimeoutError, ConnectionError: the plugin inventory could not
            be read, so nothing was added (retry later). Before 1.3.2 this case returned
            the result of a blind add and could start a duplicate plugin.
        """
        existing = self.find_plugin(region, agent)
        if existing:
            return existing
        # the global says "not loaded": confirm with the agent (authoritative for what runs there)
        existing = self._agents.find_plugin(region, agent, STUNNEL_PLUGIN_NAME)
        if existing:
            logger.info("stunnel deploy_plugin: %s/%s already runs %s (not yet listed by the global)",
                        region, agent, existing)
            return existing
        try:
            configparams: Dict[str, Any] = {'pluginname': STUNNEL_PLUGIN_NAME}
            if jar_file_path is not None:
                upload = self._agents.upload_plugin_agent(region, agent, jar_file_path)
                if not isinstance(upload, dict) or not upload.get('jar_file_path'):
                    logger.error("stunnel deploy_plugin: upload of %s to %s/%s failed: %s",
                                 jar_file_path, region, agent, upload)
                    return None
                configparams['jarfile'] = upload['jar_file_path']
                jar_info = get_jar_info(jar_file_path)
                if jar_info:
                    configparams['version'] = str(jar_info.get('version'))
                    configparams['md5'] = str(jar_info.get('md5'))
            else:
                configparams['jarfile'] = STUNNEL_EMBEDDED_JAR
            added = self._agents.add_plugin_agent(region, agent, configparams)
            return added.get('pluginid') if isinstance(added, dict) else None
        except Exception as e:
            logger.error("stunnel deploy_plugin on %s/%s failed: %s", region, agent, e)
            return None

    def create_tunnel(self, stunnel_id: str, src_region: str, src_agent: str, src_port: str,
                      dst_region: str, dst_agent: str, dst_host: str, dst_port: str,
                      buffer_size: Optional[str] = "8192",
                      src_plugin_id: Optional[str] = None,
                      dst_plugin_id: Optional[str] = None,
                      watchdog_timeout: Optional[str] = None,
                      performance_report_rate: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a tunnel: a listener on src_port at the source agent forwards to
        dst_host:dst_port reachable from the destination agent. The src stunnel
        plugin coordinates configdsttunnel on the destination itself.

        Plugin ids are auto-resolved by name when not supplied. buffer_size,
        watchdog_timeout (ms) and performance_report_rate (ms) are sent only when
        not None (the plugin applies its defaults otherwise).
        Returns the parsed stunnel_config on success, else None.
        """
        src_plugin_id = src_plugin_id or self.find_plugin(src_region, src_agent)
        dst_plugin_id = dst_plugin_id or self.find_plugin(dst_region, dst_agent)
        if not src_plugin_id or not dst_plugin_id:
            logger.error("stunnel plugin not found (src=%s, dst=%s); ensure %s is loaded on both agents",
                         src_plugin_id, dst_plugin_id, STUNNEL_PLUGIN_NAME)
            return None
        payload = {
            'action': 'configsrctunnel',
            'action_stunnel_id': stunnel_id,
            'action_src_port': str(src_port),
            'action_dst_host': dst_host,
            'action_dst_port': str(dst_port),
            'action_dst_region': dst_region,
            'action_dst_agent': dst_agent,
            'action_dst_plugin': dst_plugin_id,
        }
        if buffer_size is not None:
            payload['action_buffer_size'] = str(buffer_size)
        if watchdog_timeout is not None:
            payload['action_watchdog_timeout'] = str(watchdog_timeout)
        if performance_report_rate is not None:
            payload['action_performance_report_rate'] = str(performance_report_rate)
        result = self.messaging.global_plugin_msgevent(True, 'CONFIG', payload, src_region, src_agent, src_plugin_id)
        if isinstance(result, dict) and 'stunnel_config' in result:
            return json.loads(decompress_param(result['stunnel_config']))
        return result if isinstance(result, dict) else None

    def get_tunnel_list(self, region: str, agent: str, plugin_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List tunnels hosted by the stunnel plugin on an agent."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return []
        result = self.messaging.global_plugin_msgevent(True, 'EXEC', {'action': 'listtunnels'}, region, agent, plugin_id)
        if isinstance(result, dict) and 'tunnels' in result:
            return json.loads(result['tunnels'])
        return []

    def get_tunnel_status(self, region: str, agent: str, stunnel_id: str, plugin_id: Optional[str] = None) -> Optional[Any]:
        """Return the status of a tunnel by id (or None)."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return None
        result = self.messaging.global_plugin_msgevent(True, 'EXEC',
                                                       {'action': 'gettunnelstatus', 'action_stunnel_id': stunnel_id},
                                                       region, agent, plugin_id)
        return result.get('tunnel_status') if isinstance(result, dict) else None

    def get_tunnel_config(self, region: str, agent: str, stunnel_id: str, plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the persisted config of a tunnel by id (or None)."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return None
        result = self.messaging.global_plugin_msgevent(True, 'EXEC',
                                                       {'action': 'gettunnelconfig', 'action_stunnel_id': stunnel_id},
                                                       region, agent, plugin_id)
        if isinstance(result, dict) and 'tunnel_config' in result:
            return json.loads(result['tunnel_config'])
        return None

    def tunnel_health_check(self, region: str, agent: str, stunnel_id: str, plugin_id: Optional[str] = None) -> bool:
        """True if the agent's stunnel plugin holds a config for the tunnel (tunnelhealthcheck,
        the probe the two tunnel ends use on each other)."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return False
        result = self.messaging.global_plugin_msgevent(True, 'EXEC',
                                                       {'action': 'tunnelhealthcheck', 'action_stunnel_id': stunnel_id},
                                                       region, agent, plugin_id)
        return isinstance(result, dict) and result.get('status') == STATUS_OK

    def get_metrics(self, region: str, agent: str, plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The stunnel plugin's live metrics (getmetrics: per-tunnel throughput, sessions,
        flow-control counters) as a dict, or None."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return None
        result = self.messaging.global_plugin_msgevent(True, 'EXEC', {'action': 'getmetrics'}, region, agent, plugin_id)
        if isinstance(result, dict) and result.get('metrics') is not None:
            try:
                return json.loads(result['metrics'])
            except (TypeError, ValueError) as e:
                logger.error("stunnel get_metrics: unparseable metrics from %s/%s: %s", region, agent, e)
        return None

    def set_net_tuning(self, region: str, agent: str, tuning: Dict[str, Any],
                       plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Apply plugin-wide network tuning on an agent's stunnel plugin (nettuning, CONFIG).

        Recognized keys (integers): net_socket_buffer_bytes, net_read_chunk_bytes,
        net_write_high_water_bytes, net_fc_window_bytes, net_trace_sample_n (see
        NET_TUNING_KEYS); unknown keys are ignored by the plugin. New values apply to
        connections opened afterwards. Returns the reply (status "10" on success) or None.
        """
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return None
        payload = {k: str(v) for k, v in tuning.items()}
        payload['action'] = 'nettuning'
        result = self.messaging.global_plugin_msgevent(True, 'CONFIG', payload, region, agent, plugin_id)
        return result if isinstance(result, dict) else None

    def remove_src_tunnel(self, region: str, agent: str, stunnel_id: str, plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Tear down the source side of a tunnel (its listener, sessions and persisted
        config); the source plugin also asks the destination to drop its end."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return None
        return self.messaging.global_plugin_msgevent(True, 'CONFIG',
                                                     {'action': 'removesrctunnel', 'action_stunnel_id': stunnel_id},
                                                     region, agent, plugin_id)

    def remove_dst_tunnel(self, region: str, agent: str, stunnel_id: str, plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Tear down the destination side of a tunnel."""
        plugin_id = plugin_id or self.find_plugin(region, agent)
        if not plugin_id:
            return None
        return self.messaging.global_plugin_msgevent(True, 'CONFIG',
                                                     {'action': 'removedsttunnel', 'action_stunnel_id': stunnel_id},
                                                     region, agent, plugin_id)

    def remove_tunnel(self, stunnel_id: str, src_region: str, src_agent: str,
                      dst_region: str, dst_agent: str,
                      src_plugin_id: Optional[str] = None, dst_plugin_id: Optional[str] = None) -> Dict[str, Any]:
        """Remove both ends of a tunnel (source first, then destination). Plugin ids are
        auto-resolved when omitted. Returns {stunnel_id, src_removal, dst_removal,
        fully_removed}; fully_removed is True when both ends answered."""
        out: Dict[str, Any] = {'stunnel_id': stunnel_id, 'src_removal': None, 'dst_removal': None, 'fully_removed': False}
        out['src_removal'] = self.remove_src_tunnel(src_region, src_agent, stunnel_id, src_plugin_id)
        out['dst_removal'] = self.remove_dst_tunnel(dst_region, dst_agent, stunnel_id, dst_plugin_id)
        out['fully_removed'] = bool(out['src_removal'] and out['dst_removal'])
        return out
