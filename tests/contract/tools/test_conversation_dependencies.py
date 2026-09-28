"""Conversation reuse is explicit and carries a source result, not model arguments."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.tools import ToolCall, ToolDependencyEdge, validate_tool_call


def test_dependency_reuse_requires_an_explicit_conversation_scope() -> None:
    """Existing dependencies remain fresh for each invocation."""
    ordinary = ToolDependencyEdge(tool_name='collect_name', arg_name='name')
    assert ordinary.model_dump().get('result_scope') == 'invocation'
    reusable = ToolDependencyEdge.model_validate(
        {'tool_name': 'collect_name', 'arg_name': 'name', 'result_scope': 'conversation'}
    )
    assert reusable.model_dump()['result_scope'] == 'conversation'
    with pytest.raises(ValidationError):
        ToolDependencyEdge.model_validate(
            {'tool_name': 'collect_name', 'arg_name': 'name', 'result_scope': 'global'}
        )


def test_retained_result_binding_is_separate_from_model_arguments() -> None:
    """Source thread, call, producer version, and value cross the typed boundary."""
    value: dict[str, Any] = {
        'call_id': 'new-call',
        'spec_ref': {'namespace': 'sdk', 'tool_id': 'summary', 'version': 'v1'},
        'arguments': {},
        'lineage': {'session_id': 'new-session', 'invocation_id': 'new-invocation'},
        'retained_dependencies': {
            'name': {
                'thread_id': 'thread-1',
                'source_session_id': 'prior-session',
                'source_call_id': 'prior-call',
                'producer': {'namespace': 'sdk', 'tool_id': 'collect_name', 'version': 'v1'},
                'result': {'name': 'Taylor'},
            }
        },
    }
    call = ToolCall.model_validate(value)
    validate_tool_call(value)
    assert call.arguments == {}
    assert call.model_dump()['retained_dependencies'] == value['retained_dependencies']
    del value['retained_dependencies']['name']['source_call_id']
    with pytest.raises(ValidationError):
        ToolCall.model_validate(value)
