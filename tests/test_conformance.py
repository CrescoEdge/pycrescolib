"""
Conformance / parity tests for the Python client.

Each CASE is invoked against a capturing mock transport; the normalized outgoing message must
equal the shared golden corpus. The Java suite asserts the *same* corpus, so a green run on
both sides means the two clients emit identical wire messages for identical calls.
"""
import json
import os

import pytest

from tests.conformance_util import CASES, invoke

_GOLDEN_PATH = os.path.join(os.path.dirname(__file__), 'conformance', 'golden_messages.json')
with open(_GOLDEN_PATH) as _f:
    GOLDEN = {c['name']: c for c in json.load(_f)}


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_wire_message_matches_golden(case):
    assert case['name'] in GOLDEN, f"{case['name']} missing from golden corpus"
    expected = GOLDEN[case['name']]
    actual = invoke(case)
    assert actual['message_info'] == expected['message_info'], (
        f"{case['name']} message_info mismatch\n expected {expected['message_info']}\n actual   {actual['message_info']}")
    assert actual['message_payload'] == expected['message_payload'], (
        f"{case['name']} message_payload mismatch\n expected {expected['message_payload']}\n actual   {actual['message_payload']}")


def test_golden_and_cases_are_in_sync():
    """The golden corpus and the CASES list must cover exactly the same calls (no silent gaps)."""
    assert set(GOLDEN) == {c['name'] for c in CASES}


def test_is_rpc_is_canonical_string():
    """Every message must carry is_rpc as the canonical string 'true'/'false' (matches Java + server)."""
    for case in CASES:
        info = invoke(case)['message_info']
        assert info['is_rpc'] in ('true', 'false'), f"{case['name']} is_rpc={info['is_rpc']!r} not canonical"
