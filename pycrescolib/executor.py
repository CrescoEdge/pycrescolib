"""Client-side helper for the io.cresco.executor plugin: run a command on an agent and drive its stdin.

A runner is registered with config_process and started with run_process; its stdout and stderr stream over the
dataplane under its stream_name (type output / error), and its exit arrives there as an execution_log event.

Stdin is never the dataplane. The executor keeps a process's stdin open only when config_process asked for it
(stdin=True, or an -interactive- command), and takes input only from write_stdin, a MsgEvent action it accepts from
the caller that started the runner, an admin or infra. Each write carries at most MAX_STDIN_WRITE bytes; write_stdin
splits larger input into several writes, in order. wsapi refuses a dataplane stream that would write stdin
(input_id input / input-*), and so does this client's dataplane.

Mirrors the Java client's crescoclient.core.Executor method for method. Plugin ids are resolved by name through
globalcontroller.find_plugin when not given.
"""
import base64
import logging
from typing import Any, Dict, Optional, Union

from .base_classes import CrescoMessageBase

logger = logging.getLogger(__name__)

EXECUTOR_PLUGIN_NAME = "io.cresco.executor"
# the executor's bound on one write_stdin (Runner.MAX_STDIN_WRITE)
MAX_STDIN_WRITE = 64 * 1024
# write_stdin replies: status "10" written, "9" refused (see refusal), "8" bad params, "7" not written
STATUS_WRITTEN = "10"


class StdinWriteError(Exception):
    """write_stdin was not accepted. ``refusal`` is the executor's reason code when it refused: ``not-owner`` (only
    the caller that started the runner, an admin or infra may write), ``no-stdin`` (config_process without stdin=True)
    or ``not-running``; ``written`` is how many bytes earlier writes of the same call delivered."""

    def __init__(self, stream_name: str, status: Optional[str], refusal: Optional[str], status_desc: Optional[str],
                 written: int = 0):
        reason = refusal or status_desc or ("no reply" if status is None else f"status {status}")
        super().__init__(f"write_stdin to {stream_name!r} failed: {reason}"
                         + (f" ({status_desc})" if refusal and status_desc else "")
                         + (f"; {written} byte(s) were written before" if written else ""))
        self.stream_name = stream_name
        self.status = status
        self.refusal = refusal
        self.status_desc = status_desc
        self.written = written


def _true(v: Any) -> bool:
    return str(v).lower() == "true"


class executor(CrescoMessageBase):
    """Run OS processes on an agent (io.cresco.executor) and write their stdin."""

    def __init__(self, messaging, globalcontroller):
        super().__init__(messaging)
        self._gc = globalcontroller

    def find_plugin(self, region: str, agent: str) -> Optional[str]:
        """The executor plugin_id on an agent, or None when none is loaded."""
        return self._gc.find_plugin(region, agent, EXECUTOR_PLUGIN_NAME)

    def _plugin(self, region: str, agent: str, plugin_id: Optional[str]) -> str:
        pid = plugin_id or self.find_plugin(region, agent)
        if not pid:
            raise LookupError(f"no {EXECUTOR_PLUGIN_NAME} plugin on {region}/{agent}")
        return pid

    def _send(self, event_type: str, payload: Dict[str, Any], region: str, agent: str, plugin_id: Optional[str],
              timeout: float) -> Dict[str, Any]:
        reply = self.messaging.global_plugin_msgevent(True, event_type, payload, region, agent,
                                                      self._plugin(region, agent, plugin_id), timeout=timeout)
        return reply if isinstance(reply, dict) else {}

    def config_process(self, region: str, agent: str, stream_name: str, command: str, stdin: bool = False,
                       metrics: bool = False, plugin_id: Optional[str] = None, timeout: float = 8.0) -> Dict[str, Any]:
        """Register a runner (infra / admin). Returns {'config_status': bool, 'stdin': bool, 'error_msg': str|None}:
        'stdin' says whether the runner takes write_stdin (stdin=True, or an -interactive- command)."""
        payload = {'action': 'config_process', 'stream_name': stream_name, 'command': command,
                   'stdin': str(bool(stdin)).lower(), 'metrics': str(bool(metrics)).lower()}
        r = self._send('CONFIG', payload, region, agent, plugin_id, timeout)
        return {'config_status': _true(r.get('config_status')), 'stdin': _true(r.get('stdin')),
                'error_msg': r.get('error_msg')}

    def run_process(self, region: str, agent: str, stream_name: str, plugin_id: Optional[str] = None,
                    timeout: float = 8.0) -> bool:
        """Start a configured runner (infra / admin). The caller that starts it may write its stdin."""
        r = self._send('EXEC', {'action': 'run_process', 'stream_name': stream_name}, region, agent, plugin_id, timeout)
        return _true(r.get('status'))

    def status_process(self, region: str, agent: str, stream_name: str, plugin_id: Optional[str] = None,
                       timeout: float = 8.0) -> bool:
        """True while the runner's process is running."""
        r = self._send('CONFIG', {'action': 'status_process', 'stream_name': stream_name}, region, agent, plugin_id, timeout)
        return _true(r.get('run_status'))

    def end_process(self, region: str, agent: str, stream_name: str, plugin_id: Optional[str] = None,
                    timeout: float = 8.0) -> bool:
        """Kill the runner's process (its whole tree) and free the runner (infra / admin)."""
        r = self._send('CONFIG', {'action': 'end_process', 'stream_name': stream_name}, region, agent, plugin_id, timeout)
        return _true(r.get('end_status'))

    def write_stdin(self, region: str, agent: str, stream_name: str, data: Union[str, bytes, None] = None,
                    newline: bool = True, close: bool = False, plugin_id: Optional[str] = None,
                    timeout: float = 8.0) -> int:
        """Write to a running process's stdin through the executor's write_stdin action.

        ``data`` is text (UTF-8, followed by a newline unless ``newline=False``) or bytes (written as they are);
        ``close=True`` closes stdin after the data (end of input; ``data=None`` just closes it). Input over
        MAX_STDIN_WRITE bytes goes in several writes, in order. Returns the number of bytes written.

        Raises:
            StdinWriteError: the executor refused or failed a write (``refusal``: not-owner, no-stdin, not-running);
                ``written`` says how much of the input earlier writes delivered.
            LookupError: no executor plugin on the agent (when ``plugin_id`` is not given).
            TimeoutError, ConnectionError: from the transport.
        """
        if isinstance(data, str):
            raw = (data + "\n" if newline else data).encode("utf-8")
        elif data is None:
            raw = b""
        elif isinstance(data, (bytes, bytearray, memoryview)):
            raw = bytes(data)
        else:
            raise TypeError("data must be str, bytes or None")
        if not raw and not close:
            return 0
        pid = self._plugin(region, agent, plugin_id)
        chunks = [raw[i:i + MAX_STDIN_WRITE] for i in range(0, len(raw), MAX_STDIN_WRITE)] or [b""]
        written = 0
        for n, chunk in enumerate(chunks):
            last = n == len(chunks) - 1
            payload: Dict[str, Any] = {'action': 'write_stdin', 'stream_name': stream_name}
            if chunk:
                payload['data_b64'] = base64.b64encode(chunk).decode("ascii")
            if close and last:
                payload['close_stdin'] = 'true'
            reply = self.messaging.global_plugin_msgevent(True, 'EXEC', payload, region, agent, pid, timeout=timeout)
            reply = reply if isinstance(reply, dict) else {}
            if reply.get('status') != STATUS_WRITTEN:
                # the executor answers status/refusal; the agent's action authorization, before it, status_code 403
                raise StdinWriteError(stream_name, reply.get('status') or reply.get('status_code'), reply.get('refusal'),
                                      reply.get('status_desc'), written)
            written += len(chunk)
        logger.debug("write_stdin: %d byte(s) to %s", written, stream_name)
        return written

    def close_stdin(self, region: str, agent: str, stream_name: str, plugin_id: Optional[str] = None,
                    timeout: float = 8.0) -> None:
        """Close a running process's stdin (end of input)."""
        self.write_stdin(region, agent, stream_name, None, close=True, plugin_id=plugin_id, timeout=timeout)
