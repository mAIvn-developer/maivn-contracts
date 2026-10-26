"""Typed loaders and validators for owned tool contract files."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.artifacts import load_artifact_ref_schema
from maivn_contracts.tools.model import (
    ToolCall,
    ToolCallback,
    ToolDispatch,
    ToolOutcomeVariant,
    ToolSpecVariant,
)

_CONTRACTS_ROOT = SCHEMA_ROOT / 'tools'
_ARTIFACT_REF_SCHEMA_ID = 'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json'
_TOOL_SPEC_ADAPTER: TypeAdapter[ToolSpecVariant] = TypeAdapter[ToolSpecVariant](
    ToolSpecVariant,
)
_TOOL_OUTCOME_ADAPTER: TypeAdapter[ToolOutcomeVariant] = TypeAdapter[ToolOutcomeVariant](
    ToolOutcomeVariant,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


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


def load_tool_spec_schema() -> dict[str, Any]:
    """Load the ToolSpec JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'tool_spec.schema.json')


def load_tool_call_schema() -> dict[str, Any]:
    """Load the ToolCall JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'tool_call.schema.json')


def load_tool_outcome_schema() -> dict[str, Any]:
    """Load the ToolOutcome JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'tool_outcome.schema.json')


def load_tool_dispatch_schema() -> dict[str, Any]:
    """Load the ToolDispatch JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'tool_dispatch.schema.json')


def load_tool_callback_schema() -> dict[str, Any]:
    """Load the ToolCallback JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'tool_callback.schema.json')


def validate_tool_spec(obj: Mapping[str, Any]) -> ToolSpecVariant:
    """Validate a tool-spec-like mapping and return the typed wire model."""
    schema = load_tool_spec_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return _TOOL_SPEC_ADAPTER.validate_python(obj)


def validate_tool_call(obj: Mapping[str, Any]) -> ToolCall:
    """Validate a tool-call-like mapping and return the typed wire model."""
    schema = load_tool_call_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return ToolCall.model_validate(obj)


def validate_tool_outcome(obj: Mapping[str, Any]) -> ToolOutcomeVariant:
    """Validate a tool-outcome-like mapping and return the typed wire model."""
    schema = materialize_tool_outcome_schema(load_tool_outcome_schema())
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return _TOOL_OUTCOME_ADAPTER.validate_python(obj)


def validate_tool_dispatch(obj: Mapping[str, Any]) -> ToolDispatch:
    """Validate an external tool dispatch mapping and return its typed wire model."""
    schema = load_tool_dispatch_schema()
    _check_schema(schema)
    _build_validator(schema).validate(obj)
    return ToolDispatch.model_validate(obj)


def validate_tool_callback(obj: Mapping[str, Any]) -> ToolCallback:
    """Validate an external tool callback mapping and return its typed wire model."""
    schema = _callback_schema_for_validation(load_tool_callback_schema())
    _check_schema(schema)
    _build_validator(schema).validate(obj)
    return ToolCallback.model_validate(obj)


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


def _callback_schema_for_validation(schema: dict[str, Any]) -> dict[str, Any]:
    prepared = copy.deepcopy(schema)
    properties = cast('dict[str, Any]', prepared['properties'])
    properties['outcome'] = materialize_tool_outcome_schema(load_tool_outcome_schema())
    return prepared


def materialize_tool_outcome_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline canonical ArtifactRef for this schema and its composite consumers."""
    materialized = copy.deepcopy(schema)
    artifact_schema = _rebase_artifact_ref_definitions(copy.deepcopy(load_artifact_ref_schema()))
    artifact_schema.pop('$id', None)
    artifact_schema.pop('$schema', None)
    definitions = cast('dict[str, Any]', materialized.setdefault('$defs', {}))
    definitions['artifactRef'] = artifact_schema
    serialized = json.dumps(materialized).replace(
        f'"{_ARTIFACT_REF_SCHEMA_ID}"', '"#/$defs/artifactRef"'
    )
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / 'tool_outcome.schema.json')
    return cast('dict[str, Any]', loaded)


def _rebase_artifact_ref_definitions(schema: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(schema).replace('"#/$defs/', '"#/$defs/artifactRef/$defs/')
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / 'tool_outcome.schema.json')
    return cast('dict[str, Any]', loaded)
