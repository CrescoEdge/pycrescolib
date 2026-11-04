# Cresco Python Client (pycrescolib)

Python client library for the **[Cresco](https://github.com/CrescoEdge/agent)** edge-computing framework. It connects
to the [wsapi](https://github.com/CrescoEdge/wsapi) WebSocket plugin (`wss://host:8282`, the server certificate
verified, authenticated with a per-user credential or the `cresco_service_key`) to control agents, deploy plugins, run
pipelines, stream the data plane, and build stunnel tunnels.

Part of the Cresco framework — see the **[agent repository](https://github.com/CrescoEdge/agent)** for the full
architecture and the [Java client](https://github.com/CrescoEdge/clientlib) for the equivalent in Java.

> **Standardized clients.** The Python and Java clients are kept feature- and name-identical: the same
> submodules (`messaging`, `agents`, `admin`, `api`, `globalcontroller`, `stunnel`), the same method names (snake_case
> in both languages), the same behavior, and the same examples. Anything you can do in one, you can do in the
> other with the same call. This README is identical to the Java client's, except for the install and
> quick-start sections below.

**Install:** `pip install pycrescolib` (Python 3.8+; depends on `websockets`, `cryptography`, `backoff`).
From a source checkout use `pip install .`, and to build the distributions run `python -m build`.

## Quick start

```python
from pycrescolib.clientlib import clientlib

# host/ip of an agent running the wsapi plugin, its port, the wsapi service key, and the wsapi certificate's
# fingerprint (from ws.fingerprint in the wsapi plugin data directory, or the agent log), which turns on verification
client = clientlib("localhost", 8282, "your-service-key", fingerprint="sha384:AB:CD:...")

if client.connect():
    print(client.api.get_api_region_name(), client.api.get_api_agent_name())
    print(client.globalcontroller.get_agent_list())
    client.close()
```

Runnable, standardized examples (identical to the Java client's `example/standard/StandardExamples.java`)
live in [`examples/standard_examples.py`](examples/standard_examples.py): `example_connect`, `example_pipeline`,
`example_plugin_lifecycle`, `example_dataplane`, `example_logstreamer`, `example_admin`.

## Concepts

- **Connect once, use submodules.** A `clientlib` opens one authenticated control connection and exposes six
  submodule handles: `messaging`, `agents`, `admin`, `api`, `globalcontroller`, `stunnel`.
- **Resolve plugins by name, not by log-scraping.** `globalcontroller.find_plugin(region, agent, name)` returns the
  live `plugin_id` for a plugin loaded on an agent, so you never parse logs to address a plugin.
- **Streams are separate sockets.** `get_dataplane(...)` and `get_logstreamer(...)` open their own WebSocket
  connections, are tracked by name on the client, and auto-reconnect if the socket drops.
- **"Not found" vs "couldn't ask".** Inventory queries (`globalcontroller.list_plugins` / `find_plugin` /
  `get_agent_list` / `get_region_list` / `get_pipeline_list` / `get_pipeline_id_by_name`,
  `agents.list_plugin_agent` / `find_plugin`) return an empty list / `None` **only** when the fabric answered
  "none". When the query fails they raise: `CrescoQueryError` (from `pycrescolib.base_classes`; an error reply
  such as wsapi's 504, or a reply without the list) or `TimeoutError` / `ConnectionError` (no reply, e.g. right
  after a global restart). Since 1.3.2; earlier versions returned `[]` / `None` on failure, which made
  check-then-act code (`if not find_plugin(...): add`) start duplicate plugins. Code that only displays the
  result can catch the exception; code that acts on "absent" must not. A control socket the server closed (e.g.
  a global restart) raises `ConnectionError` and `connected()` turns False, so reconnect with `connect()`;
  earlier versions kept `connected()` True and answered every RPC with an empty reply.
- **RPC vs fire-and-forget.** Messaging calls take an `is_rpc` flag: when true the call blocks for the reply,
  when false it is sent without waiting.

## API reference

Signatures are shown language-neutrally; names and behavior are identical in both clients.

### Client — `clientlib` / `CrescoClient`

| Method | Description |
|---|---|
| `clientlib(host, port, service_key=None, verify_ssl=None, *, ca_file=None, fingerprint=None, check_hostname=True, user=None, password=None)` | Create the client for a wsapi endpoint (see [Security](#security-tls-trust-and-credentials)). |
| `connect(block_on_connect=True) -> bool` | Connect to the wsapi endpoint; block until connected when `block_on_connect`. |
| `connected() -> bool` | Return True if connected to the wsapi endpoint. |
| `close() -> bool` | Close the client connection and all managed streams. |
| `connection()` | Return the underlying websocket transport interface. |
| `get_dataplane(stream_name, callback=None)` | Get (and register) a dataplane for the given stream query. |
| `close_dataplane(stream_name) -> bool` | Close and deregister the named dataplane. |
| `get_active_dataplanes() -> list` | List names of currently registered dataplanes. |
| `get_logstreamer(name=None, callback=None)` | Get (and register) a logstreamer. |
| `close_logstreamer(name) -> bool` | Close and deregister the named logstreamer. |
| `get_active_logstreamers() -> list` | List names of currently registered logstreamers. |

Submodule handles: `messaging`, `agents`, `admin`, `api`, `globalcontroller`, `stunnel`.

### `api`

| Method | Description |
|---|---|
| `get_api_region_name()` | Region name of the agent hosting the wsapi plugin. |
| `get_api_agent_name()` | Agent name of the agent hosting the wsapi plugin. |
| `get_api_plugin_name()` | Plugin name of the wsapi plugin. |
| `get_global_region()` | Global controller region. |
| `get_global_agent()` | Global controller agent. |
| `get_global_info()` | Pair of (global_region, global_agent). |

### `admin`

| Method | Description |
|---|---|
| `stopcontroller(dst_region, dst_agent)` | Stop the agent's controller plugin. |
| `restartcontroller(dst_region, dst_agent)` | Restart the agent's controller plugin. |
| `restartframework(dst_region, dst_agent)` | Restart the underlying OSGi framework. |
| `killjvm(dst_region, dst_agent)` | Force-terminate the agent JVM. |

### `agents`

| Method | Description |
|---|---|
| `is_controller_active(dst_region, dst_agent)` | Whether the target controller is active. |
| `get_controller_status(dst_region, dst_agent)` | Controller status. |
| `add_plugin_agent(dst_region, dst_agent, configparams, edges=None)` | Add a plugin to an agent. |
| `remove_plugin_agent(dst_region, dst_agent, plugin_id)` | Remove a plugin from an agent. |
| `list_plugin_agent(dst_region, dst_agent)` | List plugins on an agent (asks the agent itself; raises if it cannot be read). |
| `find_plugin(dst_region, dst_agent, pluginname)` | Resolve a plugin's `plugin_id` by name from the agent's own list (or `None` if not loaded). |
| `status_plugin_agent(dst_region, dst_agent, plugin_id)` | Get plugin status. |
| `get_agent_info(dst_region, dst_agent)` | Get agent information. |
| `get_agent_log(dst_region, dst_agent)` | Get agent logs. |
| `repo_pull_plugin_agent(dst_region, dst_agent, jar_file_path)` | Pull a plugin jar to the agent repo. |
| `upload_plugin_agent(dst_region, dst_agent, jar_file_path)` | Upload a plugin jar to the agent. |
| `update_plugin_agent(dst_region, dst_agent, jar_file_path)` | Update a plugin on the agent. |
| `get_broadcast_discovery(dst_region, dst_agent)` | Get broadcast discovery from an agent. |
| `cepadd(input_stream, input_stream_desc, output_stream, output_stream_desc, query, dst_region, dst_agent)` | Add a complex-event-processing query. |

### `globalcontroller`

| Method | Description |
|---|---|
| `submit_pipeline(cadl, tenant_id='0')` | Submit a CADL pipeline. |
| `remove_pipeline(pipeline_id)` | Remove a pipeline. |
| `get_pipeline_list()` | List pipelines. |
| `get_pipeline_info(pipeline_id)` | Get pipeline information. |
| `get_pipeline_status(pipeline_id)` | Get pipeline status code. |
| `get_pipeline_id_by_name(pipeline_name)` | Look up a pipeline ID by name. |
| `get_pipeline_export(pipeline_id)` | Export a pipeline. |
| `get_pipeline_is_assignment_info(inode_id, resource_id)` | Get inode-to-resource assignment info. |
| `get_agent_list(dst_region=None)` | List agents (optionally in one region). |
| `get_agent_resources(dst_region, dst_agent)` | Get an agent's resource info. |
| `get_region_resources(dst_region)` | Get a region's resource info. |
| `get_region_list()` | List regions. |
| `get_plugin_repo_list()` | List plugins available in the repositories. |
| `get_repo_plugins()` | List plugins known to the repositories. |
| `list_plugins(dst_region, dst_agent)` | List the plugins loaded on an agent (via the global controller — reliable from anywhere in the mesh). |
| `find_plugin(dst_region, dst_agent, pluginname)` | Resolve the live `plugin_id` for a plugin loaded on an agent by its plugin name (or `None`). |
| `upload_plugin_global(jar_file_path)` | Upload a plugin jar to the global repo. |
| `get_metric_inventory(scope, dst_region, dst_agent, include_plugins, include_resource)` | Pull the fabric's unified metric inventory (controller + plugin metrics, optional resource summary). |
| `get_capability_inventory(scope, dst_region, dst_agent, include_plugins, include_osgi)` | Pull the fabric's self-describing capability catalog (LLM-facing tool descriptors). |

> The metric/capability inventories take `scope` = `'node'`, `'region'`, or `'global'`; pass
> `dst_region`+`dst_agent` to target one agent's controller. (In the Java client these two methods
> currently order the positional args as `dst_region, dst_agent, scope, …`.)

### `stunnel`

Build and manage secure TCP tunnels through the [io.cresco.stunnel](https://github.com/CrescoEdge/stunnel)
plugin: a listener on `src_port` at the source agent forwards to `dst_host:dst_port` reachable from the
destination agent, with tunnel data riding the Cresco data plane. Plugin ids are auto-resolved by name via
`find_plugin`, so callers never pass a raw `plugin_id`.

| Method | Description |
|---|---|
| `find_plugin(region, agent)` | Resolve the `io.cresco.stunnel` plugin_id loaded on an agent (or `None`). |
| `deploy_plugin(region, agent, jar_file_path=None)` | Ensure the stunnel plugin runs on an agent: no-op if loaded, else upload `jar_file_path` (`pluginupload`) or start the copy embedded in the agent (`stunnel.jar`) with `pluginadd`. "Not loaded" is confirmed with the agent itself (`pluginlist`) before adding, because the global's view can lag the agent briefly after a restart. Returns the plugin_id, or `None` if the add failed; **raises** (and adds nothing) when the inventory could not be read. |
| `create_tunnel(stunnel_id, src_region, src_agent, src_port, dst_region, dst_agent, dst_host, dst_port, buffer_size="8192", src_plugin_id=None, dst_plugin_id=None, watchdog_timeout=None, performance_report_rate=None)` | Create a tunnel; plugin ids auto-resolved; optional params are sent only when not `None`. Returns the parsed `stunnel_config`. |
| `remove_tunnel(stunnel_id, src_region, src_agent, dst_region, dst_agent, src_plugin_id=None, dst_plugin_id=None)` | Remove both ends of a tunnel; returns `{stunnel_id, src_removal, dst_removal, fully_removed}`. |
| `get_tunnel_list(region, agent)` | List tunnels on an agent. |
| `get_tunnel_status(region, agent, stunnel_id)` | Get a tunnel's status (`ACTIVE`/`RECOVERING`/`DOWN`/`UNKNOWN`). |
| `get_tunnel_config(region, agent, stunnel_id)` | Get a tunnel's config. |
| `tunnel_health_check(region, agent, stunnel_id)` | `True` if that agent's plugin holds a config for the tunnel (`tunnelhealthcheck`). |
| `get_metrics(region, agent)` | The plugin's live metrics (`getmetrics`) as a dict. |
| `set_net_tuning(region, agent, tuning)` | Plugin-wide network tuning (`nettuning`): `net_socket_buffer_bytes`, `net_read_chunk_bytes`, `net_write_high_water_bytes`, `net_fc_window_bytes`, `net_trace_sample_n`; applies to connections opened afterwards. |
| `remove_src_tunnel(region, agent, stunnel_id)` | Remove only the source end (the server cascades the matching dst removal). |
| `remove_dst_tunnel(region, agent, stunnel_id)` | Remove only the destination end. |

Every per-agent method also takes an optional trailing `plugin_id` to skip the lookup; when the lookup
itself fails the method raises (see "Not found vs couldn't ask" above) instead of reporting "no plugin". Method names and
arguments match the Java client's `crescoclient.core.Stunnel`.

### `messaging`

All take `(is_rpc, message_event_type, message_payload, ...)` and return the reply dict for RPC calls.

| Method | Routes to |
|---|---|
| `global_controller_msgevent(...)` | the global controller |
| `regional_controller_msgevent(...)` | the regional controller |
| `global_agent_msgevent(..., dst_region, dst_agent)` | an agent via the global controller |
| `regional_agent_msgevent(..., dst_agent)` | an agent in the local region |
| `agent_msgevent(...)` | the local agent |
| `global_plugin_msgevent(..., dst_region, dst_agent, dst_plugin)` | a plugin via the global controller |
| `regional_plugin_msgevent(..., dst_agent, dst_plugin)` | a plugin in the local region |
| `plugin_msgevent(..., dst_plugin)` | a local plugin |

### `filerepo`

| Method | Description |
|---|---|
| `stream_file(dst_region, dst_agent, dst_plugin, file_path, dest_path, byte_length, start_byte=0, buffer_size=None, timeout)` | Download a byte range of a file from a filerepo plugin over the dataplane (`streamfile`); written only when every chunk arrived and the SHA-384 in filerepo's terminal frame matches, else `StreamFileError` / `StreamFileException` and nothing is written. Needs `infra` or `admin` on that agent. |

### dataplane (from `get_dataplane`)

| Method | Description |
|---|---|
| `send(message)` | Send a text message. |
| `send_binary(data)` | Send a binary message. |
| `send_binary_file(file_path)` | Read and send a binary file. |
| `send_partial(data, complete)` | Send a payload as a fragmented message (flushed when `complete`). |
| `update_config(dst_region, dst_agent)` | Update the dataplane stream configuration. |
| `connect()` | Open the stream. |
| `connected()` | Whether the stream is connected. |
| `close()` | Close the stream. |
| `get_metrics()` | Client-side counters for this stream (messages/bytes sent + received, active). |

### logstreamer (from `get_logstreamer`)

| Method | Description |
|---|---|
| `send(message)` | Send a message over the log stream. |
| `update_config(dst_region, dst_agent)` | Point the log stream at an agent. |
| `update_config_class(dst_region, dst_agent, loglevel, baseclass)` | Set the log level for one base class. |
| `connect()` | Open the stream. |
| `connected()` | Whether the stream is connected. |
| `close()` | Close the stream. |

## Security: TLS trust and credentials

Every connection the client opens (the API socket, every dataplane and every log stream) uses the same trust setting
and the same credentials. With a trust setting, the wsapi server certificate is verified before anything is sent.

**Trusting the wsapi certificate.** wsapi makes its own certificate and publishes it in its plugin data directory on
the agent (`<agent data>/plugin-data/<wsapi plugin id>/`): `ws.fingerprint` holds its SHA-384 and SHA-256
fingerprints and `ws.crt.pem` the certificate; the agent log also shows the fingerprint at every start. Then either

```python
client = clientlib(host, 8282, key, fingerprint="sha384:AB:CD:...")   # pin it (SHA-384 or SHA-256, any case, colons optional)
client = clientlib(host, 8282, key, ca_file="/path/to/ws.crt.pem")    # or trust it (or a CA bundle) as a CA file
```

or set `CRESCO_TLS_FINGERPRINT` or `CRESCO_TLS_CA_FILE` in the environment and change no code. Several pins (a list or a
comma-separated string) allow a certificate rotation. With `ca_file` the host name is checked (wsapi's certificate
names `localhost`, the agent's host names and addresses and `wsapi_tls_san`); pass `check_hostname=False` to skip
that. `verify_ssl=True` with neither uses the system trust store (and `SSL_CERT_FILE`), which does not trust a
self-signed wsapi.

A server that does not match gets nothing: no service key, no password. `connect()` returns False, `client.last_error`
says why (`wsapi certificate mismatch for host:port: the pinned fingerprint ... does not match the certificate the
server presented (...)`), and so do `dataplane.last_error` / `logstreamer.last_error`. The typed errors are in
`pycrescolib.tls`: `CertificateMismatch`, `CertificateVerificationError`, `AuthenticationError` (HTTP 401, 403 or 429,
with `.status`), `TLSConfigError`.

`verify_ssl=False` turns verification off. The credentials then go to whoever answers, so every connection made that
way logs a WARNING. It cannot be combined with `ca_file` or `fingerprint`. (It no longer turns off HTTPS verification
for the whole Python process, as 1.3.2 and earlier did.)

A client that names no trust setting at all (no `verify_ssl`, `ca_file` or `fingerprint`, and no `CRESCO_TLS_*`
variable) is, for now, not verified, as in 1.3.2 (`pycrescolib.tls.VERIFY_BY_DEFAULT` is False). Set a trust setting
now: verification will become the default.

**Credentials.** A per-user credential (created on the agent with wsapi's `CredentialTool`) or the legacy service key:

```python
client = clientlib(host, 8282, user="alice", password=os.environ["CRESCO_PASSWORD"], fingerprint=fp)
client = clientlib(host, 8282, "service-key", fingerprint=fp)
```

The user name and password go as HTTP Basic inside TLS. wsapi answers 401 for a bad credential, 403 for a user of
another tenant, and 429 after repeated failures from one address.

## Dataplane messages and verified file downloads

- A dataplane `MapMessage` (for example the executor's `execution_log` with a process's exit code, and its
  `delete_exchange`) arrives as a text message holding the JSON object of its entries.
- No dataplane subscription receives a process's stdin (wsapi narrows every subscription), so a client cannot read what
  others type into a runner; writing stdin is unchanged (open the stream with `input_id=<stdin_type>`).
- `filerepo.stream_file` downloads a file from a filerepo plugin over the dataplane and verifies it: filerepo ends every
  transfer with a terminal frame carrying its status and the SHA-384 of the bytes it sent (through wsapi, a JSON text
  frame `{"transfer_id", "transfer_end": "true", "transfer_status", "total_bytes", "sha384", ...}`). The chunks are
  reassembled in order into a private staging file next to the destination, which is moved into place only when every
  chunk arrived, the byte count is right and the SHA-384 matches.

```python
r = client.filerepo.stream_file("global-region", "agent-a", repo_plugin_id, "/data/repo/model.bin",
                                "/tmp/model.bin", byte_length=size)      # size from the repository's file list
print(r["sha384"])
```

## Testing & cross-language parity

Both clients ship a self-contained test suite (no live mesh needed) that asserts they emit
**identical wire messages for identical API calls** — the Python and Java suites assert the same
generated golden corpus, so a green run on both proves the clients produce the same results.

- **Python:** `pip install -e .[test] && pytest`
- **Java:** `mvn test`

See the [test-suite README](tests/README.md) for coverage, the canonical wire contract, and how to
regenerate the golden corpus after adding or changing a method.

## License

See [LICENSE.txt](LICENSE.txt).
