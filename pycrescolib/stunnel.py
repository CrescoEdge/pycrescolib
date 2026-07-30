"""Client-side helper for the io.cresco.stunnel plugin.

Wraps the stunnel plugin's CONFIG/EXEC actions (create / remove / list / status /
config) as a first-class client submodule, mirroring agents / admin /
globalcontroller. Plugin ids are resolved by name via agents.find_plugin, so
callers never have to scrape logs or know a plugin's system id.
"""
import json
import logging
from typing import Dict, Any, Optional, List

from .base_classes import CrescoMessageBase
from .utils import decompress_param

logger = logging.getLogger(__name__)

STUNNEL_PLUGIN_NAME = "io.cresco.stunnel"


class stunnel(CrescoMessageBase):
    """Build and manage secure TCP tunnels across the Cresco mesh."""

    def __init__(self, messaging, globalcontroller):
        super().__init__(messaging)
        self._gc = globalcontroller

    def find_plugin(self, region: str, agent: str) -> Optional[str]:
        """Resolve the stunnel plugin_id loaded on an agent (or None).

        Uses the global controller's registration state (reliable) rather than a
        direct per-agent RPC, which can time out on edge nodes.
        """
        return self._gc.find_plugin(region, agent, STUNNEL_PLUGIN_NAME)

    def create_tunnel(self, stunnel_id: str, src_region: str, src_agent: str, src_port: str,
                      dst_region: str, dst_agent: str, dst_host: str, dst_port: str,
                      buffer_size: str = "8192",
                      src_plugin_id: Optional[str] = None,
                      dst_plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Create a tunnel: a listener on src_port at the source agent forwards to
        dst_host:dst_port reachable from the destination agent. The src stunnel
        plugin coordinates configdsttunnel on the destination itself.

        Plugin ids are auto-resolved by name when not supplied.
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
            'action_buffer_size': str(buffer_size),
        }
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

    def remove_src_tunnel(self, region: str, agent: str, stunnel_id: str, plugin_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Tear down the source side of a tunnel."""
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
        """Remove both ends of a tunnel. Plugin ids are auto-resolved when omitted."""
        out: Dict[str, Any] = {'stunnel_id': stunnel_id, 'src_removal': None, 'dst_removal': None, 'fully_removed': False}
        out['src_removal'] = self.remove_src_tunnel(src_region, src_agent, stunnel_id, src_plugin_id)
        out['dst_removal'] = self.remove_dst_tunnel(dst_region, dst_agent, stunnel_id, dst_plugin_id)
        out['fully_removed'] = bool(out['src_removal'] and out['dst_removal'])
        return out
