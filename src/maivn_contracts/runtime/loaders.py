"""Typed loaders and validators for runtime protocol contract files."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter

from maivn_contracts.messages import load_message_schema
from maivn_contracts.messages.loaders import materialize_message_schema
from maivn_contracts.runtime.model import Command, RunConfig, RunState, StreamPart

_CONTRACTS_ROOT = Path(__file__).resolve().parents[3] / 'runtime'
_COMMAND_SCHEMA_ID = 'https://schemas.maivn.dev/runtime/command.schema.json'
_COMMAND_ADAPTER: TypeAdapter[Command] = TypeAdapter(Command)

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


def load_run_config_schema() -> dict[str, Any]:
    """Load the RunConfig JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'run_config.schema.json')


def load_command_schema() -> dict[str, Any]:
    """Load the Command JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'command.schema.json')


def load_stream_part_schema() -> dict[str, Any]:
    """Load the StreamPart JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'stream_part.schema.json')


def load_run_state_schema() -> dict[str, Any]:
    """Load the RunState JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'run_state.schema.json')


def validate_run_config(obj: Mapping[str, Any]) -> RunConfig:
    """Validate a run-config-like mapping and return the typed wire model."""
    schema = load_run_config_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return RunConfig.model_validate(obj)


def validate_command(obj: Mapping[str, Any]) -> Command:
    """Validate a command-like mapping and return the typed wire model."""
    schema = load_command_schema()
    _check_schema(schema)
    validator = _build_validator(_schema_for_validation(schema))
    validator.validate(obj)
    return _COMMAND_ADAPTER.validate_python(obj)


def validate_stream_part(obj: Mapping[str, Any]) -> StreamPart:
    """Validate a stream-part-like mapping and return the typed wire model."""
    schema = load_stream_part_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return StreamPart.model_validate(obj)


def validate_run_state(obj: Mapping[str, Any]) -> RunState:
    """Validate a run-state-like mapping and return the typed wire model."""
    schema = load_run_state_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return RunState.model_validate(obj)


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


def _schema_for_validation(schema: Mapping[str, Any]) -> dict[str, Any]:
    prepared = cast('dict[str, Any]', copy.deepcopy(schema))
    if prepared.get('$id') != _COMMAND_SCHEMA_ID:
        return prepared

    defs = cast('dict[str, Any]', prepared['$defs'])
    defs['message'] = materialize_message_schema(load_message_schema())
    return prepared
