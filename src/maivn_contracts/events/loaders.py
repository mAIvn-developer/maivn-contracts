"""Typed loaders and validators for the canonical event contract files."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.artifacts.loaders import materialize_artifact_lifecycle_event_schema
from maivn_contracts.events.model import Event

ProjectionName = Literal['audit', 'billing', 'canvas', 'replay', 'trace', 'webhook']

_CONTRACTS_ROOT = SCHEMA_ROOT / 'events'

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


class _JsonSchemaValidator(Protocol):
    """Protocol for the typed validator method used by this module."""

    def validate(self, instance: object) -> None:
        """Validate an object against the configured JSON Schema."""


class _MissingProjectionMappingError(KeyError):
    """Raised when a projection lacks a canonical event mapping."""

    def __init__(self, projection: ProjectionName, event_type: str) -> None:
        """Build the missing projection mapping error."""
        message = f'No {projection} projection mapping for event type: {event_type}'
        super().__init__(message)


class _ContractObjectTypeError(TypeError, ValueError):
    """Raised when a contract file is not a JSON object."""

    def __init__(self, path: Path) -> None:
        """Build the invalid contract object error."""
        message = f'Contract file must contain a JSON object: {path}'
        super().__init__(message)


def load_event_schema() -> dict[str, Any]:
    """Load the canonical Event JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'event.schema.json')


def load_taxonomy() -> dict[str, Any]:
    """Load the canonical event taxonomy."""
    return _read_json(_CONTRACTS_ROOT / 'taxonomy.json')


def load_projection(name: ProjectionName) -> dict[str, Any]:
    """Load a projection mapping table by name."""
    return _read_json(_CONTRACTS_ROOT / 'projections' / f'{name}.json')


@lru_cache(maxsize=1)
def _event_validator() -> _JsonSchemaValidator:
    """Return the process-wide validator for the canonical Event schema.

    The Event schema is a constant contract file, so preparing it and metaschema-checking
    it produce the same validator every time. Doing that work per event made durable-log
    reads cost ~74ms an event - `check_schema` alone was ~73ms - so assembling one
    453-event session trace burned ~33s of CPU on the data plane's single event loop and
    starved every other request sharing it, including its Postgres reads.
    """
    schema = _schema_for_validation(load_event_schema())
    _check_event_schema(schema)
    return _build_event_validator(schema)


def validate_event(obj: Mapping[str, Any]) -> Event:
    """Validate an event-like mapping and return the typed wire model."""
    _event_validator().validate(obj)
    return Event.model_validate(obj)


def project_event_type(event_type: str, projection: ProjectionName) -> str | None:
    """Return the projected event type for a canonical event type.

    Canvas mappings may explicitly drop internal events and return `None`.
    Projection target events pass through unchanged.
    """
    projection_table = load_projection(projection)
    target_events = cast('list[str]', projection_table['target_events'])
    if event_type in target_events:
        return event_type

    mappings = cast('dict[str, dict[str, Any]]', projection_table['mappings'])
    mapping = mappings.get(event_type)
    if mapping is None:
        raise _MissingProjectionMappingError(projection, event_type)

    target = mapping['target']
    if target is None:
        return None
    return cast('str', target)


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(path)
    return cast('dict[str, Any]', loaded)


def _check_event_schema(schema: Mapping[str, Any]) -> None:
    check_schema = cast('Callable[[object], None]', Draft202012Validator.check_schema)
    check_schema(schema)


def _build_event_validator(schema: Mapping[str, Any]) -> _JsonSchemaValidator:
    validator_factory = cast('Callable[..., _JsonSchemaValidator]', Draft202012Validator)
    return validator_factory(schema, format_checker=FormatChecker())


def _schema_for_validation(schema: dict[str, Any]) -> dict[str, Any]:
    prepared = cast('dict[str, Any]', json.loads(json.dumps(schema)))
    serialized = json.dumps(prepared).replace(
        '"https://schemas.maivn.dev/artifacts/artifact_lifecycle_event.schema.json"',
        '"#/$defs/artifactLifecycleEventPayload"',
    )
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / 'event.schema.json')
    definitions = cast('dict[str, Any]', cast('dict[str, Any]', loaded).setdefault('$defs', {}))
    lifecycle = materialize_artifact_lifecycle_event_schema(
        _read_json(SCHEMA_ROOT / 'artifacts' / 'artifact_lifecycle_event.schema.json')
    )
    lifecycle.pop('$id', None)
    lifecycle.pop('$schema', None)
    rebased = json.loads(
        json.dumps(lifecycle).replace('"#/$defs/', '"#/$defs/artifactLifecycleEventPayload/$defs/')
    )
    definitions['artifactLifecycleEventPayload'] = cast('dict[str, Any]', rebased)
    return cast('dict[str, Any]', loaded)
