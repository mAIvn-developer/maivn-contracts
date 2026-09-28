# maivn-contracts

`maivn-contracts` contains the typed wire models, JSON Schemas, loaders, and
validators shared by mAIvn services and the Python SDK.

## Install

```bash
pip install maivn-contracts
```

Import from a focused public namespace rather than from its implementation
modules:

```python
from maivn_contracts.events import Event, validate_event
from maivn_contracts.messages import Message, validate_message
from maivn_contracts.tools import ToolCall, validate_tool_call
```

The package exposes contract families for agents, artifacts, events, messages,
resources, runtime state, scenarios, swarms, tools, toolsets, and workers. Each
family's `load_*_schema` functions return the checked-in schema, `validate_*`
functions validate untrusted wire data, and Pydantic models provide typed
construction and parsing.

Treat schemas and their canonical encodings as protocol boundaries. Do not
copy private fields into logs or relax a validator only in one consumer. Update
the shared contract and all affected producers and consumers together.
