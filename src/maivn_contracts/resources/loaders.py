"""Typed loaders and validators for resource-processing contract files."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.messages import load_attachment_schema
from maivn_contracts.resources.model import DerivedArtifact, ProcessingState, ResourcePolicy

_CONTRACTS_ROOT = SCHEMA_ROOT / 'resources'
_RESOURCE_POLICY_SCHEMA_ID = 'https://schemas.maivn.dev/resources/resource_policy.schema.json'

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


def load_resource_policy_schema() -> dict[str, Any]:
    """Load the ResourcePolicy JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'resource_policy.schema.json')


def load_processing_state_schema() -> dict[str, Any]:
    """Load the ProcessingState JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'processing_state.schema.json')


def load_derived_artifact_schema() -> dict[str, Any]:
    """Load the DerivedArtifact JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'derived_artifact.schema.json')


def validate_resource_policy(obj: Mapping[str, Any]) -> ResourcePolicy:
    """Validate a resource-policy-like mapping and return the typed wire model."""
    schema = load_resource_policy_schema()
    _check_schema(schema)
    validator = _build_validator(_schema_for_validation(schema))
    validator.validate(obj)
    return ResourcePolicy.model_validate(obj)


def validate_processing_state(obj: Mapping[str, Any]) -> ProcessingState:
    """Validate a processing-state-like mapping and return the typed wire model."""
    schema = load_processing_state_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return ProcessingState.model_validate(obj)


def validate_derived_artifact(obj: Mapping[str, Any]) -> DerivedArtifact:
    """Validate a derived-artifact-like mapping and return the typed wire model."""
    schema = load_derived_artifact_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return DerivedArtifact.model_validate(obj)


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
    if prepared.get('$id') != _RESOURCE_POLICY_SCHEMA_ID:
        return prepared

    defs = cast('dict[str, Any]', prepared['$defs'])
    defs['attachment'] = load_attachment_schema()
    return prepared
