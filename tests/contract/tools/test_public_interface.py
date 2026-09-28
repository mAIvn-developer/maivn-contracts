# pyright: strict
"""Contract tests for the tools module public interface."""

from __future__ import annotations

from maivn_contracts import tools
from maivn_contracts.artifacts import ArtifactRef
from maivn_contracts.tools import (
    AuthRef,
    FunctionToolSpec,
    MCPRegistryServerRef,
    MCPToolSpec,
    MCPUrlServerRef,
    SystemToolSpec,
    ToolArgumentDependency,
    ToolArgumentProducerRequirement,
    ToolCall,
    ToolCallLineage,
    ToolDependencyEdge,
    ToolOutcome,
    ToolOutcomeArtifactRef,
    ToolOutcomeError,
    ToolSpecRef,
    load_tool_call_schema,
    load_tool_outcome_schema,
    load_tool_spec_schema,
)


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public tools module exports."""
    assert set(tools.__all__) == {
        'AuthRef',
        'ErrorToolOutcome',
        'FunctionToolSpec',
        'IdempotencyHint',
        'MCPRegistryServerRef',
        'MCPServerRef',
        'MCPToolSpec',
        'MCPUrlServerRef',
        'OkToolOutcome',
        'SystemToolSpec',
        'ToolCall',
        'ToolCallLineage',
        # Modes A/B slice 1 (task 107): dispatch + callback envelopes.
        'ToolCallback',
        'ToolDispatch',
        'ToolOutcome',
        'ToolOutcomeArtifactRef',
        'ToolOutcomeError',
        'ToolOutcomeVariant',
        'ToolSpec',
        'ToolDependencyEdge',
        'ToolArgumentDependency',
        'ToolArgumentProducerRequirement',
        'ToolSpecRef',
        'ToolSpecVariant',
        'load_tool_call_schema',
        'load_tool_callback_schema',
        'load_tool_dispatch_schema',
        'load_tool_outcome_schema',
        'load_tool_spec_schema',
        'validate_tool_call',
        'validate_tool_callback',
        'validate_tool_dispatch',
        'validate_tool_outcome',
        'validate_tool_spec',
    }

    for exported_name in tools.__all__:
        assert hasattr(tools, exported_name)


def test_tool_spec_variants_and_json_schema_agree_field_for_field() -> None:
    """Keep ToolSpec variant models aligned with schema definitions."""
    schema = load_tool_spec_schema()

    assert set(FunctionToolSpec.model_fields) == set(
        schema['$defs']['functionToolSpec']['properties'],
    )
    assert set(MCPToolSpec.model_fields) == set(schema['$defs']['mcpToolSpec']['properties'])
    assert set(SystemToolSpec.model_fields) == set(
        schema['$defs']['systemToolSpec']['properties'],
    )
    assert set(AuthRef.model_fields) == set(schema['$defs']['authRef']['properties'])
    assert set(ToolArgumentDependency.model_fields) == set(
        schema['$defs']['toolArgumentDependency']['properties'],
    )
    assert set(ToolArgumentProducerRequirement.model_fields) == set(
        schema['$defs']['toolArgumentProducerRequirement']['properties'],
    )
    assert set(MCPRegistryServerRef.model_fields) == set(
        schema['$defs']['mcpRegistryServerRef']['properties'],
    )
    assert set(MCPUrlServerRef.model_fields) == set(
        schema['$defs']['mcpUrlServerRef']['properties'],
    )


def test_tool_call_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the ToolCall model and JSON Schema field sets aligned."""
    schema = load_tool_call_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(ToolCall.model_fields)
    required_model_fields = {
        name for name, field in ToolCall.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])
    assert set(ToolSpecRef.model_fields) == set(schema['$defs']['toolSpecRef']['properties'])
    assert set(ToolCallLineage.model_fields) == set(
        schema['$defs']['toolCallLineage']['properties'],
    )
    assert ToolCallLineage.model_fields['relation'].default is None


def test_dependency_revision_contract_fields_are_explicit_opt_ins() -> None:
    """A dependency and lineage remain ordinary unless both opt-in fields are present."""
    schema = load_tool_spec_schema()
    edge = schema['$defs']['functionToolSpec']['properties']['tool_dependencies']['items']

    assert set(ToolDependencyEdge.model_fields) == set(edge['properties'])
    assert ToolDependencyEdge.model_fields['revision_policy'].default is None
    assert edge['properties']['revision_policy']['enum'] == ['on_validation_error']


def test_tool_outcome_variants_and_json_schema_agree_field_for_field() -> None:
    """Keep ToolOutcome variant models aligned with schema definitions."""
    schema = load_tool_outcome_schema()

    assert set(ToolOutcomeError.model_fields) == set(
        schema['$defs']['toolOutcomeError']['properties'],
    )
    assert ToolOutcomeArtifactRef is ArtifactRef
    assert set(ToolOutcome.model_fields) == {'call_id', 'duration_ms', 'artifact_refs'}
    assert schema['properties']['artifact_refs']['items'] == {
        '$ref': 'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json'
    }
    assert 'artifactStorageRef' not in schema['$defs']
    assert 'toolOutcomeArtifactRef' not in schema['$defs']
