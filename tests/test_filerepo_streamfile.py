"""filerepo.stream_file: reassembles streamfile chunks and commits the file only when the terminal frame's SHA-384,
byte count and chunk count all match (the wsapi framing: binary [transfer_id][6-digit seq][payload] chunks, then a JSON
text terminal frame)."""
import hashlib
import json
import os
import threading

import pytest

from pycrescolib.filerepo import StreamFileError, filerepo


class FakeDataplane:
    def __init__(self, callback, binary_callback):
        self.text, self.binary = callback, binary_callback

    def connect(self):
        return True


class FakeMessaging:
    def __init__(self, client):
        self.client, self.calls = client, []

    def global_plugin_msgevent(self, is_rpc, etype, payload, region, agent, plugin, timeout=8.0):
        self.calls.append(dict(payload))
        if payload["action"] == "streamfilecancel":
            return {}
        reply = self.client.reply
        if reply.get("status") == "10":
            threading.Thread(target=self.client.play, args=(payload,), daemon=True).start()
        return reply


class FakeClient:
    def __init__(self, data, chunk=4, mutate=None, reply=None, terminal_extra=None, no_terminal=False):
        self.data, self.chunk, self.mutate = data, chunk, mutate
        self.reply = reply or {"status": "10", "status_desc": "transfer accepted"}
        self.terminal_extra = terminal_extra or {}
        self.no_terminal = no_terminal
        self.messaging = FakeMessaging(self)
        self.closed = []
        self.dp = None

    def get_dataplane(self, name, callback=None, binary_callback=None):
        self.dp = FakeDataplane(callback, binary_callback)
        return self.dp

    def close_dataplane(self, name):
        self.closed.append(name)

    def play(self, req):
        tid = req["transfer_id"].encode()
        start, length = int(req["start_byte"]), int(req["byte_length"])
        body = self.data[start:start + length]
        chunks = [body[i:i + self.chunk] for i in range(0, len(body), self.chunk)]
        frames = [tid + f"{n:06d}".encode() + c for n, c in enumerate(chunks)]
        if self.mutate:
            frames = self.mutate(frames)
        self.dp.binary(b"other-transfer000000junk")          # another transfer's chunk on the stream: ignored
        for f in frames:
            self.dp.binary(f)
        if self.no_terminal:
            return
        term = {"transfer_id": req["transfer_id"], "transfer_end": "true", "transfer_status": "10",
                "transfer_desc": "complete", "total_bytes": str(len(body)), "seq_num": str(len(chunks)),
                "sha384": hashlib.sha384(body).hexdigest()}
        term.update(self.terminal_extra)
        self.dp.text(json.dumps(term))


DATA = os.urandom(4099)


def test_a_verified_transfer_is_written(tmp_path):
    c = FakeClient(DATA, chunk=1000)
    out = tmp_path / "f.bin"
    r = filerepo(c).stream_file("r", "a", "p", "/repo/f.bin", str(out), byte_length=len(DATA))
    assert out.read_bytes() == DATA
    assert r["sha384"] == hashlib.sha384(DATA).hexdigest() and r["total_bytes"] == len(DATA)
    req = c.messaging.calls[0]
    assert req["action"] == "streamfile" and req["ident_key"] == "stream_name" and req["transfer_id"] == r["transfer_id"]
    assert c.closed, "the transfer's dataplane is closed"
    assert os.listdir(tmp_path) == ["f.bin"], "no staging file left"


def test_a_byte_range(tmp_path):
    c = FakeClient(DATA, chunk=7)
    out = tmp_path / "part"
    filerepo(c).stream_file("r", "a", "p", "/f", str(out), byte_length=100, start_byte=50)
    assert out.read_bytes() == DATA[50:150]


@pytest.mark.parametrize("case", ["bad-hash", "short", "missing-chunk", "duplicate", "status-9", "no-hash"])
def test_an_unverifiable_transfer_writes_nothing(tmp_path, case):
    kw = {
        "bad-hash": dict(terminal_extra={"sha384": "0" * 96}),
        "short": dict(terminal_extra={"total_bytes": "5"}),
        "missing-chunk": dict(mutate=lambda f: f[:2] + f[3:]),
        "duplicate": dict(mutate=lambda f: f + f[-1:]),
        "status-9": dict(terminal_extra={"transfer_status": "9", "transfer_desc": "cancelled"}),
        "no-hash": dict(terminal_extra={"sha384": ""}),
    }[case]
    c = FakeClient(DATA, chunk=500, **kw)
    out = tmp_path / "f.bin"
    with pytest.raises(StreamFileError):
        filerepo(c).stream_file("r", "a", "p", "/f", str(out), byte_length=len(DATA), timeout=10)
    assert os.listdir(tmp_path) == [], f"{case}: nothing may be written"


def test_a_refused_request_raises_with_its_status(tmp_path):
    c = FakeClient(DATA, reply={"status": "8", "status_desc": "invalid byte range"})
    with pytest.raises(StreamFileError) as e:
        filerepo(c).stream_file("r", "a", "p", "/f", str(tmp_path / "x"), byte_length=10)
    assert e.value.status == "8" and "invalid byte range" in str(e.value)
    assert os.listdir(tmp_path) == []


def test_no_terminal_frame_times_out_and_cancels(tmp_path):
    c = FakeClient(DATA, no_terminal=True)
    with pytest.raises(StreamFileError):
        filerepo(c).stream_file("r", "a", "p", "/f", str(tmp_path / "x"), byte_length=len(DATA), timeout=1.0)
    assert c.messaging.calls[-1]["action"] == "streamfilecancel"
    assert os.listdir(tmp_path) == []
