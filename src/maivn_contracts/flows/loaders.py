"""Typed loader and validator for the canonical Flow graph contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.flows.model import FlowGraph

_CONTRACTS_ROOT = SCHEMA_ROOT / 'flows'

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


class _JsonSchemaValidator(Protocol):
    """Protocol for the validator method used by this module."""

    def validate(self, instance: object) -> None:
        """Validate an object against the configured JSON Schema."""


class _ContractObjectTypeError(TypeError, ValueError):
    """Raised when a Flow contract file is not a JSON object."""

    def __init__(self, path: Path) -> None:
        """Build the invalid contract object error."""
        message = f'Contract file must contain a JSON object: {path}'
        super().__init__(message)


def load_flow_graph_schema() -> dict[str, Any]:
    """Load the canonical Flow graph JSON Schema."""
    path = _CONTRACTS_ROOT / 'flow_graph.schema.json'
    loaded = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(path)
    return cast('dict[str, Any]', loaded)


def validate_flow_graph(obj: Mapping[str, Any]) -> FlowGraph:
    """Validate a Flow-like mapping through JSON Schema and the graph model."""
    schema = load_flow_graph_schema()
    check_schema = cast('Callable[[object], None]', Draft202012Validator.check_schema)
    check_schema(schema)
    validator_factory = cast('Callable[..., _JsonSchemaValidator]', Draft202012Validator)
    validator_factory(schema).validate(obj)
    return FlowGraph.model_validate(obj)
