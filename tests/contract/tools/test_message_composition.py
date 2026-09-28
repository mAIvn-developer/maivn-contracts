# pyright: strict
"""Contract tests for tools composing with the public Message contract."""

from __future__ import annotations

from maivn_contracts.messages import validate_message
from maivn_contracts.tools import validate_tool_call, validate_tool_outcome


def test_tool_call_id_matches_tool_role_message_metadata() -> None:
    """Pin tool call id composition through Message.metadata.tool_call_id."""
    tool_call = validate_tool_call(
        {
            'call_id': 'call-lookup-001',
            'spec_ref': {
                'tool_id': 'tool-lookup-case',
                'namespace': 'support',
                'version': '2026-07-03',
            },
            'arguments': {'case_id': 'case-1001'},
            'lineage': {
                'session_id': 'ses-support-001',
                'invocation_id': 'inv-support-001',
                'message_id': 'msg-assistant-tool-use-001',
                'root_call_id': 'call-lookup-001',
            },
        },
    )
    tool_message = validate_message(
        {
            'message_id': 'msg-tool-lookup-001',
            'role': 'tool',
            'content': 'lookup_case returned priority=high',
            'metadata': {
                'tool_call_id': 'call-lookup-001',
                'tool_name': 'lookup_case',
            },
            'ts': '2026-07-03T15:00:00Z',
        },
    )
    outcome = validate_tool_outcome(
        {
            'call_id': 'call-lookup-001',
            'status': 'ok',
            'duration_ms': 42,
            'result': {'priority': 'high'},
        },
    )

    assert tool_message.metadata is not None
    assert tool_call.call_id == tool_message.metadata['tool_call_id']
    assert outcome.call_id == tool_call.call_id
