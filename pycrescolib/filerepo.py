"""
Download a file from a filerepo plugin over the dataplane (``streamfile``), verified.

filerepo sends a byte range of a cataloged file as dataplane chunks, then a terminal frame with the transfer's status
and the SHA-384 of the bytes it sent. Through wsapi a chunk is a binary frame ``[transfer_id][seq_num, 6 digits]
[payload]`` and the terminal frame is a JSON text frame ``{"transfer_id", "transfer_end": "true", "transfer_status",
"total_bytes", "sha384", ...}``. :meth:`filerepo.stream_file` reassembles the chunks in order into a private staging
file next to the destination and renames it into place only when every chunk arrived, the byte count is right and the
SHA-384 matches; otherwise it raises :class:`StreamFileError` and leaves no file behind.

``streamfile`` needs the ``infra`` or ``admin`` role on the filerepo agent (a wsapi admin credential or the service key).
"""
import hmac
import hashlib
import json
import logging
import os
import secrets
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class StreamFileError(Exception):
    """A streamfile transfer that failed or could not be verified. ``status`` is filerepo's, when it gave one."""

    def __init__(self, message: str, status: Optional[str] = None):
        super().__init__(message)
        self.status = status


class _Receiver:
    """Reassembles one transfer's chunks, in order, into a staging file; remembers its terminal frame."""

    MAX_OUT_OF_ORDER = 64

    def __init__(self, transfer_id: str, staging_path: str):
        self.tid = transfer_id
        self.prefix = transfer_id.encode("ascii")
        self.fd = os.open(staging_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.sha = hashlib.sha384()
        self.written = 0
        self.next_seq = 0
        self.pending = {}
        self.terminal = None
        self.error = None
        self.done = threading.Event()
        self.lock = threading.Lock()

    def on_binary(self, frame: bytes) -> None:
        if not frame.startswith(self.prefix):
            return                                            # another transfer's chunk on this stream
        head = frame[len(self.prefix):len(self.prefix) + 6]
        try:
            seq = int(head)
        except ValueError:
            return
        payload = frame[len(self.prefix) + 6:]
        with self.lock:
            if self.error or self.terminal:
                return
            if seq < self.next_seq or seq in self.pending:
                self.error = f"chunk {seq} arrived twice"
                self.done.set()
                return
            self.pending[seq] = payload
            if len(self.pending) > self.MAX_OUT_OF_ORDER:
                self.error = f"chunk {self.next_seq} never arrived ({len(self.pending)} later chunks waiting)"
                self.done.set()
                return
            while self.next_seq in self.pending:
                data = self.pending.pop(self.next_seq)
                os.write(self.fd, data)
                self.sha.update(data)
                self.written += len(data)
                self.next_seq += 1

    def on_text(self, text) -> None:
        try:
            msg = json.loads(text)
        except Exception:
            return
        if not isinstance(msg, dict) or msg.get("transfer_end") != "true" or msg.get("transfer_id") != self.tid:
            return
        with self.lock:
            self.terminal = msg
        self.done.set()

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


class filerepo:
    """File transfers from a filerepo plugin. A submodule of :class:`pycrescolib.clientlib.clientlib`."""

    def __init__(self, client):
        self._client = client

    def stream_file(self, dst_region: str, dst_agent: str, dst_plugin: str, file_path: str, dest_path: str,
                    byte_length: int, start_byte: int = 0, buffer_size: Optional[int] = None,
                    timeout: float = 600.0) -> dict:
        """Download ``byte_length`` bytes of ``file_path`` (from ``start_byte``) into ``dest_path``, verified.

        Args:
            dst_region, dst_agent, dst_plugin: the filerepo plugin
            file_path: the file's path on that agent (as its repository lists it)
            dest_path: where to write it; written only after the transfer is verified
            byte_length: how many bytes (the file's size for a whole file)
            start_byte: where to start
            buffer_size: chunk size (filerepo caps it at 768 KB)
            timeout: seconds to wait for the whole transfer

        Returns:
            ``{"transfer_id", "total_bytes", "sha384"}`` of the verified transfer.

        Raises:
            StreamFileError: refused, cancelled, failed, incomplete, or the SHA-384 did not match; nothing is written.
        """
        tid = "pc-" + secrets.token_hex(12)
        ident = "sf-" + secrets.token_hex(16)
        dest = os.path.abspath(dest_path)
        staging = os.path.join(os.path.dirname(dest), f".{os.path.basename(dest)}.{tid}.part")
        rx = _Receiver(tid, staging)
        selector = f"stream_name='{ident}'"
        committed = False
        dp = None
        try:
            dp = self._client.get_dataplane(selector, callback=rx.on_text, binary_callback=rx.on_binary)
            try:
                active = dp.connect()
            except Exception as e:
                raise StreamFileError(f"the dataplane stream for the transfer was refused: {e}") from e
            if not active:
                raise StreamFileError(f"the dataplane stream for the transfer did not open: {getattr(dp, 'last_error', None)}")
            payload = {"action": "streamfile", "file_path": file_path, "start_byte": str(int(start_byte)),
                       "byte_length": str(int(byte_length)), "ident_key": "stream_name", "ident_id": ident,
                       "transfer_id": tid}
            if buffer_size:
                payload["buffer_size"] = str(int(buffer_size))
            reply = self._client.messaging.global_plugin_msgevent(True, "EXEC", payload, dst_region, dst_agent, dst_plugin)
            status = str((reply or {}).get("status", ""))
            if status != "10":
                raise StreamFileError(f"streamfile refused ({status or 'no reply'}): "
                                      f"{(reply or {}).get('status_desc', '')}", status or None)
            if not rx.done.wait(timeout):
                self._cancel(dst_region, dst_agent, dst_plugin, tid)
                raise StreamFileError(f"streamfile {tid} did not finish within {timeout} s (cancelled)")
            with rx.lock:
                terminal, error = rx.terminal, rx.error
                written, next_seq, digest = rx.written, rx.next_seq, rx.sha.hexdigest()
            if error:
                self._cancel(dst_region, dst_agent, dst_plugin, tid)
                raise StreamFileError(f"streamfile {tid}: {error}")
            t_status = terminal.get("transfer_status")
            if t_status != "10":
                raise StreamFileError(f"streamfile {tid} ended with status {t_status}: {terminal.get('transfer_desc', '')}",
                                      t_status)
            want_chunks = terminal.get("seq_num")
            if want_chunks is not None and str(next_seq) != str(want_chunks):
                raise StreamFileError(f"streamfile {tid}: {next_seq} of {want_chunks} chunks arrived")
            total = int(terminal.get("total_bytes", "-1"))
            if total != written or written != int(byte_length):
                raise StreamFileError(f"streamfile {tid}: {written} bytes arrived, the sender sent {total}, "
                                      f"{int(byte_length)} were asked for")
            want = str(terminal.get("sha384", "")).lower()
            if not want or not hmac.compare_digest(want, digest):
                raise StreamFileError(f"streamfile {tid}: the SHA-384 of the received bytes ({digest}) is not the "
                                      f"sender's ({want or 'none'})")
            rx.close()
            os.replace(staging, dest)
            committed = True
            return {"transfer_id": tid, "total_bytes": written, "sha384": digest}
        finally:
            rx.close()
            if not committed:
                try:
                    os.unlink(staging)
                except OSError:
                    pass
            if dp is not None:
                try:
                    self._client.close_dataplane(selector)
                except Exception:
                    pass

    def _cancel(self, region, agent, plugin, tid):
        try:
            self._client.messaging.global_plugin_msgevent(False, "EXEC", {"action": "streamfilecancel", "transfer_id": tid},
                                                          region, agent, plugin)
        except Exception as e:
            logger.debug(f"streamfilecancel {tid} not sent: {e}")
