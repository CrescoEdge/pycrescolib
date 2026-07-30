# Cresco Python Client (pycrescolib)

Python client library for the **[Cresco](https://github.com/CrescoEdge/agent)** edge-computing framework. It connects
to the [wsapi](https://github.com/CrescoEdge/wsapi) WebSocket plugin (`wss://host:8282`, authenticated with the
`cresco_service_key` header) to control agents, deploy plugins, run pipelines, stream the
data plane, and build stunnel tunnels.

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

# host/ip of an agent running the wsapi plugin, its port, and the wsapi service key
client = clientlib("localhost", 8282, "your-service-key", verify_ssl=False)

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
- **RPC vs fire-and-forget.** Messaging calls take an `is_rpc` flag: when true the call blocks for the reply,
  when false it is sent without waiting.

## API reference

Signatures are shown language-neutrally; names and behavior are identical in both clients.

### Client — `clientlib` / `CrescoClient`

| Method | Description |
|---|---|
| `clientlib(host, port, service_key, verify_ssl=False)` | Create the client for a wsapi endpoint. |
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
| `list_plugin_agent(dst_region, dst_agent)` | List plugins on an agent. |
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
| `create_tunnel(stunnel_id, src_region, src_agent, src_port, dst_region, dst_agent, dst_host, dst_port, buffer_size)` | Create a tunnel; plugin ids auto-resolved. Returns the plugin reply (status / `stunnel_config`). |
| `remove_tunnel(stunnel_id, src_region, src_agent, dst_region, dst_agent)` | Remove both ends of a tunnel. |
| `get_tunnel_list(region, agent)` | List tunnels on an agent. |
| `get_tunnel_status(region, agent, stunnel_id)` | Get a tunnel's status. |
| `get_tunnel_config(region, agent, stunnel_id)` | Get a tunnel's config. |
| `remove_src_tunnel(region, agent, stunnel_id)` | Remove only the source end (the server cascades the matching dst removal). |
| `remove_dst_tunnel(region, agent, stunnel_id)` | Remove only the destination end. |

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

## SSL verification

By default SSL certificate verification is disabled (Cresco agents use self-signed certs). Enable it with the
constructor flag:

```python
client = clientlib("localhost", 8282, "your-service-key", verify_ssl=True)
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
