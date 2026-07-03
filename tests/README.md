# Cresco Python client — test suite

This suite is **self-contained** (no live Cresco mesh required) and **cross-language**: it proves
that the Python client and the [Java client](https://github.com/CrescoEdge/clientlib) emit
**identical wire messages for identical API calls**.

## Why this shape

Both clients are thin wrappers that build a JSON envelope — `{message_info, message_payload}` —
and hand it to the WebSocket transport. The deterministic, testable contract is therefore: *for a
given API call, what exact message goes on the wire?* A capturing mock transport lets us assert
that without a running agent.

Both the Python and Java suites assert the **same golden corpus**
(`conformance/golden_messages.json`), which is generated from the Python client and copied verbatim
into the Java repo. If both suites are green, both clients produce the same wire output.

## Layout

- `conformance_util.py` — the mock transport (captures the outgoing JSON), the canonical `CASES`
  list (every wire-producing call), and the normalizer.
- `gen_golden.py` — regenerates `conformance/golden_messages.json` from this client.
- `conformance/golden_messages.json` — the shared golden corpus (source of truth).
- `test_conformance.py` — replays `CASES`, asserts each normalized message equals the golden; also
  guards that `is_rpc` is canonical and that the golden and `CASES` cover exactly the same calls.
- `test_reply_parsing.py` — decode-path tests (canned reply → correctly-decoded return value).
- `test_local_methods.py` — public methods that return client-side state (e.g. `dataplane.get_metrics`).
- `fixtures/example-plugin.jar` — a byte-identical copy lives in the Java repo; used by the
  plugin-jar methods so `get_jar_info` → `{pluginname, version, md5}` and the base64 `jardata` match.

## Coverage

**44 wire-producing methods** — every `messaging` routing variant (8), `admin` (4),
`api.get_global_info`, all of `agents` (13, including the plugin-jar methods), and all of
`globalcontroller` (17, including `get_metric_inventory` / `get_capability_inventory` and the
plugin-jar methods) — plus reply-parsing and local-method tests.

## Normalization (content-based, not byte-based)

- gzip+base64 fields (`configparams`, `cepparams`, `action_gpipeline`) are decompressed and
  JSON-parsed before comparison — Java's `Deflater` and Python's `gzip` produce different bytes for
  the same content, and the *content* is what the server decodes.
- `jardata` is plain base64 on both sides, so it is byte-identical for the same fixture jar.
- The fixture jar's machine-specific absolute path is replaced with the token `<JAR_PATH>`
  (`update_plugin_agent` embeds the raw path in its payload).
- Comparison is on parsed objects, so JSON key ordering is irrelevant.

## Run

```bash
pip install -e .[test]   # or: pip install pytest
pytest                   # from the repo root
```

## Regenerate the golden (after adding or changing a method)

1. Add a case to `tests/conformance_util.py` `CASES`.
2. Add the matching invocation to the Java `ConformanceTest.invocations()`.
3. `python -m tests.gen_golden`
4. Copy `tests/conformance/golden_messages.json` →
   `clientlib/src/test/resources/conformance/golden_messages.json` (verbatim).
5. Run both suites.

The suites fail if the golden and the `CASES`/invocations cover different calls — **no silent gaps**.

## Canonical wire contract (locked by these tests)

- `is_rpc` is the string `"true"`/`"false"` in `message_info` (the wsapi server reads `message_info`
  as a string map).
- `cepadd`'s compressed params go under the key **`cepparams`** (the server reads
  `getCompressedParam("cepparams")`).
- `pluginupload` routes to the **target agent** (`global_agent_msgevent`), not the global controller.

## Scope notes (no silent gaps)

- Local accessors that emit no message (`api.get_api_region_name`/`get_api_agent_name`/
  `get_api_plugin_name` read the transport identity; `dataplane.get_metrics` returns counters) are
  not in the wire corpus; `get_metrics` is covered in `test_local_methods.py`.
- The Python **async** `messaging` methods (the base class, not `messaging_sync`) are advanced
  extras, not the standardized surface, and are not asserted for wire parity.

## Bugs this suite caught (and fixed)

- **`cepadd`** (Java) sent params under `configparams`; the server reads `cepparams`, so `cepadd`
  silently delivered `null`.
- **`upload_plugin_agent`** (Java) routed to the global controller, ignoring the target agent.
