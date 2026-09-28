"""Unit tests for the curated session-trace assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from maivn_contracts.events import (
    Event,
    assemble_session_trace,
    project_event_type,
    project_trace_for_staff,
)

if TYPE_CHECKING:
    from maivn_contracts.events.trace import TraceNode

_PARENT = 'ses-trace-parent'
_PARENT_INPUT_TOKENS = 100
_CHILD_OUTPUT_TOKENS = 5
_TOOL_LATENCY_MS = 250
_FLAKY_LATENCY_MS = 90
_MODEL_RUNTIME_MS = 3_000
_MODEL_TTFT_MS = 1_000
_CHILD = 'ses-trace-child'
_DESCENDANT_CAP_FOR_TEST = 2
_MEMORY_HIT_COUNT = 4
_MEMORY_KIND_COUNT = 2
_ANSWERED_PAUSE_MS = 20_000
_UNANSWERED_PAUSE_MS = 30_000


def _event(  # noqa: PLR0913 - event construction mirrors the wire record.
    index: int,
    event_type: str,
    *,
    session_id: str = _PARENT,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    latency_ms: int | None = None,
    parent_session_id: str | None = None,
    ts: str = '2026-07-13T22:00:00Z',
    job_depth: int | None = None,
    job_index: int = 0,
) -> Event:
    return Event.model_validate(
        {
            'event_id': f'evt-{index}',
            'ordinal': f'producer-test-{index:06d}',
            'type': event_type,
            'session_id': session_id,
            'root_event_id': 'evt-root',
            'parent_session_id': parent_session_id,
            'trigger_chain_depth': 0,
            'job_depth': (1 if parent_session_id else 0) if job_depth is None else job_depth,
            'job_index': job_index,
            'actor': 'agent:invoke',
            'mode': 'hosted',
            'correlation_id': correlation_id,
            'latency_ms': latency_ms,
            'payload': payload or {},
            'ts': ts,
        },
    )


def test_trace_tree_pairs_tools_nests_children_and_stays_curated() -> None:
    """The tree carries runs, tools, and aspects with timings - and nothing internal."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'run_config': {'agent_id': 'analyst', 'user_id': 'u', 'thread_id': 't'}},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(2, 'planning', ts='2026-07-13T22:00:01Z'),
        _event(3, 'searching_tools', ts='2026-07-13T22:00:02Z'),
        _event(
            4,
            'system_tool_start',
            payload={
                'tool_name': 'lookup_case',
                'tool_call': {'arguments': {'case_id': 'case-1', 'secret_value': 'x'}},
            },
            correlation_id='call-1',
            ts='2026-07-13T22:00:03Z',
        ),
        _event(
            5,
            'system_tool_complete',
            payload={'tool_name': 'lookup_case'},
            correlation_id='call-1',
            latency_ms=250,
            ts='2026-07-13T22:00:04Z',
        ),
        _event(
            6,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'run_config': {'agent_id': 'researcher', 'user_id': 'u', 'thread_id': 't'}},
            ts='2026-07-13T22:00:05Z',
        ),
        _event(
            7,
            'final',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'usage': {'input_tokens': 10, 'output_tokens': 5}},
            ts='2026-07-13T22:00:06Z',
        ),
        _event(
            8,
            'final',
            payload={'usage': {'input_tokens': 100, 'output_tokens': 40}},
            ts='2026-07-13T22:00:07Z',
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    root = trace.root
    assert root.kind == 'run'
    assert root.name == 'analyst'
    assert root.status == 'completed'
    assert root.tokens is not None
    assert root.tokens.input_tokens == _PARENT_INPUT_TOKENS

    kinds = [child.kind for child in root.children]
    assert kinds == ['working', 'tool', 'run']

    working = root.children[0]
    assert working.started_at == '2026-07-13T22:00:01Z'
    assert working.ended_at == '2026-07-13T22:00:02Z'

    tool = root.children[1]
    assert tool.name == 'lookup_case'
    assert tool.status == 'completed'
    assert tool.duration_ms == _TOOL_LATENCY_MS
    # Curation: useful inputs survive, while sensitive fields never expose values.
    assert tool.detail == {
        'tool_type': 'system',
        'argument_names': ['case_id', 'secret_value'],
        'arguments': {'case_id': 'case-1', 'secret_value': '[REDACTED]'},
    }
    assert 'x' not in str(tool.detail)

    child_run = root.children[2]
    assert child_run.name == 'researcher'
    assert child_run.status == 'completed'
    assert child_run.tokens is not None
    assert child_run.tokens.output_tokens == _CHILD_OUTPUT_TOKENS


def test_trace_tool_detail_preserves_public_tool_type_for_visual_identity() -> None:
    """Tool trace nodes retain their public type for consistent UI color mapping."""
    events = [
        _event(
            1,
            'system_tool_start',
            payload={'tool_name': 'market_data', 'tool_type': 'mcp'},
            correlation_id='call-mcp',
        ),
        _event(
            2,
            'system_tool_complete',
            payload={'tool_name': 'market_data'},
            correlation_id='call-mcp',
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert trace.root.children[0].detail['tool_type'] == 'mcp'


def test_enrichment_phases_remain_distinct_execution_stages() -> None:
    """Studio sees the execution story instead of one generic Working row."""
    events = [
        _event(1, 'assignment_received'),
        _event(2, 'enrichment', payload={'phase': 'planning'}),
        _event(3, 'enrichment', payload={'phase': 'searching_tools'}),
        _event(4, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert [child.name for child in trace.root.children] == [
        'Planning execution',
        'Finding tools',
    ]
    assert [child.detail['phase'] for child in trace.root.children] == [
        'planning',
        'searching_tools',
    ]


def test_open_enrichment_phases_fall_back_to_the_canonical_enrichment_projection() -> None:
    """A schema-valid new phase cannot make the entire user trace unavailable."""
    events = [
        _event(1, 'assignment_received'),
        _event(2, 'enrichment', payload={'phase': 'plan_warning'}),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert trace.root.children[0].kind == 'working'
    assert trace.root.children[0].name == 'Working'
    assert trace.root.children[0].detail['phase'] == 'plan_warning'
    with pytest.raises(KeyError, match='No trace projection mapping'):
        project_event_type('not_a_canonical_event_type', 'trace')


def test_routing_receipts_do_not_turn_unmeasured_gaps_into_routing_duration() -> None:
    """Separate route decisions and usage receipts are instantaneous observations."""
    events = [
        _event(1, 'assignment_received'),
        _event(2, 'model_routing', payload={'mode': 'auto', 'model': 'first-model'}),
        _event(
            3,
            'model_routing',
            payload={'mode': 'hop_usage', 'model': 'second-model'},
            ts='2026-07-13T22:00:11Z',
        ),
        _event(4, 'final', ts='2026-07-13T22:00:12Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)
    routes = [child for child in trace.root.children if child.kind == 'routing']

    assert [route.detail['model'] for route in routes] == ['first-model', 'second-model']
    assert [route.name for route in routes] == [
        'Routed to first-model',
        'Usage recorded for second-model',
    ]
    assert all(route.started_at == route.ended_at for route in routes)


def test_planning_trace_preserves_public_setting_and_reason() -> None:
    """Planning decisions remain reviewable through the closed trace projection."""
    detail = {
        'mode': 'auto',
        'model': 'gpt-5.6-sol',
        'planning_requested': 'auto',
        'planning_tier': 'deep',
        'planning_auto': True,
        'planning_reason': 'Dependent steps with competing constraints',
    }
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received'),
            _event(2, 'model_routing', payload=detail),
            _event(3, 'final'),
        ],
        session_id=_PARENT,
    )
    route = next(child for child in trace.root.children if child.kind == 'routing')
    for key, value in detail.items():
        assert route.detail[key] == value


def test_memory_aspect_surfaces_nested_retrieval_counters() -> None:
    """A memory node explains what it recalled instead of being a bare marker.

    Memory-family events nest their counters under `memory`, so a top-level-only
    sweep left 'Memory retrieved' carrying nothing but its own phase - the one
    aspect in the tree that told the reader no numbers at all.
    """
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'enrichment',
            payload={
                'phase': 'memory_retrieved',
                'message': 'Retrieved 4 memory hits',
                'memory': {
                    'mode': 'retrieve',
                    'hit_count': 4,
                    'skill_count': 2,
                    'insight_count': 2,
                    'resource_count': 0,
                },
            },
        ),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    memory_node = next(child for child in trace.root.children if child.kind == 'memory')
    assert memory_node.name == 'Memory retrieved'
    assert memory_node.detail['phase'] == 'memory_retrieved'
    assert memory_node.detail['mode'] == 'retrieve'
    assert memory_node.detail['hit_count'] == _MEMORY_HIT_COUNT
    assert memory_node.detail['skill_count'] == _MEMORY_KIND_COUNT
    assert memory_node.detail['insight_count'] == _MEMORY_KIND_COUNT
    assert memory_node.detail['resource_count'] == 0


def test_document_analysis_selection_projects_as_value_free_resource_trace() -> None:
    """Expose strategy counters while keeping source content out of the trace."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'enrichment',
            payload={
                'phase': 'document_analysis_selected',
                'message': 'Selected bounded document-analysis strategy',
                'memory': {
                    'mode': 'focused_navigation',
                    'reason': 'focused_intent',
                    'resource_count': 1,
                    'estimated_document_tokens': 42_000,
                    'estimated_protected_input_tokens': 1_200,
                    'context_ratio': 0.25,
                    'private_document_text': 'quarterly plan secret',
                },
            },
        ),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    resource_node = next(child for child in trace.root.children if child.kind == 'resource')
    assert resource_node.name == 'Focused document navigation'
    assert resource_node.detail == {
        'phase': 'document_analysis_selected',
        'mode': 'focused_navigation',
        'reason': 'focused_intent',
        'resource_count': 1,
        'estimated_document_tokens': 42_000,
        'estimated_protected_input_tokens': 1_200,
        'context_ratio': 0.25,
    }
    assert 'quarterly plan secret' not in resource_node.model_dump_json()


def test_document_detail_keys_do_not_widen_other_memory_trace_events() -> None:
    """Document-only fields cannot expose same-named values from ordinary memory events."""
    private_reason = 'private customer-specific retrieval rationale'
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'enrichment',
            payload={
                'phase': 'memory_retrieved',
                'message': 'Retrieved memory',
                'memory': {
                    'skill_count': 1,
                    'insight_count': 0,
                    'resource_count': 0,
                    'reason': private_reason,
                },
            },
        ),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    memory_node = next(child for child in trace.root.children if child.kind == 'memory')
    assert memory_node.detail == {
        'phase': 'memory_retrieved',
        'skill_count': 1,
        'insight_count': 0,
        'resource_count': 0,
    }
    assert private_reason not in memory_node.model_dump_json()


def test_document_evidence_coverage_projects_bounded_counters_without_source_identity() -> None:
    """Studio receives honest aggregate coverage, never source names or evidence text."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'enrichment',
            payload={
                'phase': 'document_evidence_coverage',
                'message': 'Assembled bounded document-evidence coverage',
                'memory': {
                    'expected_resource_count': 7,
                    'packet_count': 7,
                    'complete_resource_count': 6,
                    'failed_resource_count': 0,
                    'unavailable_resource_count': 0,
                    'uncertain_resource_count': 1,
                    'partial_resource_count': 0,
                    'no_evidence_resource_count': 0,
                    'gap_resource_count': 1,
                    'missing_packet_count': 0,
                    'finding_count': 19,
                    'gap_count': 1,
                    'covered_page_count': 43,
                    'covered_section_count': 22,
                    'coverage_complete': False,
                    'model_input_tokens': 12_300,
                    'model_output_tokens': 2_100,
                    'navigation_calls': 31,
                    'elapsed_ms': 9_400,
                    'budget_exhausted': True,
                    'resource_id': 'private-resource-id',
                    'evidence_excerpt': 'private source content',
                },
            },
        ),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    resource_node = next(child for child in trace.root.children if child.kind == 'resource')
    assert resource_node.name == 'Document coverage incomplete'
    assert resource_node.detail == {
        'phase': 'document_evidence_coverage',
        'expected_resource_count': 7,
        'packet_count': 7,
        'complete_resource_count': 6,
        'failed_resource_count': 0,
        'unavailable_resource_count': 0,
        'uncertain_resource_count': 1,
        'partial_resource_count': 0,
        'no_evidence_resource_count': 0,
        'gap_resource_count': 1,
        'missing_packet_count': 0,
        'finding_count': 19,
        'gap_count': 1,
        'covered_page_count': 43,
        'covered_section_count': 22,
        'coverage_complete': False,
        'model_input_tokens': 12_300,
        'model_output_tokens': 2_100,
        'navigation_calls': 31,
        'elapsed_ms': 9_400,
        'budget_exhausted': True,
    }
    serialized = resource_node.model_dump_json()
    assert 'private-resource-id' not in serialized
    assert 'private source content' not in serialized


def test_memory_aspect_keeps_recalled_content_out_of_the_trace() -> None:
    """Counters may cross to staff; caller-supplied recall text may not."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'enrichment',
            payload={
                'phase': 'memory_retrieved',
                'message': 'Retrieved 1 memory hit',
                'memory': {
                    'mode': 'retrieve',
                    'hit_count': 1,
                    'skills': [{'name': 'Quarterly close', 'content': 'Owner is Dana Reyes'}],
                    'insights': [{'content': 'Budget cap is 120000'}],
                    'transcript': 'prior briefing text',
                },
            },
        ),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    memory_node = next(child for child in trace.root.children if child.kind == 'memory')
    assert memory_node.detail['hit_count'] == 1
    assert 'skills' not in memory_node.detail
    assert 'insights' not in memory_node.detail
    assert 'transcript' not in memory_node.detail
    assert 'Dana Reyes' not in str(memory_node.detail)
    assert '120000' not in str(memory_node.detail)


def test_hook_firings_enter_the_tree_in_execution_order() -> None:
    """A hook reads as a step in the run, positioned against what it fired around."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'hook_fired',
            payload={
                'name': 'validate_input',
                'stage': 'before',
                'status': 'ok',
                'target_type': 'tool',
            },
        ),
        _event(3, 'system_tool_start', payload={'tool_name': 'scan'}, correlation_id='c1'),
        _event(4, 'system_tool_complete', payload={'tool_name': 'scan'}, correlation_id='c1'),
        _event(
            5,
            'hook_fired',
            payload={
                'name': 'audit_result',
                'stage': 'after',
                'status': 'ok',
                'target_type': 'tool',
            },
        ),
        _event(6, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)
    names = [child.name for child in trace.root.children]

    # Hooks are siblings, not children: nesting a before-hook under the tool
    # would claim it ran inside the thing it preceded.
    assert names.index('validate_input') < names.index('scan')
    assert names.index('scan') < names.index('audit_result')
    assert [c.kind for c in trace.root.children if c.name == 'validate_input'] == ['hook']


def test_hook_detail_is_structural_and_carries_no_caller_values() -> None:
    """Hook nodes describe which hook ran, never what flowed through it."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'hook_fired',
            payload={
                'name': 'redact_pii',
                'stage': 'after',
                'status': 'failed',
                'target_type': 'model',
                'arguments': {'ssn': '123-45-6789'},
                'result': 'Dana Reyes',
                'prompt': 'internal instruction text',
            },
        ),
        _event(3, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)
    hook = next(child for child in trace.root.children if child.kind == 'hook')

    assert hook.detail == {
        'name': 'redact_pii',
        'stage': 'after',
        'status': 'failed',
        'target_type': 'model',
    }
    assert '123-45-6789' not in str(hook.detail)
    assert 'Dana Reyes' not in str(hook.detail)


def test_a_failed_hook_is_a_failed_node_not_a_completed_one() -> None:
    """Node status must not claim success when the aspect reported failure.

    Aspects were hardcoded 'completed'. A hook that raised carried
    status='failed' in its detail while the node said completed, so every
    consumer reading node status skipped it.
    """
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'hook_fired',
            payload={'name': 'guard', 'stage': 'before', 'status': 'failed', 'target_type': 'tool'},
        ),
        _event(
            3,
            'hook_fired',
            payload={'name': 'audit', 'stage': 'after', 'status': 'ok', 'target_type': 'tool'},
        ),
        _event(4, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)
    hooks = {c.name: c.status for c in trace.root.children if c.kind == 'hook'}

    assert hooks['guard'] == 'failed'
    assert hooks['audit'] == 'completed'


def test_failed_and_skipped_triggers_explain_a_run_that_never_happened() -> None:
    """Absence is the hardest thing to debug, so the trace says why."""
    failed = assemble_session_trace(
        [_event(1, 'assignment_received'), _event(2, 'trigger.failed'), _event(3, 'final')],
        session_id=_PARENT,
    )
    skipped = assemble_session_trace(
        [_event(1, 'assignment_received'), _event(2, 'trigger.skipped'), _event(3, 'final')],
        session_id=_PARENT,
    )

    failed_node = next(c for c in failed.root.children if c.kind == 'trigger')
    skipped_node = next(c for c in skipped.root.children if c.kind == 'trigger')

    assert (failed_node.name, failed_node.status) == ('Trigger failed', 'failed')
    assert (skipped_node.name, skipped_node.status) == ('Trigger skipped', 'cancelled')


def test_structural_trace_gets_public_stages_without_internal_narration() -> None:
    """Sparse runtimes still explain the black-box lifecycle deterministically."""
    events = [
        _event(1, 'assignment_received'),
        _event(2, 'model_routing', payload={'mode': 'auto', 'model': 'tier-model'}),
        _event(
            3,
            'system_tool_start',
            payload={'tool_name': 'work'},
            correlation_id='call-stage',
        ),
        _event(
            4,
            'system_tool_complete',
            payload={'tool_name': 'work'},
            correlation_id='call-stage',
        ),
        _event(5, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert [child.name for child in trace.root.children] == [
        'Evaluating request',
        'Routed to tier-model',
        'Running actions',
        'work',
        'Finalizing run',
    ]
    assert all(
        child.detail.get('source') == 'structural'
        for child in trace.root.children
        if child.kind == 'working'
    )


def test_tool_completion_adds_sanitized_result_and_redaction_field_names() -> None:
    """Trace detail is diagnostic without leaking protected values."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'system_tool_start',
            payload={
                'tool_name': 'inspect_vehicle',
                'tool_call': {'arguments': {'vehicle_id': 'V-12'}},
            },
            correlation_id='call-safe',
        ),
        _event(
            3,
            'system_tool_complete',
            payload={
                'tool_name': 'inspect_vehicle',
                'outcome': {
                    'result': {
                        'status': 'healthy',
                        'api_key': 'must-not-appear',
                    }
                },
            },
            correlation_id='call-safe',
        ),
        _event(
            4,
            'enrichment',
            payload={
                'phase': 'tool_result_redaction_applied',
                'redaction': {
                    'redacted_value_count': 1,
                    'redacted_keys': ['sensor_bus_id'],
                },
            },
        ),
        _event(5, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    tool, shield = trace.root.children
    assert tool.detail['result'] == {
        'status': 'healthy',
        'api_key': '[REDACTED]',
    }
    assert 'must-not-appear' not in trace.model_dump_json()
    assert shield.name == 'Redacting tool result'
    assert shield.detail == {
        'phase': 'tool_result_redaction_applied',
        'redacted_value_count': 1,
        'redacted_keys': ['sensor_bus_id'],
    }


def test_trace_model_exchange_shows_public_prompt_response_and_stream_metrics() -> None:
    """Developer-visible exchanges survive while internal/system prompts stay absent."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={
                'trace_messages': [
                    {'role': 'system', 'content': 'Internal platform prompt'},
                    {'role': 'user', 'content': 'Inspect the vehicle'},
                ]
            },
        ),
        _event(
            2,
            'status_message_chunk',
            payload={
                'stage': 'model_stream',
                'trace_public_response': True,
                'content_delta': 'Vehicle ',
                'chunk_index': 0,
            },
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'status_message_chunk',
            payload={
                'stage': 'model_stream',
                'trace_public_response': True,
                'content_delta': 'healthy.',
                'chunk_index': 1,
            },
            ts='2026-07-13T22:00:02Z',
        ),
        _event(
            4,
            'final',
            payload={
                'message': {'role': 'assistant', 'content': 'Vehicle V-12 healthy.'},
                'trace_message': {
                    'role': 'assistant',
                    'content': 'Vehicle {_{vehicle_id}_} healthy.',
                },
                'trace_public_response': True,
                'usage': {'input_tokens': 40, 'output_tokens': 3},
            },
            ts='2026-07-13T22:00:03Z',
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    exchange = next(child for child in trace.root.children if child.kind == 'model')
    assert exchange.name == 'Model exchange'
    assert exchange.detail == {
        'prompt': 'Inspect the vehicle',
        'response': 'Vehicle [PRIVATE] healthy.',
        'response_private_keys': ['vehicle_id'],
        'chunk_count': 2,
        'streaming': True,
        'delivery': 'live stream',
    }
    assert exchange.started_at == '2026-07-13T22:00:01Z'
    assert exchange.ended_at == '2026-07-13T22:00:03Z'
    assert 'Internal platform prompt' not in trace.model_dump_json()
    assert '{_{vehicle_id}_}' not in trace.model_dump_json()


def test_trace_omits_internal_model_prompts_and_structured_working_output() -> None:
    """Delegated assignments and unapproved model payloads never enter the public trace."""
    raw_assignment = 'Use proprietary assignment scoring and hidden rubric delta-7.'
    raw_working_output = '{"internal_plan":["route","repair"],"score":0.97}'
    events = [
        _event(
            1,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'trace_messages': [{'role': 'user', 'content': raw_assignment}]},
        ),
        _event(
            2,
            'status_message_chunk',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={
                'stage': 'model_stream',
                'content_delta': raw_working_output,
                'chunk_index': 0,
            },
        ),
        _event(
            3,
            'final',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'message': {'role': 'assistant', 'content': raw_working_output}},
        ),
    ]

    serialized = assemble_session_trace(events, session_id=_CHILD).model_dump_json()

    assert raw_assignment not in serialized
    assert raw_working_output not in serialized


def test_delegated_model_call_shows_request_context_but_not_generated_assignment() -> None:
    """Child model input stays useful without disclosing proprietary delegation."""
    raw_assignment = 'Use proprietary assignment scoring and hidden rubric delta-7.'
    events = [
        _event(
            1,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={
                'trace_messages': [{'role': 'user', 'content': 'Create a financial plan'}],
                'trace_input_scope': 'request_context',
                'protected_internal_input': True,
                'generated_assignment': raw_assignment,
            },
        ),
        _event(
            2,
            'model_routing',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'mode': 'auto', 'model': 'served-model'},
        ),
        _event(
            3,
            'progress_update',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'stage': 'model_call_started', 'turn_index': 0},
        ),
        _event(
            4,
            'progress_update',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={
                'stage': 'model_call_completed',
                'turn_index': 0,
                'usage': {'input_tokens': 20, 'output_tokens': 4},
            },
        ),
        _event(
            5,
            'final',
            session_id=_CHILD,
            parent_session_id=_PARENT,
        ),
    ]

    trace = assemble_session_trace(events, session_id=_CHILD)
    exchange = next(child for child in trace.root.children if child.kind == 'model')

    assert exchange.detail['prompt'] == 'Create a financial plan'
    assert exchange.detail['input_scope'] == 'request_context'
    assert exchange.detail['protected_internal_input'] is True
    assert raw_assignment not in trace.model_dump_json()


def test_model_call_tokens_do_not_sum_cumulative_run_usage_repeatedly() -> None:
    """Three completed calls partition cumulative counters, including cache token counters."""
    events = [_event(1, 'assignment_received')]
    for turn, count in enumerate((10, 30, 60)):
        events.extend(
            [
                _event(
                    2 + turn * 2,
                    'progress_update',
                    payload={
                        'stage': 'model_call_started',
                        'turn_index': turn,
                    },
                ),
                _event(
                    3 + turn * 2,
                    'progress_update',
                    payload={
                        'stage': 'model_call_completed',
                        'turn_index': turn,
                        'usage': {
                            'input_tokens': count,
                            'output_tokens': count // 10,
                            'cache_read_input_tokens': count * 2,
                            'cache_creation_input_tokens': count * 3,
                        },
                    },
                ),
            ]
        )
    trace = assemble_session_trace(events, session_id=_PARENT)
    calls = [child for child in trace.root.children if child.kind == 'model']
    assert [call.tokens.input_tokens for call in calls if call.tokens] == [10, 20, 30]
    assert [call.tokens.output_tokens for call in calls if call.tokens] == [1, 2, 3]
    assert [call.tokens.cache_read_tokens for call in calls if call.tokens] == [20, 40, 60]
    assert [call.tokens.cache_creation_tokens for call in calls if call.tokens] == [30, 60, 90]


@pytest.mark.parametrize('ordinals', [(0, 1), (0, 0, 1)])
def test_identified_provider_calls_keep_separate_usage_within_one_loop_turn(
    ordinals: tuple[int, ...],
) -> None:
    """Repair requests share a loop turn but have distinct measured provider calls."""
    events = [_event(1, 'assignment_received')]
    for index, ordinal in enumerate(ordinals):
        count = (index + 1) * 10
        identity = {
            'turn_index': 0,
            'model_call_id': f'provider-{index}',
            'model_call_ordinal': ordinal,
            'model': 'intended-model',
        }
        events.extend(
            [
                _event(
                    2 + index * 2,
                    'progress_update',
                    payload={
                        **identity,
                        'stage': 'model_call_started',
                    },
                ),
                _event(
                    3 + index * 2,
                    'progress_update',
                    payload={
                        **identity,
                        'stage': 'model_call_completed',
                        'model': 'served-model',
                        'usage': {'input_tokens': 999},
                        'call_usage': {'input_tokens': count, 'output_tokens': 1},
                    },
                ),
            ]
        )
    trace = assemble_session_trace(events, session_id=_PARENT)
    calls = [child for child in trace.root.children if child.kind == 'model']
    assert [call.name for call in calls] == [f'Model call {i + 1}' for i in range(len(ordinals))]
    assert [call.tokens.input_tokens for call in calls if call.tokens] == [
        (i + 1) * 10 for i in range(len(ordinals))
    ]
    assert all(call.detail['model'] == 'served-model' for call in calls)
    assert len({call.node_id for call in calls}) == len(calls)


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_identified_failed_call_keeps_status_and_unknown_usage(status: str) -> None:
    """A failed request cannot borrow cumulative tokens or masquerade as completed."""
    identity = {'turn_index': 0, 'model_call_id': 'failed-provider'}
    events = [
        _event(1, 'assignment_received'),
        _event(2, 'progress_update', payload={**identity, 'stage': 'model_call_started'}),
        _event(
            3,
            'progress_update',
            latency_ms=17,
            payload={
                **identity,
                'stage': 'model_call_completed',
                'model_call_status': status,
                'model_error_code': f'model_call_{status}',
                'usage': {'input_tokens': 999},
            },
        ),
    ]
    trace = assemble_session_trace(events, session_id=_PARENT)
    call = next(child for child in trace.root.children if child.kind == 'model')
    assert call.status == status
    assert call.tokens is None
    assert call.duration_ms == events[-1].latency_ms
    assert call.detail['error_code'] == f'model_call_{status}'


def test_model_call_usage_is_unknown_when_its_baseline_is_missing_or_regresses() -> None:
    """Partial or inconsistent counters must not manufacture a per-call total."""
    for snapshots in (((2, 60),), ((0, 10), (2, 60)), ((0, 10), (1, 5))):
        events = [_event(1, 'assignment_received')]
        events.extend(
            _event(
                index + 2,
                'progress_update',
                payload={
                    'stage': 'model_call_completed',
                    'turn_index': turn,
                    'usage': {'input_tokens': count},
                },
            )
            for index, (turn, count) in enumerate(snapshots)
        )
        trace = assemble_session_trace(events, session_id=_PARENT)
        calls = [child for child in trace.root.children if child.kind == 'model']
        assert calls[-1].tokens is None


def test_nested_model_usage_keeps_a_separate_cumulative_baseline() -> None:
    """Interleaved parent and child lifecycle events never subtract each other's counters."""
    events = [
        _event(1, 'assignment_received'),
        _event(2, 'assignment_received', session_id=_CHILD, parent_session_id=_PARENT),
    ]
    for index, (session, turn, count) in enumerate(
        ((_PARENT, 0, 10), (_CHILD, 0, 100), (_PARENT, 1, 30), (_CHILD, 1, 150))
    ):
        events.append(
            _event(
                index + 3,
                'progress_update',
                session_id=session,
                parent_session_id=_PARENT if session == _CHILD else None,
                payload={
                    'stage': 'model_call_completed',
                    'turn_index': turn,
                    'usage': {'input_tokens': count},
                },
            )
        )
    trace = assemble_session_trace(events, session_id=_PARENT)
    child_run = next(child for child in trace.root.children if child.kind == 'run')
    for run, expected in ((trace.root, [10, 20]), (child_run, [100, 50])):
        assert [
            child.tokens.input_tokens
            for child in run.children
            if child.kind == 'model' and child.tokens
        ] == expected


def test_trace_model_exchange_uses_provider_lifecycle_for_runtime_and_ttft() -> None:
    """Model duration covers the provider call, not the near-instant routing decision."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'trace_messages': [{'role': 'user', 'content': 'Inspect it'}]},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'progress_update',
            payload={'stage': 'model_call_started', 'turn_index': 0},
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'status_message_chunk',
            payload={
                'stage': 'model_stream',
                'trace_public_response': True,
                'content_delta': 'Ready',
            },
            ts='2026-07-13T22:00:02Z',
        ),
        _event(
            4,
            'progress_update',
            payload={
                'stage': 'model_call_completed',
                'turn_index': 0,
                'usage': {'input_tokens': 20, 'output_tokens': 4},
            },
            ts='2026-07-13T22:00:04Z',
        ),
        _event(
            5,
            'final',
            payload={
                'trace_message': {'role': 'assistant', 'content': 'Ready'},
                'trace_public_response': True,
            },
            ts='2026-07-13T22:00:05Z',
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    exchange = next(child for child in trace.root.children if child.kind == 'model')
    assert exchange.started_at == '2026-07-13T22:00:01Z'
    assert exchange.ended_at == '2026-07-13T22:00:04Z'
    assert exchange.duration_ms == _MODEL_RUNTIME_MS
    assert exchange.detail['time_to_first_token_ms'] == _MODEL_TTFT_MS
    assert exchange.tokens is not None
    assert exchange.tokens.model_dump() == {
        'input_tokens': 20,
        'output_tokens': 4,
        'cache_read_tokens': 0,
        'cache_creation_tokens': 0,
    }


def test_trace_model_call_inherits_the_selected_public_model() -> None:
    """A model span identifies the routed model without exposing routing internals."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'trace_messages': [{'role': 'user', 'content': 'Inspect it'}]},
        ),
        _event(
            2,
            'model_routing',
            payload={'mode': 'auto', 'model': 'served-model'},
        ),
        _event(
            3,
            'progress_update',
            payload={'stage': 'model_call_started', 'turn_index': 0},
        ),
        _event(
            4,
            'progress_update',
            payload={
                'stage': 'model_call_completed',
                'turn_index': 0,
                'usage': {'input_tokens': 20, 'output_tokens': 4},
            },
        ),
        _event(5, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    exchange = next(child for child in trace.root.children if child.kind == 'model')
    assert exchange.detail['model'] == 'served-model'


def test_child_trace_orders_routing_before_model_call_by_event_time() -> None:
    """Delayed cross-session delivery cannot invert the public execution story."""
    events = [
        _event(1, 'assignment_received', ts='2026-07-13T22:00:00Z'),
        _event(
            2,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'progress_update',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'stage': 'model_call_started', 'turn_index': 0},
            ts='2026-07-13T22:00:03Z',
        ),
        _event(
            4,
            'model_routing',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'mode': 'auto', 'model': 'served-model'},
            ts='2026-07-13T22:00:02Z',
        ),
        _event(
            5,
            'final',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            ts='2026-07-13T22:00:04Z',
        ),
        _event(6, 'final', ts='2026-07-13T22:00:05Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    child = next(node for node in trace.root.children if node.kind == 'run')
    assert [node.kind for node in child.children] == [
        'working',
        'routing',
        'model',
        'working',
    ]


def test_routing_precedes_its_model_call_when_both_share_one_timestamp() -> None:
    """A tie must not expose where the model placeholder happened to be appended.

    Routing and model-call-started are emitted back to back, so they land on the
    same millisecond regularly in real runs. Ordering by start time alone cannot
    separate them, and the model node is created before the routing node folds -
    so the trace rendered a model call above the routing decision that produced
    it, which reads as the model running before anything chose it.
    """
    shared = '2026-07-13T22:00:03Z'
    events = [
        # A run that carries its prompt gets a model node at assignment time,
        # before anything has routed. That placeholder is the node the tie
        # later exposes; without it the model node is created after routing and
        # the order looks right whether or not the bug is present.
        _event(
            1,
            'assignment_received',
            payload={
                'stage': 'session_started',
                'trace_messages': [{'role': 'user', 'content': 'produce the report'}],
            },
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'model_routing',
            payload={'mode': 'auto', 'model': 'planning-model'},
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'system_tool_start',
            payload={'tool_name': 'leaf', 'correlation_id': 'c1'},
            ts='2026-07-13T22:00:02Z',
        ),
        # The chunk carries turn_index, which is what puts a model node in the
        # tree — before the synthesis routing below folds. Without this the
        # model node is created after routing and the ordering looks fine
        # whether or not the bug is present.
        _event(
            4,
            'system_tool_chunk',
            payload={'stage': 'tool_execution', 'phase': 'started', 'turn_index': 0},
            ts='2026-07-13T22:00:02Z',
        ),
        _event(
            5,
            'system_tool_complete',
            payload={'tool_name': 'leaf', 'correlation_id': 'c1'},
            ts='2026-07-13T22:00:02Z',
        ),
        _event(
            6,
            'model_routing',
            payload={'mode': 'synthesis', 'model': 'served-model'},
            ts=shared,
        ),
        _event(
            7,
            'progress_update',
            payload={'stage': 'model_call_started', 'turn_index': 0},
            ts=shared,
        ),
        _event(8, 'final', ts='2026-07-13T22:00:05Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    ordered = [(node.kind, node.started_at) for node in trace.root.children]
    routing_at_tie = ordered.index(('routing', shared))
    model_at_tie = ordered.index(('model', shared))
    assert routing_at_tie < model_at_tie


@pytest.mark.parametrize('usage', [None, {'input_tokens': 0, 'output_tokens': 0}])
def test_request_context_does_not_invent_a_provider_call(usage: dict[str, int] | None) -> None:
    """A routed tool-only run has context, not evidence of a model operation."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'trace_messages': [{'role': 'user', 'content': 'Build the vehicle'}]},
        ),
        _event(2, 'model_routing', payload={'mode': 'auto', 'model': 'selected-model'}),
        _event(3, 'system_tool_start', payload={'tool_name': 'build'}, correlation_id='build'),
        _event(4, 'system_tool_complete', payload={'tool_name': 'build'}, correlation_id='build'),
        _event(5, 'final', payload={} if usage is None else {'usage': usage}),
    ]
    trace = assemble_session_trace(events, session_id=_PARENT)
    assert not any(child.kind == 'model' for child in trace.root.children)
    context = next(child for child in trace.root.children if child.name == 'Run context')
    assert context.kind == 'working'
    assert context.detail['prompt'] == 'Build the vehicle'
    assert context.duration_ms is None
    assert context.status == 'completed'


def test_explicit_model_call_is_preserved_when_provider_usage_is_zero() -> None:
    """Zero reported usage must never erase an explicitly observed provider operation."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'progress_update',
            payload={'stage': 'model_call_started', 'turn_index': 0, 'model_call_id': 'actual'},
        ),
        _event(
            3,
            'progress_update',
            payload={
                'stage': 'model_call_completed',
                'turn_index': 0,
                'model_call_id': 'actual',
                'call_usage': {'input_tokens': 0, 'output_tokens': 0},
            },
        ),
        _event(4, 'final', payload={'usage': {'input_tokens': 0, 'output_tokens': 0}}),
    ]
    trace = assemble_session_trace(events, session_id=_PARENT)
    calls = [child for child in trace.root.children if child.kind == 'model']
    assert len(calls) == 1
    assert calls[0].detail['model_call_id'] == 'actual'


def test_trace_infers_legacy_model_runtime_between_routing_and_actions() -> None:
    """Direct SDK reporters still receive an honest model span without lifecycle events."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'trace_messages': [{'role': 'user', 'content': 'Build it'}]},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'model_routing',
            payload={'mode': 'auto', 'model': 'tier-model'},
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'system_tool_start',
            payload={'tool_name': 'build'},
            correlation_id='call-build',
            ts='2026-07-13T22:00:04Z',
        ),
        _event(
            4,
            'system_tool_complete',
            payload={'tool_name': 'build'},
            correlation_id='call-build',
            ts='2026-07-13T22:00:05Z',
        ),
        _event(
            5,
            'final',
            payload={'usage': {'input_tokens': 40, 'output_tokens': 8}},
            ts='2026-07-13T22:00:06Z',
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    exchange = next(child for child in trace.root.children if child.kind == 'model')
    assert exchange.name == 'Model call 1'
    assert exchange.status == 'completed'
    assert exchange.started_at == '2026-07-13T22:00:01Z'
    assert exchange.ended_at == '2026-07-13T22:00:04Z'
    assert exchange.duration_ms == _MODEL_RUNTIME_MS
    assert exchange.tokens is not None
    assert exchange.tokens.model_dump() == {
        'input_tokens': 40,
        'output_tokens': 8,
        'cache_read_tokens': 0,
        'cache_creation_tokens': 0,
    }


def test_trace_scrubs_common_private_field_values() -> None:
    """Common PII field names are protected even without the word secret."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'system_tool_start',
            payload={
                'tool_name': 'lookup_customer',
                'tool_call': {
                    'arguments': {
                        'email': 'person@example.com',
                        'phone_number': '555-0100',
                        'status': 'active',
                    }
                },
            },
            correlation_id='call-private',
        ),
        _event(3, 'final'),
    ]

    serialized = assemble_session_trace(events, session_id=_PARENT).model_dump_json()

    assert 'person@example.com' not in serialized
    assert '555-0100' not in serialized
    assert '"status":"active"' in serialized


def test_trace_redaction_receipt_scrubs_matching_tool_result_fields() -> None:
    """Dynamic private-data keys stay named while their values are removed from tool detail."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'system_tool_start',
            payload={'tool_name': 'inspect', 'tool_call': {'arguments': {}}},
            correlation_id='call-private-result',
        ),
        _event(
            3,
            'system_tool_complete',
            payload={
                'tool_name': 'inspect',
                'outcome': {
                    'status': 'ok',
                    'result': {'serial_number': 'SN-PRIVATE-1', 'status': 'completed'},
                },
            },
            correlation_id='call-private-result',
        ),
        _event(
            4,
            'enrichment',
            payload={
                'phase': 'tool_result_redaction_applied',
                'redaction': {
                    'redacted_value_count': 1,
                    'redacted_keys': ['serial_number'],
                },
            },
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)
    tool = next(child for child in trace.root.children if child.kind == 'tool')

    assert tool.detail['result'] == {
        'serial_number': '[REDACTED]',
        'status': 'completed',
    }
    assert 'SN-PRIVATE-1' not in trace.model_dump_json()


def test_trace_redaction_receipt_scrubs_result_completed_after_receipt() -> None:
    """Reporter ordering cannot reintroduce a private value after its receipt was emitted."""
    events = [
        _event(1, 'assignment_received'),
        _event(
            2,
            'system_tool_start',
            payload={'tool_name': 'inspect', 'tool_call': {'arguments': {}}},
            correlation_id='call-late-private-result',
        ),
        _event(
            3,
            'enrichment',
            payload={
                'phase': 'tool_result_redaction_applied',
                'redaction': {
                    'redacted_value_count': 1,
                    'redacted_keys': ['serial_number'],
                },
            },
        ),
        _event(
            4,
            'system_tool_complete',
            payload={
                'tool_name': 'inspect',
                'outcome': {
                    'status': 'ok',
                    'result': {'serial_number': 'SN-PRIVATE-2', 'status': 'completed'},
                },
            },
            correlation_id='call-late-private-result',
        ),
    ]

    serialized = assemble_session_trace(events, session_id=_PARENT).model_dump_json()

    assert 'SN-PRIVATE-2' not in serialized
    assert '"serial_number":"[REDACTED]"' in serialized


def test_unpaired_and_failed_tools_keep_honest_status() -> None:
    """A failed tool reads failed; a never-completed tool reads running, never done."""
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'user_id': 'u'}}),
        _event(
            2,
            'system_tool_start',
            payload={'tool_name': 'flaky'},
            correlation_id='call-flaky',
        ),
        _event(
            3,
            'system_tool_error',
            payload={'tool_name': 'flaky'},
            correlation_id='call-flaky',
            latency_ms=90,
        ),
        _event(
            4,
            'system_tool_start',
            payload={'tool_name': 'hung'},
            correlation_id='call-hung',
        ),
        _event(5, 'error', payload={'message': 'boom'}),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    root = trace.root
    assert root.status == 'failed'
    flaky, hung = root.children
    assert flaky.status == 'failed'
    assert flaky.duration_ms == _FLAKY_LATENCY_MS
    assert hung.status == 'running'
    assert hung.ended_at is None


def test_failed_run_keeps_curated_error_detail() -> None:
    """Trace users can diagnose a failed run without exposing arbitrary payload fields."""
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'analyst'}}),
        _event(
            2,
            'error',
            payload={
                'error_type': 'ModelRefusalError',
                'reason': 'model_refusal',
                'message': 'model refused the request',
                'private_context': 'never shown',
            },
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert trace.root.status == 'failed'
    assert trace.root.detail == {
        'error_type': 'ModelRefusalError',
        'reason': 'model_refusal',
        'message': 'model refused the request',
    }
    assert 'private_context' not in trace.root.model_dump_json()


def test_terminal_run_never_leaves_its_request_context_running() -> None:
    """A terminal root cannot contain the synthetic forever-running child seen in Studio."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'trace_messages': [{'role': 'user', 'content': 'Inspect it'}]},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'error',
            payload={'error_type': 'ModelUnavailableError', 'message': 'model unavailable'},
            ts='2026-07-13T22:00:01Z',
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    exchange = next(child for child in trace.root.children if child.name == 'Run context')
    assert not any(child.kind == 'model' for child in trace.root.children)
    assert trace.root.status == 'failed'
    assert exchange.status == 'failed'
    assert exchange.ended_at == trace.root.ended_at


@pytest.mark.parametrize(
    'cancellation',
    [
        {'error_type': 'CancelledError'},
        {'error_class': 'CancelledError', 'error_code': 'invoke_cancelled'},
        {'error_code': 'invoke_cancelled'},
    ],
)
def test_cancelled_error_closes_run_as_cancelled_not_failed(
    cancellation: dict[str, str],
) -> None:
    """A user-requested cancellation is terminal without being presented as a failure."""
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'user_id': 'u'}}),
        _event(
            2,
            'system_tool_start',
            payload={'tool_name': 'in_flight'},
            correlation_id='call-in-flight',
        ),
        _event(
            3,
            'error',
            payload={
                'stage': 'error',
                **cancellation,
                'message': 'invoke cancelled',
            },
        ),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert trace.root.status == 'cancelled'
    assert trace.root.children[0].status == 'cancelled'
    assert trace.root.children[0].ended_at == trace.root.ended_at


def test_dropped_event_types_never_reach_the_tree() -> None:
    """Projection-dropped events (chunks, heartbeats, internals) leave no trace nodes."""
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'user_id': 'u'}}),
        _event(2, 'status_message_chunk', payload={'content_delta': 'internal narration'}),
        _event(3, 'heartbeat'),
        _event(4, 'progress_update', payload={'usage': {'input_tokens': 3}}),
        _event(5, 'final', payload={'usage': {'input_tokens': 9, 'output_tokens': 2}}),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert trace.root.children == []
    assert 'internal narration' not in trace.root.model_dump_json()


def test_model_routing_folds_into_a_curated_routing_aspect() -> None:
    """The routing aspect carries the decision detail users need - and only that."""
    events = [
        _event(1, 'assignment_received', payload={'stage': 'session_started'}),
        _event(
            2,
            'model_routing',
            payload={
                'mode': 'auto',
                'pinned': True,
                'profile': 'internal_structured',
                'complexity': 'simple',
                'model': 'gpt-5.6-luna',
                'chain': ['openai/gpt-5.6-luna', 'xai/grok-4.5'],
                'internal_selector_state': {'never': 'shown'},
                'policy_origin': 'framework_profile',
                'expected_task_cost': None,
                'evidence_status': 'no_comparable_reviewed_task_evidence',
                'first_event_ms': 20,
                'first_useful_ms': 80,
                'first_visible_ms': 150,
                'usage_status': 'unreported',
            },
            ts='2026-07-13T22:00:01Z',
        ),
        _event(3, 'final', ts='2026-07-13T22:00:02Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    routing = next(child for child in trace.root.children if child.kind == 'routing')
    assert routing.name == 'Routed to gpt-5.6-luna'
    assert routing.status == 'completed'
    assert routing.detail == {
        'mode': 'auto',
        'pinned': True,
        'profile': 'internal_structured',
        'complexity': 'simple',
        'model': 'gpt-5.6-luna',
        'chain': ['openai/gpt-5.6-luna', 'xai/grok-4.5'],
        'policy_origin': 'framework_profile',
        'expected_task_cost': None,
        'evidence_status': 'no_comparable_reviewed_task_evidence',
        'first_event_ms': 20,
        'first_useful_ms': 80,
        'first_visible_ms': 150,
        'usage_status': 'unreported',
    }


def test_hop_timing_is_not_labeled_as_another_routing_decision() -> None:
    """Provider timing telemetry preserves its identity without inventing another route."""
    payload = {
        'mode': 'hop_timing',
        'model': 'gpt-5.6-luna',
        'attempt_id': 'attempt-1',
        'first_event_ms': 100,
        'first_useful_ms': 200,
        'first_visible_ms': 300,
        'elapsed_ms': 400,
        'usage_status': 'reported',
    }
    trace = assemble_session_trace(
        [
            _event(1, 'assignment_received', payload={'stage': 'session_started'}),
            _event(2, 'model_routing', payload=payload),
            _event(3, 'final'),
        ],
        session_id=_PARENT,
    )
    timing = next(child for child in trace.root.children if child.kind == 'routing')
    assert timing.name == 'Response timing for gpt-5.6-luna'
    assert timing.detail == payload


def test_synthesis_routing_is_named_as_a_final_presentation_decision() -> None:
    """A post-work downshift must not look like another initial auto route."""
    events = [
        _event(1, 'assignment_received', payload={'stage': 'session_started'}),
        _event(
            2,
            'model_routing',
            payload={
                'mode': 'synthesis',
                'pinned': False,
                'source_profile': 'reasoning',
                'profile': 'fast',
                'complexity': 'simple',
                'model': 'grok-4.5',
                'chain': ['xai/grok-4.5', 'anthropic/claude-haiku-4-5'],
                'selection_policy': 'economical_auto',
                'fallback_policy': 'cross_provider_required',
            },
            ts='2026-07-13T22:00:01Z',
        ),
        _event(3, 'final', ts='2026-07-13T22:00:02Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    routing = next(child for child in trace.root.children if child.kind == 'routing')
    assert routing.name == 'Final synthesis route to grok-4.5'
    assert routing.detail == {
        'mode': 'synthesis',
        'pinned': False,
        'source_profile': 'reasoning',
        'profile': 'fast',
        'complexity': 'simple',
        'model': 'grok-4.5',
        'chain': ['xai/grok-4.5', 'anthropic/claude-haiku-4-5'],
        'selection_policy': 'economical_auto',
        'fallback_policy': 'cross_provider_required',
    }


def test_default_assembly_stays_single_level_and_has_no_truncated_field() -> None:
    """The default (non-recursive) call is unchanged: one level, no `truncated` at all.

    `SessionTrace` never gained a `truncated` field - only the recursive assembler's
    `RecursiveSessionTrace` subclass has one. This is the S6-COMPAT-001 fix: adding
    recursion must never change what a single-level trace serializes.
    """
    grandchild = 'ses-trace-grandchild'
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'root'}}),
        _event(
            2,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'run_config': {'agent_id': 'child'}},
        ),
        _event(
            3,
            'assignment_received',
            session_id=grandchild,
            parent_session_id=_CHILD,
            payload={'run_config': {'agent_id': 'grandchild'}},
        ),
        _event(4, 'final', session_id=grandchild, parent_session_id=_CHILD),
        _event(5, 'final', session_id=_CHILD, parent_session_id=_PARENT),
        _event(6, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)

    assert 'truncated' not in type(trace).model_fields
    assert not hasattr(trace, 'truncated')
    assert [child.name for child in trace.root.children] == ['child']
    # The grandchild is invisible to the default single-level fold - unchanged behavior.
    child_node = trace.root.children[0]
    assert child_node.children == []


def test_single_level_serialization_is_byte_identical_to_pre_recursion() -> None:
    """S6-COMPAT-001 regression: the exact JSON BYTES a single-level trace produces.

    A dict-equality check on `model_dump()` output (the prior form of this test) says
    nothing about JSON key ORDER or ENCODING - two different serializations can
    compare dict-equal while producing genuinely different bytes on the wire. This
    compares the actual `model_dump_json()` byte string, pydantic's own byte-level
    serializer, against a frozen golden fixture captured from the pre-recursion
    `SessionTrace` shape. Any future change to `SessionTrace` (a new field, a
    reordered field, a changed default) that alters these bytes is exactly the class
    of regression S6-COMPAT-001 was raised over - so this test intentionally has zero
    tolerance. (The companion HTTP-boundary test, `test_run_trace_route_bytes_are_
    byte_identical_to_pre_recursion` in maivn-control-plane, additionally exercises the
    real `/v1/runs/{id}/trace` route's `exclude_none=True` serializer and the ASGI
    layer's own `json.dumps` encoding - two steps this contracts-level test does not
    reach on its own.)
    """
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'byte-compat'}}),
        _event(2, 'final', payload={'usage': {'input_tokens': 3, 'output_tokens': 1}}),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT)
    dumped_bytes = trace.model_dump_json().encode('utf-8')

    assert dumped_bytes == (
        b'{"session_id":"' + _PARENT.encode('utf-8') + b'","root":{'
        b'"node_id":"run--' + _PARENT.encode('utf-8') + b'","kind":"run",'
        b'"name":"byte-compat","status":"completed",'
        b'"started_at":"2026-07-13T22:00:00Z","ended_at":"2026-07-13T22:00:00Z",'
        b'"duration_ms":null,"tokens":{"input_tokens":3,"output_tokens":1,'
        b'"cache_read_tokens":0,"cache_creation_tokens":0},"detail":{},"children":[]}}'
    )
    assert b'"truncated"' not in dumped_bytes


def test_recursive_assembly_folds_multi_level_cascade() -> None:
    """recursive=True nests grandchildren (and deeper) under their true parent run."""
    grandchild = 'ses-trace-grandchild'
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'root'}}),
        _event(
            2,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={'run_config': {'agent_id': 'child'}},
        ),
        _event(
            3,
            'assignment_received',
            session_id=grandchild,
            parent_session_id=_CHILD,
            payload={'run_config': {'agent_id': 'grandchild'}},
        ),
        _event(4, 'final', session_id=grandchild, parent_session_id=_CHILD),
        _event(5, 'final', session_id=_CHILD, parent_session_id=_PARENT),
        _event(6, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    assert trace.truncated is False
    assert [child.name for child in trace.root.children] == ['child']
    child_node = trace.root.children[0]
    assert [grandchild_node.name for grandchild_node in child_node.children] == ['grandchild']


def test_recursive_assembly_excludes_unrelated_sibling_root_sessions() -> None:
    """A sibling root-level session (same fetch, different lineage) is not a descendant."""
    sibling_root = 'ses-trace-sibling-root'
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'root'}}),
        _event(2, 'final'),
        _event(3, 'assignment_received', session_id=sibling_root, payload={}),
        _event(4, 'final', session_id=sibling_root),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    assert trace.root.children == []


def test_recursive_assembly_attaches_dangling_parent_at_root_with_marker() -> None:
    """A session whose declared parent never appears in the fetch attaches at root."""
    orphan = 'ses-trace-orphan'
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'root'}}),
        _event(
            2,
            'assignment_received',
            session_id=orphan,
            parent_session_id='ses-trace-missing-parent',
            payload={'run_config': {'agent_id': 'orphan'}},
        ),
        _event(3, 'final', session_id=orphan, parent_session_id='ses-trace-missing-parent'),
        _event(4, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    assert [child.name for child in trace.root.children] == ['orphan']
    assert trace.root.children[0].detail.get('orphaned') is True


def test_recursive_assembly_guards_against_lineage_cycles() -> None:
    """A cycle with no path back to the requested session is excluded, not looped over."""
    cycle_a, cycle_b = 'ses-trace-cycle-a', 'ses-trace-cycle-b'
    events = [
        _event(1, 'assignment_received', payload={'run_config': {'agent_id': 'root'}}),
        _event(
            2,
            'assignment_received',
            session_id=cycle_a,
            parent_session_id=cycle_b,
            payload={},
        ),
        _event(
            3,
            'assignment_received',
            session_id=cycle_b,
            parent_session_id=cycle_a,
            payload={},
        ),
        _event(4, 'final'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    assert trace.root.children == []
    assert trace.truncated is False


def test_recursive_assembly_caps_descendant_sessions_and_events_deterministically() -> None:
    """Exceeding either cap sets truncated=True and cuts by position, not arbitrarily."""
    events: list[Event] = [
        _event(0, 'assignment_received', payload={'run_config': {'agent_id': 'root'}}),
    ]
    index = 1
    for child_index in range(5):
        child_session = f'ses-trace-cap-child-{child_index}'
        events.append(
            _event(
                index,
                'assignment_received',
                session_id=child_session,
                parent_session_id=_PARENT,
                payload={},
            ),
        )
        index += 1
    events.append(_event(index, 'final'))

    trace = assemble_session_trace(
        events,
        session_id=_PARENT,
        recursive=True,
        max_descendant_sessions=_DESCENDANT_CAP_FOR_TEST,
        max_events=1000,
    )

    assert trace.truncated is True
    assert len(trace.root.children) == _DESCENDANT_CAP_FOR_TEST
    # Deterministic cut: the first-discovered (lowest position) children survive.
    assert [child.name for child in trace.root.children] == ['Run', 'Run']

    trace_by_events = assemble_session_trace(
        events,
        session_id=_PARENT,
        recursive=True,
        max_descendant_sessions=1000,
        max_events=1,
    )

    assert trace_by_events.truncated is True


def test_staff_projection_drops_tenant_values_but_keeps_the_tree() -> None:
    """Cross-tenant staff reads keep structure and names, never caller-supplied values."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'run_config': {'agent_id': 'analyst'}},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'system_tool_start',
            payload={
                'tool_name': 'lookup_case',
                'tool_call': {'arguments': {'case_id': 'case-1', 'customer_email': 'a@b.invalid'}},
            },
            correlation_id='call-1',
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'system_tool_complete',
            payload={'tool_name': 'lookup_case', 'result': 'raw-tool-result'},
            correlation_id='call-1',
            ts='2026-07-13T22:00:02Z',
        ),
    ]

    tenant = assemble_session_trace(events, session_id=_PARENT)
    staff = project_trace_for_staff(tenant)

    tenant_tool = tenant.root.children[0]
    staff_tool = staff.root.children[0]

    # The tenant's own view keeps the values it supplied.
    assert tenant_tool.detail['arguments'] == {
        'case_id': 'case-1',
        'customer_email': '[REDACTED]',
    }

    # The staff view keeps the shape and the names, and drops every supplied value.
    assert staff.session_id == tenant.session_id
    assert staff_tool.name == tenant_tool.name
    assert staff_tool.status == tenant_tool.status
    assert staff_tool.duration_ms == tenant_tool.duration_ms
    assert staff_tool.detail['argument_names'] == ['case_id', 'customer_email']
    assert 'arguments' not in staff_tool.detail
    assert 'result' not in staff_tool.detail
    serialized = staff.model_dump_json()
    for leaked in ('case-1', 'a@b.invalid', 'raw-tool-result'):
        assert leaked not in serialized

    # The source trace is never mutated in place.
    assert 'arguments' in tenant_tool.detail


def _job_run_events(
    session: str,
    *,
    base: int,
    job_depth: int,
    job_index: int,
    ts: str,
) -> list[Event]:
    """One decomposed child run that routes, then makes a single model call."""
    return [
        _event(
            base,
            'assignment_received',
            session_id=session,
            parent_session_id=_PARENT,
            job_depth=job_depth,
            job_index=job_index,
            ts=ts,
        ),
        _event(
            base + 1,
            'model_routing',
            session_id=session,
            parent_session_id=_PARENT,
            payload={'mode': 'synthesis', 'model': 'served-model'},
            job_depth=job_depth,
            job_index=job_index,
            ts=ts,
        ),
        _event(
            base + 2,
            'progress_update',
            session_id=session,
            parent_session_id=_PARENT,
            payload={'stage': 'model_call_started', 'turn_index': 0},
            job_depth=job_depth,
            job_index=job_index,
            ts=ts,
        ),
        _event(
            base + 3,
            'final',
            session_id=session,
            parent_session_id=_PARENT,
            job_depth=job_depth,
            job_index=job_index,
            ts=ts,
        ),
    ]


def test_model_calls_are_named_by_the_job_they_belong_to() -> None:
    """Sibling jobs must not render the same label as each other or as the root.

    Every run's first call was "Model call 1", so a decomposed tree showed the label
    once per run and read as one run calling the model repeatedly. Naming a decomposed
    run by DEPTH.INDEX makes each call traceable to the job that made it.
    """
    events = [
        _event(1, 'assignment_received', ts='2026-07-13T22:00:00Z'),
        *_job_run_events('ses-job-a', base=10, job_depth=1, job_index=0, ts='2026-07-13T22:00:01Z'),
        *_job_run_events('ses-job-b', base=20, job_depth=1, job_index=1, ts='2026-07-13T22:00:02Z'),
        *_job_run_events('ses-job-c', base=30, job_depth=2, job_index=0, ts='2026-07-13T22:00:03Z'),
        _event(
            40,
            'model_routing',
            payload={'mode': 'synthesis', 'model': 'served-model'},
            ts='2026-07-13T22:00:04Z',
        ),
        _event(
            41,
            'progress_update',
            payload={'stage': 'model_call_started', 'turn_index': 0},
            ts='2026-07-13T22:00:04Z',
        ),
        _event(42, 'final', ts='2026-07-13T22:00:05Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    def model_names(node: TraceNode) -> list[str]:
        found = [child.name for child in node.children if child.kind == 'model']
        for child in node.children:
            found.extend(model_names(child))
        return found

    names = model_names(trace.root)
    assert 'Model call 1.1' in names
    assert 'Model call 1.2' in names
    assert 'Model call 2.1' in names
    # The root run carries no job coordinates, so it stays a plain number.
    assert 'Model call 1' in names
    assert len(names) == len(set(names)), 'two model calls rendered the same label'


def test_a_child_run_says_which_kind_of_run_it_is() -> None:
    """A tool job and a swarm member rendered identically until this existed.

    Both are child runs at a job depth, so nothing in the tree distinguished a
    decomposed graph from a fanned-out swarm while reading it.
    """
    events = [
        _event(1, 'assignment_received', ts='2026-07-13T22:00:00Z'),
        _event(
            2,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={
                'run_config': {
                    'agent_id': 'researcher',
                    'child_run_kind': 'tool_job',
                    'plan_node_id': 'job-summary',
                    'decomposition_depth': 1,
                },
            },
            ts='2026-07-13T22:00:01Z',
        ),
        _event(3, 'final', session_id=_CHILD, parent_session_id=_PARENT, ts='2026-07-13T22:00:02Z'),
        _event(4, 'final', ts='2026-07-13T22:00:03Z'),
    ]

    # Recursive assembly only. The single-level `SessionTrace` is byte-frozen by
    # S6-COMPAT-001, so identity rides the endpoint Studio actually reads.
    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    child = next(node for node in trace.root.children if node.kind == 'run')
    assert child.detail['child_run_kind'] == 'tool_job'
    assert child.detail['plan_node_id'] == 'job-summary'
    assert child.detail['decomposition_depth'] == 1
    # The root is not a child of anything; saying so adds a field with no reader.
    assert 'child_run_kind' not in trace.root.detail

    single = assemble_session_trace(events, session_id=_PARENT)
    single_child = next(node for node in single.root.children if node.kind == 'run')
    assert 'child_run_kind' not in single_child.detail


def test_a_run_says_whether_it_was_an_agent_or_a_swarm() -> None:
    """`_run_name` returns agent_id or swarm_id as a bare string and drops which it was.

    Nothing downstream could then tell a swarm root from an agent - counting them once
    reported a swarm root plus two delegates as three agents - and the trace cannot be
    grouped by scope without it.
    """
    events = [
        _event(
            1,
            'assignment_received',
            payload={'run_config': {'swarm_id': 'research-swarm', 'user_id': 'u'}},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'assignment_received',
            session_id=_CHILD,
            parent_session_id=_PARENT,
            payload={
                'run_config': {
                    'agent_id': 'analyst',
                    'child_run_kind': 'swarm_member',
                },
            },
            ts='2026-07-13T22:00:01Z',
        ),
        _event(3, 'final', session_id=_CHILD, parent_session_id=_PARENT, ts='2026-07-13T22:00:02Z'),
        _event(4, 'final', ts='2026-07-13T22:00:03Z'),
    ]

    trace = assemble_session_trace(events, session_id=_PARENT, recursive=True)

    assert trace.root.detail['scope_type'] == 'swarm'
    member = next(node for node in trace.root.children if node.kind == 'run')
    assert member.detail['scope_type'] == 'agent'
    assert member.detail['child_run_kind'] == 'swarm_member'

    # The byte-frozen single-level trace must not gain the field.
    single = assemble_session_trace(events, session_id=_PARENT)
    assert 'scope_type' not in single.root.detail


def _tool_named(root: TraceNode, name: str) -> TraceNode:
    return next(child for child in root.children if child.kind == 'tool' and child.name == name)


def _interrupts(root: TraceNode) -> list[TraceNode]:
    return [child for child in root.children if child.kind == 'interrupt']


def test_human_answer_closes_the_pause_with_what_came_back() -> None:
    """The pause opened by interrupt_required ends when the human-input tool returns."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'run_config': {'agent_id': 'asker', 'user_id': 'u', 'thread_id': 't'}},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'interrupt_required',
            payload={'interrupt_id': 'int-1'},
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'system_tool_start',
            payload={
                'tool_name': 'request_human_input',
                'tool_call': {'arguments': {'question': 'Which channels?', 'header': 'Channels'}},
            },
            correlation_id='call-ask',
            ts='2026-07-13T22:00:20Z',
        ),
        _event(
            4,
            'system_tool_complete',
            payload={
                'tool_name': 'request_human_input',
                'result': {'answer': ['Slack'], 'answer_format': {'type': 'array'}},
            },
            correlation_id='call-ask',
            ts='2026-07-13T22:00:21Z',
        ),
        _event(5, 'final', payload={}, ts='2026-07-13T22:00:25Z'),
    ]

    root = assemble_session_trace(events, session_id=_PARENT).root
    pause = _interrupts(root)[0]
    tool = _tool_named(root, 'request_human_input')

    assert pause.status == 'completed'
    assert pause.name == 'Input received'
    assert pause.ended_at == '2026-07-13T22:00:21Z'
    assert pause.duration_ms == _ANSWERED_PAUSE_MS
    assert pause.detail['answered_by'] == 'human'
    assert pause.detail['question'] == 'Which channels?'
    assert pause.detail['answer'] == ['Slack']
    assert pause.detail['tool_node_id'] == tool.node_id


def test_unanswered_pause_is_closed_when_the_run_ends() -> None:
    """A pause nobody answered ends with the run as cancelled, never as waiting forever."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'run_config': {'agent_id': 'asker', 'user_id': 'u', 'thread_id': 't'}},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'interrupt_required',
            payload={'interrupt_id': 'int-1'},
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'error',
            payload={'error_type': 'timeout', 'message': 'no answer'},
            ts='2026-07-13T22:00:31Z',
        ),
    ]

    root = assemble_session_trace(events, session_id=_PARENT).root
    pause = _interrupts(root)[0]

    assert pause.status == 'cancelled'
    assert pause.name == 'Input never received'
    assert pause.ended_at == '2026-07-13T22:00:31Z'
    assert pause.duration_ms == _UNANSWERED_PAUSE_MS


def test_ordinary_tool_completion_leaves_a_pause_waiting() -> None:
    """Only the human-input tool answers the pause; a lookup running meanwhile does not."""
    events = [
        _event(
            1,
            'assignment_received',
            payload={'run_config': {'agent_id': 'asker', 'user_id': 'u', 'thread_id': 't'}},
            ts='2026-07-13T22:00:00Z',
        ),
        _event(
            2,
            'interrupt_required',
            payload={'interrupt_id': 'int-1'},
            ts='2026-07-13T22:00:01Z',
        ),
        _event(
            3,
            'system_tool_start',
            payload={'tool_name': 'lookup_case', 'tool_call': {'arguments': {}}},
            correlation_id='call-1',
            ts='2026-07-13T22:00:02Z',
        ),
        _event(
            4,
            'system_tool_complete',
            payload={'tool_name': 'lookup_case', 'result': {'status': 'ok'}},
            correlation_id='call-1',
            ts='2026-07-13T22:00:03Z',
        ),
    ]

    root = assemble_session_trace(events, session_id=_PARENT).root
    assert _interrupts(root)[0].status == 'waiting'
