"""Bounds and redaction rules for every value that reaches session-trace detail."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from maivn_contracts.events import (
    Event,
    SessionTrace,
    TraceNode,
    assemble_session_trace,
    project_trace_for_staff,
)

SESSION = 'ses-sanitize'
MAX_DEPTH = 5
MAX_ITEMS = 50
MAX_TEXT = 2_000


def _event(index: int, event_type: str, payload: dict[str, Any], **extra: object) -> Event:
    return Event.model_validate(
        {
            'event_id': f'evt-{index}',
            'ordinal': f'producer-sanitize-{index:06d}',
            'type': event_type,
            'session_id': SESSION,
            'root_event_id': 'evt-root',
            'trigger_chain_depth': 0,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'agent:invoke',
            'mode': 'hosted',
            'payload': payload,
            'ts': '2026-07-13T22:00:00Z',
            **extra,
        },
    )


def _tool_arguments(arguments: object) -> dict[str, Any]:
    """Run one tool call carrying these arguments and return the tool node's detail."""
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', {}),
            _event(
                2,
                'system_tool_start',
                {'tool_name': 'probe', 'tool_call': {'arguments': arguments}},
                correlation_id='call-1',
            ),
        ],
        session_id=SESSION,
    )
    (tool,) = trace.root.children
    return tool.detail


def _nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {'leaf': 'v'}
    for level in range(depth):
        value = {f'level_{level}': value}
    return value


def test_detail_nesting_is_truncated_at_the_depth_cap() -> None:
    """Values at depth five become a truncation marker; shallower values survive."""
    detail = _tool_arguments(_nested(MAX_DEPTH))
    node: Any = detail['arguments']
    for _ in range(MAX_DEPTH):
        (node,) = node.values()
    assert node == '[TRUNCATED]'

    shallow: Any = _tool_arguments(_nested(MAX_DEPTH - 2))['arguments']
    for _ in range(MAX_DEPTH - 2):
        (shallow,) = shallow.values()
    assert shallow == {'leaf': 'v'}


def test_detail_mappings_and_sequences_keep_only_the_first_fifty_items() -> None:
    """Mappings and lists are cut to fifty items in order; sets become lists."""
    arguments = {f'k{index:03d}': index for index in range(MAX_ITEMS + 5)}
    kept = _tool_arguments(arguments)['arguments']
    assert list(kept) == [f'k{index:03d}' for index in range(MAX_ITEMS)]
    assert _tool_arguments(arguments)['argument_names'] == sorted(arguments)

    listed = _tool_arguments({'items': list(range(MAX_ITEMS + 1))})['arguments']['items']
    assert listed == list(range(MAX_ITEMS))


def test_detail_text_is_cut_at_two_thousand_characters() -> None:
    """Long strings are truncated to the text cap; strings at the cap survive whole."""
    detail = _tool_arguments({'short': 'a' * MAX_TEXT, 'long': 'b' * (MAX_TEXT + 1)})['arguments']
    assert detail['short'] == 'a' * MAX_TEXT
    assert detail['long'] == 'b' * MAX_TEXT


@pytest.mark.parametrize(
    'key',
    [
        'API_KEY',
        'mailing_address',
        'Authorization',
        'chain_of_thought',
        'password_hint',
        'phone',
        'private_data_ref',
        'user_prompt',
        'reasoning_trace',
        'client_secret',
        'ssn',
        'system_message',
        'system_prompt',
        'refresh_token',
        'work_email',
    ],
)
def test_sensitive_key_parts_redact_values_case_insensitively(key: str) -> None:
    """Any key containing a sensitive part, in any case, has its value redacted."""
    detail = _tool_arguments({key: 'private-value', 'nested': {key: {'deep': 'x'}}})
    assert detail['arguments'][key] == '[REDACTED]'
    assert detail['arguments']['nested'][key] == '[REDACTED]'


def test_scalars_pass_through_and_other_objects_are_rendered_as_bounded_text() -> None:
    """JSON scalars stay typed; anything else is stringified within the text cap."""
    detail = _tool_arguments(
        {'flag': True, 'count': 3, 'ratio': 0.5, 'missing': None, 'tags': ['a', 'b']},
    )['arguments']
    assert detail == {'flag': True, 'count': 3, 'ratio': 0.5, 'missing': None, 'tags': ['a', 'b']}


def test_private_placeholders_in_detail_text_are_masked() -> None:
    """Every private-placeholder spelling is replaced before text reaches the trace."""
    detail = _tool_arguments(
        {
            'note': 'Ship to {_{customer_address}_} for {{customer_name}} via {_carrier_}.',
        },
    )
    rendered = detail['arguments']['note']
    for name in ('customer_address', 'customer_name', 'carrier'):
        assert name not in rendered
    assert rendered.startswith('Ship to ')


def test_tool_without_mapping_arguments_reports_only_its_type() -> None:
    """Non-mapping arguments or a missing tool call add nothing beyond the tool type."""
    assert _tool_arguments(['positional']) == {'tool_type': 'system'}
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', {}),
            _event(2, 'system_tool_start', {'tool_name': 'bare', 'tool_type': 'MCP'}),
        ],
        session_id=SESSION,
    )
    assert trace.root.children[0].detail == {'tool_type': 'mcp'}


def _shield(redaction: object) -> dict[str, Any]:
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', {}),
            _event(
                2,
                'enrichment',
                {'phase': 'message_redaction_applied', 'redaction': redaction},
            ),
        ],
        session_id=SESSION,
    )
    shield: TraceNode = trace.root.children[0]
    assert shield.kind == 'shield'
    return shield.detail


def test_shield_detail_keeps_counts_and_clean_key_names_only() -> None:
    """Counts must be non-negative integers; key names are trimmed, de-duplicated, sorted."""
    assert _shield(
        {'redacted_value_count': 2, 'inserted_keys': [' b ', 'a', 'a', '', 7, '  ']},
    ) == {
        'phase': 'message_redaction_applied',
        'redacted_value_count': 2,
        'redacted_keys': ['a', 'b'],
    }
    assert _shield({'redacted_value_count': -1, 'redacted_keys': 'not-a-list'}) == {
        'phase': 'message_redaction_applied',
    }
    assert _shield('not-a-mapping') == {'phase': 'message_redaction_applied'}


def _completed_tool_with_receipt(result: object, redacted_keys: object) -> TraceNode:
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', {}),
            _event(2, 'system_tool_start', {'tool_name': 'lookup'}, correlation_id='call-1'),
            _event(
                3,
                'system_tool_complete',
                {'tool_name': 'lookup', 'outcome': {'result': result}},
                correlation_id='call-1',
            ),
            _event(
                4,
                'enrichment',
                {
                    'phase': 'tool_result_redaction_applied',
                    'redaction': {'redacted_keys': redacted_keys},
                },
            ),
        ],
        session_id=SESSION,
    )
    return next(child for child in trace.root.children if child.kind == 'tool')


def test_redaction_receipt_redacts_keys_and_dotted_path_suffixes_inside_lists() -> None:
    """A receipt key matches a field by name or as the last segment of a dotted path."""
    tool = _completed_tool_with_receipt(
        {'rows': [{'account_no': 'A-1', 'label': 'ok'}], 'holder': {'name': 'Ada'}},
        ['account_no', 'holder.name'],
    )
    assert tool.detail['result'] == {
        'rows': [{'account_no': '[REDACTED]', 'label': 'ok'}],
        'holder': {'name': '[REDACTED]'},
    }


@pytest.mark.parametrize('keys', [[], ['  '], [3], 'account_no'])
def test_redaction_receipt_without_usable_keys_changes_nothing(keys: object) -> None:
    """Blank, non-string or non-list receipt keys leave the tool detail intact."""
    tool = _completed_tool_with_receipt({'account_no': 'A-1'}, keys)
    assert tool.detail['result'] == {'account_no': 'A-1'}


def test_failed_tool_records_only_its_sanitized_error() -> None:
    """A failed tool keeps a sanitized error and never a result."""
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', {}),
            _event(2, 'system_tool_start', {'tool_name': 'lookup'}, correlation_id='call-1'),
            _event(
                3,
                'system_tool_error',
                {
                    'tool_name': 'lookup',
                    'error': {'message': 'boom', 'api_key': 'k'},
                    'result': 'ignored',
                },
                correlation_id='call-1',
            ),
        ],
        session_id=SESSION,
    )
    (tool,) = trace.root.children
    assert tool.status == 'failed'
    assert tool.detail['error'] == {'message': 'boom', 'api_key': '[REDACTED]'}
    assert 'result' not in tool.detail


def test_detail_renders_non_json_values_as_bounded_text() -> None:
    """A value JSON cannot carry is rendered with str() and cut at the text cap."""
    moment = datetime(2026, 7, 13, 22, 0, tzinfo=timezone.utc)
    detail = _tool_arguments({'when': moment})['arguments']
    assert detail['when'] == str(moment)


def test_list_nesting_counts_toward_the_depth_cap() -> None:
    """Nested lists are truncated at the same depth as nested mappings."""
    value: object = 'leaf'
    for _ in range(MAX_DEPTH):
        value = [value]
    node: Any = _tool_arguments({'nested': value})['arguments']['nested']
    for _ in range(MAX_DEPTH - 1):
        (node,) = node
    assert node == '[TRUNCATED]'


def test_long_non_json_values_are_cut_at_the_text_cap() -> None:
    """Stringified values obey the same two-thousand-character cap as strings."""
    detail = _tool_arguments({'amount': Decimal('9' * (MAX_TEXT + 10))})['arguments']
    assert detail['amount'] == '9' * MAX_TEXT


TENANT_VALUE_KEYS = (
    'arguments',
    'error',
    'internal_narration',
    'output',
    'prompt',
    'result',
    'transcript',
)


def test_staff_projection_drops_every_tenant_value_key_at_every_depth() -> None:
    """Each caller-supplied detail key is removed from every node; other detail stays."""
    tenant_detail = {key: f'tenant {key}' for key in TENANT_VALUE_KEYS}
    child = TraceNode(
        node_id='tool--1',
        kind='tool',
        name='lookup',
        status='completed',
        detail={**tenant_detail, 'tool_type': 'func'},
    )
    trace = SessionTrace(
        session_id=SESSION,
        root=TraceNode(
            node_id='run--1',
            kind='run',
            name='Run',
            status='completed',
            detail={**tenant_detail, 'agent_id': 'analyst'},
            children=[child],
        ),
    )

    staff = project_trace_for_staff(trace)

    assert staff.root.detail == {'agent_id': 'analyst'}
    assert staff.root.children[0].detail == {'tool_type': 'func'}
    assert trace.root.detail == {**tenant_detail, 'agent_id': 'analyst'}


def test_repeated_private_placeholders_are_listed_once_in_order() -> None:
    """Each private key appears once in the public key list, in first-seen order."""
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', {}),
            _event(
                2,
                'final',
                {
                    'trace_message': {
                        'role': 'assistant',
                        'content': '{_{b}_} then {_{a}_} then {_{b}_} again.',
                    },
                    'trace_public_response': True,
                },
            ),
        ],
        session_id=SESSION,
    )
    exchange = next(child for child in trace.root.children if child.kind == 'model')
    assert exchange.detail['response'] == '[PRIVATE] then [PRIVATE] then [PRIVATE] again.'
    assert exchange.detail['response_private_keys'] == ['b', 'a']
