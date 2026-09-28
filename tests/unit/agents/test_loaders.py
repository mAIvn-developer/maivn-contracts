# pyright: strict
"""Unit tests for deployed-agent registry contract loaders and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.agents import (
    load_agent_schema,
    load_agent_version_schema,
    load_message_binding_schema,
    validate_agent,
    validate_agent_version,
    validate_message_binding,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]
_MAX_AGENT_TOOL_DEPENDENCIES = 256


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_load_agent_schema_exposes_identity_only_fields() -> None:
    """Expose the strict deployed-agent identity field set."""
    schema = load_agent_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'agent_id',
        'project_id',
        'name',
        'description',
        'latest_version',
        'created_at',
        'updated_at',
    }
    assert set(schema['required']) == {
        'agent_id',
        'project_id',
        'name',
        'latest_version',
        'created_at',
        'updated_at',
    }


def test_load_agent_version_schema_exposes_immutable_version_fields() -> None:
    """Expose the strict immutable agent-version field set."""
    schema = load_agent_version_schema()

    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'agent_id',
        'version',
        'execution_mode',
        'model',
        'instructions',
        'tools_snapshot',
        'attached_skill_ids',
        'agents_snapshot',
        'agent_tool_dependencies',
        'swarm_roster',
        'options',
        'memory',
        'output_schema',
        'webhook_endpoint',
        'created_at',
        'created_by',
    }
    assert 'immutable' in schema['properties']['execution_mode']['description']


def test_agent_version_schema_exposes_closed_runtime_topology() -> None:
    """Expose the immutable roster using the existing invoke vocabulary."""
    schema = load_agent_version_schema()

    assert schema['properties']['agents_snapshot'] == {
        'type': 'array',
        'maxItems': 64,
        'description': 'Optional immutable invocation-local roster compiled for this version.',
        'items': {'$ref': '#/$defs/invokeAgentSpec'},
    }
    assert (
        schema['properties']['agent_tool_dependencies']['maxItems'] == _MAX_AGENT_TOOL_DEPENDENCIES
    )
    assert schema['properties']['swarm_roster']['type'] == 'boolean'
    assert schema['properties']['attached_skill_ids']['maxItems'] == _MAX_AGENT_TOOL_DEPENDENCIES
    assert schema['$defs']['invokeAgentSpec']['additionalProperties'] is False
    assert schema['$defs']['agentToolDependency']['required'] == [
        'tool_id',
        'agent_name',
        'arg_name',
    ]
    assert schema['$defs']['toolSnapshot']['properties']['tool_dependencies'] == {
        'type': 'array',
        'maxItems': _MAX_AGENT_TOOL_DEPENDENCIES,
        'description': 'Immutable tool outputs injected into this tool by argument name.',
        'items': {'$ref': '#/$defs/toolDependencyEdge'},
    }
    assert 'compose_argument' in schema['$defs']['modelSettings']['properties']
    assert 'compose_artifact' not in schema['$defs']['modelSettings']['properties']


def test_agent_version_schema_adds_optional_external_tool_snapshot_readers() -> None:
    """Keep historical versions readable while pinning new external dispatch metadata."""
    schema = load_agent_version_schema()
    tool_snapshot = schema['$defs']['toolSnapshot']
    webhook_execution = schema['$defs']['webhookToolExecution']
    options = schema['$defs']['versionOptions']

    expected_readers = {
        'tool_id',
        'version',
        'idempotency',
        'timeout_ms',
        'output_schema',
        'expected_runtime_ms',
    }
    assert expected_readers <= set(
        tool_snapshot['properties'],
    )
    assert set(tool_snapshot['required']) == {
        'name',
        'description',
        'parameters_schema',
        'execution',
    }
    assert options['properties']['sticky_workers']['default'] is False
    # Lookahead-free: pydantic-core (Rust regex) and Go RE2 reject look-around.
    assert webhook_execution['properties']['path']['pattern'] == '^/([^/?#][^?#]*)?$'
    assert webhook_execution['properties']['path']['minLength'] == 1
    assert schema['$defs']['webhookEndpoint']['properties']['url']['pattern'] == '^https://'


def test_load_message_binding_schema_exposes_one_discriminated_wire_object() -> None:
    """Expose one message-binding wire object discriminated by kind."""
    schema = load_message_binding_schema()

    assert schema['discriminator']['propertyName'] == 'kind'
    assert {entry['$ref'] for entry in schema['oneOf']} == {
        '#/$defs/templateMessageBinding',
        '#/$defs/callableMessageBinding',
    }
    template = schema['$defs']['templateMessageBinding']
    assert template['properties']['messages']['items']['type'] == 'string'
    assert 'server-side and authoritative' in template['description']


@pytest.mark.parametrize(
    ('fixture_name', 'validator_name'),
    [
        ('valid_agents.json', 'agent'),
        ('valid_agent_versions.json', 'version'),
        ('valid_message_bindings.json', 'binding'),
    ],
)
def test_validators_accept_valid_golden_fixtures(
    fixture_name: str,
    validator_name: str,
) -> None:
    """Accept every valid golden registry fixture."""
    validators: dict[str, ContractValidator] = {
        'agent': validate_agent,
        'version': validate_agent_version,
        'binding': validate_message_binding,
    }

    for fixture in _load_fixture(fixture_name):
        validated = validators[validator_name](fixture)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'validator_name'),
    [
        ('invalid_agents.json', 'agent'),
        ('invalid_agent_versions.json', 'version'),
        ('invalid_message_bindings.json', 'binding'),
    ],
)
def test_validators_reject_invalid_golden_fixtures(
    fixture_name: str,
    validator_name: str,
) -> None:
    """Reject every invalid golden registry fixture."""
    validators: dict[str, ContractValidator] = {
        'agent': validate_agent,
        'version': validate_agent_version,
        'binding': validate_message_binding,
    }

    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validators[validator_name](fixture)
