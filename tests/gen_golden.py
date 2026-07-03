"""
Generate the shared golden-message corpus from the (canonicalized) Python client.

The golden corpus is the single source of truth for the outgoing wire message of every
API call. Both the Python and Java conformance suites assert their normalized output equals
this corpus -- so if both pass, both clients emit identical messages.

Run:  python -m tests.gen_golden      (from the pycrescolib repo root)
Writes tests/conformance/golden_messages.json. Copy that file verbatim into the Java repo at
src/test/resources/conformance/golden_messages.json so both suites read the same corpus.
"""
import json
import os

from tests.conformance_util import CASES, invoke


def main():
    golden = []
    for case in CASES:
        msg = invoke(case)
        golden.append({
            'name': case['name'],
            'target': case['target'],
            'method': case['method'],
            'args': case['args'],
            'message_info': msg['message_info'],
            'message_payload': msg['message_payload'],
        })

    out_dir = os.path.join(os.path.dirname(__file__), 'conformance')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'golden_messages.json')
    with open(out_path, 'w') as f:
        json.dump(golden, f, indent=2, sort_keys=True)
        f.write('\n')
    print(f"Wrote {len(golden)} golden cases to {out_path}")


if __name__ == '__main__':
    main()
