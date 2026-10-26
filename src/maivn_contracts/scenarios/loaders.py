"""Typed loaders and validators for scenario and trigger contract files."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.agents import load_agent_version_schema, load_message_binding_schema
from maivn_contracts.artifacts import load_artifact_ref_schema
from maivn_contracts.flows import load_flow_graph_schema
from maivn_contracts.scenarios.model import (
    Scenario,
    Trigger,
    TriggerFire,
    TriggerInvocation,
    TriggerLaunch,
)

_CONTRACTS_ROOT = SCHEMA_ROOT / 'scenarios'
_TRIGGER_SCHEMA_ID = 'https://schemas.maivn.dev/scenarios/trigger.schema.json'
_SCENARIO_SCHEMA_ID = 'https://schemas.maivn.dev/scenarios/scenario.schema.json'

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


def load_trigger_schema() -> dict[str, Any]:
    """Load the Trigger JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'trigger.schema.json')


def load_trigger_fire_schema() -> dict[str, Any]:
    """Load the TriggerFire JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'trigger_fire.schema.json')


def load_trigger_invocation_schema() -> dict[str, Any]:
    """Load the TriggerInvocation JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'trigger_invocation.schema.json')


def load_trigger_launch_schema() -> dict[str, Any]:
    """Load the exact-version internal TriggerLaunch JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'trigger_launch.schema.json')


def load_scenario_schema() -> dict[str, Any]:
    """Load the Scenario JSON Schema."""
    return _read_json(_CONTRACTS_ROOT / 'scenario.schema.json')


def validate_trigger(obj: Mapping[str, Any]) -> Trigger:
    """Validate a trigger-like mapping and return the typed wire model."""
    schema = load_trigger_schema()
    _check_schema(schema)
    validator = _build_validator(_schema_for_validation(schema))
    validator.validate(obj)
    return Trigger.model_validate(obj)


def validate_trigger_fire(obj: Mapping[str, Any]) -> TriggerFire:
    """Validate a trigger-fire-like mapping and return the typed wire model."""
    schema = load_trigger_fire_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return TriggerFire.model_validate(obj)


def validate_trigger_invocation(obj: Mapping[str, Any]) -> TriggerInvocation:
    """Validate a trigger-invocation-like mapping and return the typed wire model."""
    schema = load_trigger_invocation_schema()
    _check_schema(schema)
    validator = _build_validator(schema)
    validator.validate(obj)
    return TriggerInvocation.model_validate(obj)


def validate_trigger_launch(obj: Mapping[str, Any]) -> TriggerLaunch:
    """Validate an internal trigger launch mapping and return its typed wire model."""
    schema = load_trigger_launch_schema()
    _check_schema(schema)
    validator = _build_validator(_schema_for_validation(schema))
    validator.validate(obj)
    return TriggerLaunch.model_validate(obj)


def validate_scenario(obj: Mapping[str, Any]) -> Scenario:
    """Validate a scenario-like mapping and return the typed wire model."""
    schema = load_scenario_schema()
    _check_schema(schema)
    validator = _build_validator(_schema_for_validation(schema))
    validator.validate(obj)
    return Scenario.model_validate(obj)


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
    if prepared.get('$id') == _SCENARIO_SCHEMA_ID:
        properties = cast('dict[str, Any]', prepared['properties'])
        properties['flow_graph'] = {
            'oneOf': [load_flow_graph_schema(), {'type': 'null'}],
            'description': (
                'Optional canonical Flow authoring topology. '
                'Legacy records without a graph remain valid.'
            ),
        }
        return _materialize_file_output_artifact_authorities(prepared)
    if prepared.get('$id') != _TRIGGER_SCHEMA_ID:
        if prepared.get('$id') == 'https://schemas.maivn.dev/scenarios/trigger_launch.schema.json':
            properties = cast('dict[str, Any]', prepared['properties'])
            properties['agent_version_snapshot'] = load_agent_version_schema()
            properties['binding'] = load_message_binding_schema()
        return prepared

    properties = cast('dict[str, Any]', prepared['properties'])
    properties['binding'] = load_message_binding_schema()
    return prepared


def _materialize_file_output_artifact_authorities(
    schema: dict[str, Any],
) -> dict[str, Any]:
    artifact_ref = load_artifact_ref_schema()
    artifact_definitions = cast('dict[str, Any]', artifact_ref['$defs'])
    definitions = cast('dict[str, Any]', schema['$defs'])
    definitions['artifactKind'] = copy.deepcopy(artifact_definitions['artifactKind'])
    definitions['mimeType'] = copy.deepcopy(artifact_definitions['mimeType'])

    serialized = json.dumps(schema)
    serialized = serialized.replace(
        '"https://schemas.maivn.dev/artifacts/artifact_ref.schema.json#/$defs/artifactKind"',
        '"#/$defs/artifactKind"',
    )
    serialized = serialized.replace(
        '"https://schemas.maivn.dev/artifacts/artifact_ref.schema.json#/$defs/mimeType"',
        '"#/$defs/mimeType"',
    )
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / 'scenario.schema.json')
    return cast('dict[str, Any]', loaded)
