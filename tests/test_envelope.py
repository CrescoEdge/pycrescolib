"""
Envelope frames (wsapi round 2): a dataplane opened with envelope=True receives every message with its verified writer,
so a client can tell a process's real execution_log (a map written by the executor) from a user's look-alike text.
"""
import json
import struct
import time

import pytest

from pycrescolib.clientlib import clientlib
from pycrescolib.dataplane import Envelope, parse_envelope_bytes, parse_envelope_text, with_envelope

from tests.tls_util import WssServer, make_cert


@pytest.fixture(scope="module")
def server_cert():
    return make_cert()


@pytest.fixture(autouse=True)
def no_env_trust(monkeypatch):
    monkeypatch.delenv("CRESCO_TLS_FINGERPRINT", raising=False)
    monkeypatch.delenv("CRESCO_TLS_CA_FILE", raising=False)


def bytes_frame(header, payload):
    h = json.dumps(header).encode("utf-8")
    return struct.pack(">I", len(h)) + h + payload


def test_text_map_and_terminal_envelopes_name_their_writer():
    forged = parse_envelope_text(json.dumps({"kind": "text", "writer": "api:tenant-a/bob", "writer_roles": "user",
                                             "writer_tenant": "tenant-a", "properties": {"stream_name": "job-1"},
                                             "text": '{"cmd":"execution_log","log":"Exit Code: 0"}'}))
    assert forged.kind == "text" and forged.from_api_user and forged.writer_tenant == "tenant-a"
    assert forged.properties["stream_name"] == "job-1" and forged.map is None
    real = parse_envelope_text(json.dumps({"kind": "map", "writer": "plugin:region-1/agent-1/system-executor",
                                           "writer_roles": "infra", "writer_tenant": "tenant-a", "properties": {},
                                           "map": {"cmd": "execution_log", "log": "Exit Code: 0"}}))
    assert real.kind == "map" and not real.from_api_user and real.map["cmd"] == "execution_log"
    end = parse_envelope_text(json.dumps({"kind": "transfer_end", "writer": "plugin:r/a/system-filerepo",
                                          "properties": {}, "map": {"transfer_status": "10", "sha384": "ab"}}))
    assert end.kind == "transfer_end" and end.map["sha384"] == "ab"


def test_anything_that_is_not_an_envelope_is_raw_and_claims_no_writer():
    for frame in ('{"cmd":"execution_log"}', "plain text", '{"kind":"text"', '{"kind":"other","writer":"x"}'):
        e = parse_envelope_text(frame)
        assert e.kind == "raw" and e.writer is None and e.text == frame
    for frame in (b"", b"\x00\x00\x00\xff{}", b"\x00\x00\x00\x02{}abc", bytes_frame({"kind": "text"}, b"x")):
        e = parse_envelope_bytes(frame)
        assert e.kind == "raw" and e.writer is None and e.data == frame


def test_a_bytes_envelope_keeps_the_payload_as_published():
    e = parse_envelope_bytes(bytes_frame({"kind": "bytes", "writer": "plugin:r/a/system-filerepo", "properties":
                                          {"transfer_id": "t1", "seq_num": "3"}}, b"\x00\x01payload"))
    assert e.kind == "bytes" and e.writer == "plugin:r/a/system-filerepo" and e.data == b"\x00\x01payload"
    assert e.properties["seq_num"] == "3"


def test_envelope_is_asked_for_in_a_json_stream_config_only():
    cfg = json.loads(with_envelope(json.dumps({"ident_key": "stream_name", "ident_id": "job-1"})))
    assert cfg == {"ident_key": "stream_name", "ident_id": "job-1", "envelope": "true"}
    with pytest.raises(ValueError):
        with_envelope("stream_name='job-1'")


def test_a_dataplane_with_envelope_hands_callbacks_envelopes(server_cert):
    got_text, got_bytes = [], []
    with WssServer(server_cert) as srv:                       # the test server echoes dataplane frames
        c = clientlib("127.0.0.1", srv.port, "sk-test", fingerprint=server_cert.fingerprint())
        dp = c.get_dataplane(json.dumps({"ident_key": "stream_name", "ident_id": "job-1"}), callback=got_text.append,
                             binary_callback=got_bytes.append, envelope=True)
        assert dp.envelope
        assert dp.connect(), dp.last_error
        dp.send(json.dumps({"kind": "map", "writer": "plugin:r/a/system-executor", "properties": {},
                            "map": {"cmd": "execution_log"}}))
        dp.send("not an envelope")
        dp.send_binary(bytes_frame({"kind": "bytes", "writer": "api:t/bob", "properties": {}}, b"abc"))
        end = time.time() + 10
        while time.time() < end and (len(got_text) < 2 or not got_bytes):
            time.sleep(0.05)
        c.close()
    assert all(isinstance(e, Envelope) for e in got_text + got_bytes)
    assert got_text[0].kind == "map" and got_text[0].writer == "plugin:r/a/system-executor"
    assert got_text[1].kind == "raw" and got_text[1].writer is None
    assert got_bytes[0].data == b"abc" and got_bytes[0].from_api_user
