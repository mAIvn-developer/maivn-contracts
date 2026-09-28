# pyright: strict
"""Contract tests for the canonical Flow graph public interface."""

from __future__ import annotations

from maivn_contracts import flows
from maivn_contracts.flows import FlowGraph, load_flow_graph_schema


def test_public_interface_exports_are_pinned() -> None:
    """Expose only the closed graph models and validation entry points."""
    assert set(flows.__all__) == {
        'ComponentKind',
        'EdgeKind',
        'FlowComponentRef',
        'FlowEdge',
        'FlowGraph',
        'FlowLayout',
        'FlowNestedFlowRef',
        'FlowNode',
        'FlowOutputNode',
        'FlowPosition',
        'FlowResourceNode',
        'FlowRuntimeRef',
        'FlowScopeNode',
        'FlowTriggerNode',
        'ResourceRelationship',
        'load_flow_graph_schema',
        'validate_flow_graph',
    }


def test_model_and_schema_top_level_fields_agree() -> None:
    """Keep the hand-authored schema aligned with the public model."""
    schema = load_flow_graph_schema()

    assert set(schema['properties']) == set(FlowGraph.model_fields)
    assert set(schema['required']) == {
        name for name, field in FlowGraph.model_fields.items() if field.is_required()
    }
