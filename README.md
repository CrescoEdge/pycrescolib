# Cresco Python Client (pycrescolib)

Python client library for the **[Cresco](https://github.com/CrescoEdge/agent)** edge-computing framework. It connects
to the [wsapi](https://github.com/CrescoEdge/wsapi) WebSocket plugin (`wss://host:8282`, authenticated with the
`cresco_service_key` header) to control agents, deploy plugins, run pipelines, stream the
data plane, and build stunnel tunnels.

Part of the Cresco framework — see the **[agent repository](https://github.com/CrescoEdge/agent)** for the full
architecture and the [Java client](https://github.com/CrescoEdge/clientlib) for the equivalent in Java.

**Install:** `pip install pycrescolib` (Python 3.8+; depends on `websockets`, `cryptography`, `backoff`).
From a source checkout use `pip install .`, and to build the distributions run `python -m build`.

---

This is an improved version of the pycrescolib Python client library for interacting with the Cresco distributed edge computing framework.

## Improvements

This version includes the following improvements over the original:

1. **Thread Safety**: Replaced the deprecated `thread` module with proper thread handling and added locks where necessary.
2. **Efficient JSON Handling**: Optimized JSON serialization/deserialization with proper error handling.
3. **Proper Logging**: Added comprehensive logging throughout the codebase.
4. **Base Classes**: Created base classes to avoid code duplication.
5. **Context Managers**: Added context managers for resource management.
6. **Retry Logic**: Implemented retry mechanisms for handling connection failures.
7. **Modern Async**: Used asyncio and the websockets library for better WebSocket handling.
8. **Comprehensive Documentation**: Added docstrings and type hints throughout the code.

## Dependencies

- Python 3.7+
- websockets>=10.0
- cryptography>=36.0.0
- backoff>=2.0.0

## Installation

```bash
pip install -r requirements.txt
```

## Usage Example

### Synchronous Usage (Backward Compatible)

```python
from pycrescolib.clientlib import clientlib

# Connect to Cresco server
client = clientlib("localhost", 8282, "your-service-key")
if client.connect():
    # Get agent list
    agent_list = client.globalcontroller.get_agent_list()
    print(agent_list)
    
    # Clean up
    client.close()
```

### Using Context Manager

```python
from pycrescolib.clientlib import clientlib

# Connect to Cresco server using context manager
with clientlib("localhost", 8282, "your-service-key").connection() as client:
    # Get agent list
    agent_list = client.globalcontroller.get_agent_list()
    print(agent_list)
    # Context manager handles cleanup automatically
```

### Using Dataplane

```python
from pycrescolib.clientlib import clientlib

# Create client
client = clientlib("localhost", 8282, "your-service-key")
client.connect()

# Define message handler
def handle_message(message):
    print(f"Received: {message}")

# Create dataplane
dp = client.get_dataplane("my-stream", handle_message)
dp.connect()

# Send data
dp.send(json.dumps({"data": "pycrescolib_test"}))

# Clean up
dp.close()
client.close()
```

## Migration Notes

This version maintains backward compatibility with the original API, but includes additional async functionality for those who want to use it directly.

If you're using the async API directly, use the async/await syntax:

```python
import asyncio
from pycrescolib.wc_interface import ws_interface

async def main():
    ws = ws_interface()
    await ws.connect("wss://localhost:8282/api/apisocket", "your-service-key")
    
    # Your code here
    
    await ws.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration

You can configure the logging level:

```python
from pycrescolib.clientlib import configure_logging
import logging

# Set logging level
configure_logging(level=logging.DEBUG)
```

## SSL Verification

By default, SSL certificate verification is disabled. To enable it:

```python
# Create client with SSL verification enabled
client = clientlib("localhost", 8282, "your-service-key", verify_ssl=True)
```

## License

Same as the original pycrescolib license.