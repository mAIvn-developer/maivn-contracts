# pyright: strict
"""Unit tests for tool contract loaders and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError

from maivn_contracts.tools import (
    ErrorToolOutcome,
    FunctionToolSpec,
    MCPToolSpec,
    OkToolOutcome,
    SystemToolSpec,
    ToolArgumentProducerRequirement,
    ToolCall,
    ToolOutcome,
    ToolSpec,
    load_tool_call_schema,
    load_tool_outcome_schema,
    load_tool_spec_schema,
    validate_tool_call,
    validate_tool_outcome,
    validate_tool_spec,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
TOOL_SPEC_VARIANT_COUNT = 3
TOOL_OUTCOME_VARIANT_COUNT = 2
ContractModel: TypeAlias = (
    FunctionToolSpec | MCPToolSpec | SystemToolSpec | ToolCall | OkToolOutcome | ErrorToolOutcome
)
ContractValidator: TypeAlias = Callable[[dict[str, Any]], ContractModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_load_tool_spec_schema_exposes_function_mcp_and_system_kinds() -> None:
    """Expose the strict ToolSpec field set and kind discriminator."""
    schema = load_tool_spec_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'permissions',
        'destructive',
        'tool_id',
        'kind',
        'namespace',
        'version',
        'idempotency',
        'timeout_ms',
        'auth',
        'name',
        'description',
        'input_schema',
        'output_schema',
        'model_constructor',
        'argument_producer_requirements',
        'server_ref',
        'tool_name',
        'schema_policy',
    }
    assert set(schema['required']) == {
        'tool_id',
        'kind',
        'namespace',
        'version',
        'idempotency',
        'timeout_ms',
    }
    assert set(schema['properties']['kind']['enum']) == {'function', 'mcp', 'system'}
    assert len(schema['oneOf']) == TOOL_SPEC_VARIANT_COUNT


def test_load_tool_call_schema_exposes_spec_ref_arguments_and_lineage() -> None:
    """Expose the model-emitted tool call shape."""
    schema = load_tool_call_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'call_id',
        'spec_ref',
        'arguments',
        'lineage',
        'retained_dependencies',
    }
    assert set(schema['required']) == {'call_id', 'spec_ref', 'arguments', 'lineage'}


def test_load_tool_outcome_schema_exposes_ok_error_and_artifact_refs() -> None:
    """Expose the strict ToolOutcome variants and returnable artifact refs."""
    schema = load_tool_outcome_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'call_id',
        'status',
        'duration_ms',
        'result',
        'error',
        'artifact_refs',
    }
    assert set(schema['required']) == {'call_id', 'status', 'duration_ms'}
    assert set(schema['properties']['status']['enum']) == {'ok', 'error'}
    assert len(schema['oneOf']) == TOOL_OUTCOME_VARIANT_COUNT
    assert schema['properties']['artifact_refs']['items'] == {
        '$ref': 'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json'
    }
    assert 'artifactStorageRef' not in schema['$defs']
    assert 'toolOutcomeArtifactRef' not in schema['$defs']


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('valid_tool_specs.json', validate_tool_spec),
        ('valid_tool_calls.json', validate_tool_call),
        ('valid_tool_outcomes.json', validate_tool_outcome),
    ],
)
def test_validators_accept_valid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Accept every valid tools-contract fixture."""
    for fixture in _load_fixture(fixture_name):
        validated = validator(fixture)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('invalid_tool_specs.json', validate_tool_spec),
        ('invalid_tool_calls.json', validate_tool_call),
        ('invalid_tool_outcomes.json', validate_tool_outcome),
    ],
)
def test_validators_reject_invalid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Reject every invalid tools-contract fixture at the schema boundary."""
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)


def test_validator_return_types_are_public_contract_models() -> None:
    """Return the public typed models from each validator."""
    spec = validate_tool_spec(_load_fixture('valid_tool_specs.json')[0])
    call = validate_tool_call(_load_fixture('valid_tool_calls.json')[0])
    outcome = validate_tool_outcome(_load_fixture('valid_tool_outcomes.json')[0])

    assert isinstance(spec, ToolSpec)
    assert isinstance(call, ToolCall)
    assert isinstance(outcome, ToolOutcome)


def test_function_tool_contract_carries_model_constructor_marker() -> None:
    """Identify SDK Pydantic constructors without changing their execution kind."""
    validated = validate_tool_spec(
        {
            'tool_id': 'VehicleSpec',
            'kind': 'function',
            'namespace': 'sdk',
            'version': 'v1',
            'idempotency': 'unknown',
            'timeout_ms': 30000,
            'name': 'VehicleSpec',
            'description': 'Build a vehicle specification.',
            'input_schema': {
                'type': 'object',
                'properties': {'model': {'type': 'string'}},
                'required': ['model'],
            },
            'model_constructor': True,
        },
    )

    assert isinstance(validated, FunctionToolSpec)
    assert validated.model_constructor is True


def test_function_tool_contract_carries_nested_argument_producer_requirements() -> None:
    """Describe caller-authored reference edges without static result injection."""
    validated = validate_tool_spec(
        {
            'tool_id': 'DOCUMENTS_put_block',
            'kind': 'function',
            'namespace': 'sdk',
            'version': 'v1',
            'idempotency': 'idempotent',
            'timeout_ms': 30000,
            'name': 'DOCUMENTS_put_block',
            'description': 'Upsert a document block.',
            'input_schema': {'type': 'object', 'properties': {}},
            'argument_producer_requirements': [
                {
                    'argument_path': 'block.composition',
                    'producer_tool_name': 'DOCUMENTS_compose_artifact',
                    'reference_kind': 'composition_reference',
                }
            ],
        }
    )

    assert isinstance(validated, FunctionToolSpec)
    assert validated.argument_producer_requirements == (
        ToolArgumentProducerRequirement(
            argument_path='block.composition',
            producer_tool_name='DOCUMENTS_compose_artifact',
            reference_kind='composition_reference',
        ),
    )
    assert validated.tool_dependencies is None


def test_function_tool_contract_rejects_duplicate_argument_producer_requirements() -> None:
    """One argument path cannot name multiple or repeated reference producers."""
    requirement = ToolArgumentProducerRequirement(
        argument_path='block.composition',
        producer_tool_name='DOCUMENTS_compose_artifact',
        reference_kind='composition_reference',
    )

    with pytest.raises(ValueError, match=r'block\.composition'):
        FunctionToolSpec(
            tool_id='DOCUMENTS_put_block',
            kind='function',
            namespace='sdk',
            version='v1',
            idempotency='idempotent',
            timeout_ms=30000,
            name='DOCUMENTS_put_block',
            description='Upsert a document block.',
            input_schema={'type': 'object'},
            argument_producer_requirements=(requirement, requirement),
        )
