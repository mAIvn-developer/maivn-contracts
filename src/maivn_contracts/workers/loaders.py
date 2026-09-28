"""Typed loaders and validators for Mode A worker contract files."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker

from maivn_contracts.tools import load_tool_callback_schema, load_tool_dispatch_schema
from maivn_contracts.tools.loaders import materialize_tool_outcome_schema
from maivn_contracts.workers.model import WorkerConnection, WorkerFrame

_CONTRACTS_ROOT = Path(__file__).resolve().parents[3] / 'workers'

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class _JsonSchemaValidator(Protocol):
    """Protocol for the typed validator method used by this module."""

    def validate(self, instance: object) -> None:
        """Validate an object against the configured JSON Schema."""


class _ContractObjectTypeError(TypeError, ValueError):
    """Raised when a contract file is not a JSON object."""

    def __init__(self, path: Path) -> None:
        """Build the invalid contract object error."""
        message = f'Contract file must contain a JSON object: {path}'
        super().__init__(message)


def load_worker_connection_schema() -> dict[str, Any]:
    """Load the WorkerConnection JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'worker_connection.schema.json')


def load_worker_frame_schema() -> dict[str, Any]:
    """Load the WorkerFrame JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'worker_frame.schema.json')


def validate_worker_connection(obj: Mapping[str, Any]) -> WorkerConnection:
    """Validate a worker connection mapping and return its typed wire model."""
    schema = load_worker_connection_schema()
    _check_schema(schema)
    _build_validator(schema).validate(obj)
    return WorkerConnection.model_validate(obj)


def validate_worker_frame(obj: Mapping[str, Any]) -> WorkerFrame:
    """Validate a worker frame mapping and return its typed wire model."""
    schema = _schema_for_validation(load_worker_frame_schema())
    _check_schema(schema)
    _build_validator(schema).validate(obj)
    return WorkerFrame.model_validate(obj)


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(path)
    return cast('dict[str, Any]', loaded)


def _check_schema(schema: Mapping[str, Any]) -> None:
    check_schema = cast('Callable[[object], None]', Draft202012Validator.check_schema)
    check_schema(schema)


def _build_validator(schema: Mapping[str, Any]) -> _JsonSchemaValidator:
    validator_factory = cast('Callable[..., _JsonSchemaValidator]', Draft202012Validator)
    return validator_factory(schema, format_checker=FormatChecker())


def _schema_for_validation(schema: dict[str, Any]) -> dict[str, Any]:
    prepared = copy.deepcopy(schema)
    definitions = cast('dict[str, Any]', prepared['$defs'])
    dispatch = cast('dict[str, Any]', definitions['dispatchPayload'])
    callback = cast('dict[str, Any]', definitions['toolResultPayload'])
    dispatch_properties = cast('dict[str, Any]', dispatch['properties'])
    callback_properties = cast('dict[str, Any]', callback['properties'])
    dispatch_properties['dispatch'] = load_tool_dispatch_schema()
    callback_properties['callback'] = _replace_callback_outcome(load_tool_callback_schema())
    return prepared


def _replace_callback_outcome(schema: dict[str, Any]) -> dict[str, Any]:
    prepared = copy.deepcopy(schema)
    properties = cast('dict[str, Any]', prepared['properties'])
    properties['outcome'] = materialize_tool_outcome_schema(
        _read_json(
            Path(__file__).resolve().parents[3] / 'tools' / 'tool_outcome.schema.json',
        )
    )
    return prepared
