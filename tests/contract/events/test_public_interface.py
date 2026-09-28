# pyright: strict
"""Contract tests for the event module public interface."""

from __future__ import annotations

from maivn_contracts import events
from maivn_contracts.events import Event, load_event_schema


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public event module exports."""
    assert set(events.__all__) == {
        'AuditEntry',
        'AuditLineage',
        'BillingEntry',
        'BillingLineage',
        'BillingLedger',
        'BillingUnitKind',
        'ReplayCoverage',
        'ReplayFrame',
        'ReplayFrameKind',
        'ReplayLineage',
        'SessionReplay',
        'SessionAuditLog',
        'Event',
        'RecursiveSessionTrace',
        'SessionTrace',
        'TraceNode',
        'TraceNodeKind',
        'TraceNodeStatus',
        'TraceTokens',
        'assemble_session_trace',
        'project_trace_for_staff',
        'assemble_session_audit',
        'assemble_billing',
        'assemble_session_replay',
        'load_event_schema',
        'load_projection',
        'load_taxonomy',
        'project_event_type',
        'validate_event',
    }

    for exported_name in events.__all__:
        assert hasattr(events, exported_name)


def test_event_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the Pydantic model and JSON Schema field sets aligned."""
    schema = load_event_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(Event.model_fields)
    required_model_fields = {
        name for name, field in Event.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])
    assert 'trace_id' not in schema['required']
    assert schema['properties']['trace_id']['pattern'] == r'^[0-9a-f]{32}$'
    assert schema['properties']['trace_id']['not'] == {'const': '00000000000000000000000000000000'}
