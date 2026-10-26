"""Fold one session's ordered events into its run node of the session trace."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from maivn_contracts.events._trace_detail import (
    apply_all_redaction_receipts,
    apply_redaction_receipt,
    aspect_detail,
    child_run_identity,
    curated_error_detail,
    decision_detail,
    run_name,
    sanitize_public_text_fields,
    tool_completion_detail,
    tool_detail,
    trace_tokens,
)
from maivn_contracts.events._trace_model_calls import (
    close_terminal_model_exchanges,
    elapsed_ms,
    finalize_legacy_model_span,
    fold_model_event,
    fold_model_final,
    fold_model_prompt,
)
from maivn_contracts.events._trace_nodes import TraceNode
from maivn_contracts.events.loaders import project_event_type

if TYPE_CHECKING:
    from collections.abc import Sequence

    from maivn_contracts.events._trace_nodes import TraceNodeKind, TraceNodeStatus
    from maivn_contracts.events.model import Event

_ASPECT_KINDS: dict[str, TraceNodeKind] = {
    'trace.working': 'working',
    'trace.memory': 'memory',
    'trace.resource': 'resource',
    'trace.shield': 'shield',
    'trace.routing': 'routing',
    'trace.hook': 'hook',
}


_ASPECT_NAMES: dict[TraceNodeKind, str] = {
    'working': 'Working',
    'memory': 'Memory',
    'resource': 'Resources',
    'shield': 'Privacy shield',
    'routing': 'Model routing',
    'hook': 'Hook',
}


_PHASE_NAMES: dict[str, str] = {
    'evaluating': 'Evaluating request',
    'planning': 'Planning execution',
    'planning_actions': 'Planning actions',
    'searching_tools': 'Finding tools',
    'loading_tools': 'Preparing tools',
    'planning_assignments': 'Planning assignments',
    'executing_assignments': 'Running assignments',
    'executing_actions': 'Running actions',
    'synthesizing': 'Preparing response',
    'finalizing': 'Finalizing run',
    'reevaluate_accrued': 'Re-evaluating execution',
    'memory_retrieving': 'Retrieving memory',
    'memory_retrieved': 'Memory retrieved',
    'document_analysis_selected': 'Document analysis selected',
    'document_evidence_coverage': 'Document evidence coverage',
    'memory_summarizing': 'Summarizing memory',
    'memory_summarized': 'Memory summarized',
    'memory_indexing': 'Indexing memory',
    'memory_indexed': 'Memory indexed',
    'memory_graph_extracting': 'Building memory graph',
    'memory_skill_extracting': 'Extracting skills',
    'memory_skill_extracted': 'Skills extracted',
    'memory_insight_extracting': 'Extracting insights',
    'memory_insight_extracted': 'Insights extracted',
    'resource_registering': 'Registering resource',
    'resource_registered': 'Resource registered',
    'resource_dedup_reused': 'Reusing resource',
    'resource_version_superseded': 'Updating resource version',
    'resource_extracting': 'Extracting resource',
    'resource_extracted': 'Resource extracted',
    'redaction_previewed': 'Previewing redaction',
    'message_redaction_applied': 'Redacting input message',
    'tool_result_redaction_applied': 'Redacting tool result',
}


def run_node(
    events: Sequence[Event],
    *,
    session_id: str,
    scope_identity: bool = False,
) -> TraceNode:
    node = TraceNode(
        node_id=f'run--{session_id}',
        kind='run',
        name='Run',
        status='running',
        detail={},
    )
    open_tools: dict[str, TraceNode] = {}
    for event in events:
        projected = _trace_projection(event)
        if projected is None:
            continue
        _fold_event(node, event, projected, open_tools, scope_identity=scope_identity)
    # The legacy span names a model call too, and it must name it the same way the
    # lifecycle path does or a decomposed run served by an older reporter would be the
    # one place two sibling jobs still render an identical label.
    finalize_legacy_model_span(node, events[0] if events else None)
    close_terminal_model_exchanges(node)
    apply_all_redaction_receipts(node)
    _add_structural_stages(node)
    sanitize_public_text_fields(node)
    for tool_node in open_tools.values():
        tool_node.status = 'running'
    return node


def _add_structural_stages(node: TraceNode) -> None:
    """Add a public execution story when a runtime emitted only structural events."""
    if any(
        child.kind == 'working' and child.detail.get('phase') != 'request_context'
        for child in node.children
    ):
        return
    if not any(child.kind == 'routing' for child in node.children):
        return

    staged: list[TraceNode] = [
        TraceNode(
            node_id=f'working--{node.node_id}--evaluating',
            kind='working',
            name='Evaluating request',
            status='completed',
            started_at=node.started_at,
            ended_at=node.started_at,
            detail={'phase': 'evaluating', 'source': 'structural'},
        )
    ]
    execution_added = False
    for child in node.children:
        if child.kind == 'tool' and not execution_added:
            staged.append(
                TraceNode(
                    node_id=f'working--{node.node_id}--executing',
                    kind='working',
                    name='Running actions',
                    status='completed',
                    started_at=child.started_at,
                    ended_at=child.started_at,
                    detail={'phase': 'executing_actions', 'source': 'structural'},
                )
            )
            execution_added = True
        staged.append(child)
    if node.status == 'completed':
        staged.append(
            TraceNode(
                node_id=f'working--{node.node_id}--finalizing',
                kind='working',
                name='Finalizing run',
                status='completed',
                started_at=node.ended_at,
                ended_at=node.ended_at,
                detail={'phase': 'finalizing', 'source': 'structural'},
            )
        )
    node.children = staged


# The closed progress_update stages the trace lifts out of an otherwise dropped type.
_PROGRESS_STAGES: dict[str, str] = {
    'model_call_started': 'trace.model_started',
    'model_call_completed': 'trace.model_completed',
    'decision_completed': 'trace.decision',
}


def _trace_projection(event: Event) -> str | None:
    """Resolve a public enrichment phase before falling back to its event type."""
    if event.type == 'progress_update':
        stage = event.payload.get('stage')
        projected = _PROGRESS_STAGES.get(stage) if isinstance(stage, str) else None
        if projected is not None:
            return projected
    if event.type == 'enrichment':
        phase = event.payload.get('phase')
        if isinstance(phase, str) and phase:
            try:
                projected = project_event_type(phase, 'trace')
            except KeyError:
                # Enrichment payloads are intentionally open in the canonical
                # schema. A producer can add a value such as ``plan_warning``
                # without inventing an event type, so preserve the complete
                # trace by using the curated generic enrichment mapping.
                return project_event_type(event.type, 'trace')
            if projected is not None:
                return projected
    return project_event_type(event.type, 'trace')


def _fold_event(  # noqa: C901 - closed dispatcher over the trace event vocabulary.
    node: TraceNode,
    event: Event,
    projected: str,
    open_tools: dict[str, TraceNode],
    *,
    scope_identity: bool = False,
) -> None:
    if projected == 'trace.run_started':
        node.started_at = event.ts
        node.name = run_name(event.payload)
        if scope_identity:
            node.detail.update(child_run_identity(event.payload))
        fold_model_prompt(node, event)
        return
    if projected in {'trace.run_completed', 'trace.run_failed'}:
        if projected == 'trace.run_completed':
            fold_model_final(node, event)
        _fold_run_terminal(node, event, projected, open_tools)
        return
    if projected == 'trace.tool_started':
        tool = _tool_start_node(event)
        node.children.append(tool)
        if event.correlation_id:
            open_tools[event.correlation_id] = tool
        return
    if projected in {'trace.tool_completed', 'trace.tool_failed'}:
        _close_tool(node, event, projected, open_tools)
        return
    if projected in {
        'trace.interrupt',
        'trace.trigger_fired',
        'trace.trigger_failed',
        'trace.trigger_skipped',
    }:
        _fold_marker(node, event, projected)
        return
    if fold_model_event(node, event, projected):
        return
    if projected == 'trace.decision':
        _fold_decision(node, event)
    elif (kind := _ASPECT_KINDS.get(projected)) is not None:
        _fold_aspect(node, event, kind)


def _terminal_run_status(event: Event, projected: str) -> TraceNodeStatus:
    if projected != 'trace.run_failed':
        return 'completed'
    if (
        event.payload.get('error_code') == 'invoke_cancelled'
        or event.payload.get('error_class') == 'CancelledError'
        or event.payload.get('error_type') == 'CancelledError'
    ):
        return 'cancelled'
    return 'failed'


def _fold_run_terminal(
    node: TraceNode,
    event: Event,
    projected: str,
    open_tools: dict[str, TraceNode],
) -> None:
    # A delegated child emits assignment_completed after its own final; keep the
    # first terminal status and stretch the end time to the latest terminal event.
    if node.status == 'running':
        node.status = _terminal_run_status(event, projected)
    node.ended_at = event.ts
    if projected == 'trace.run_failed':
        node.detail = {**node.detail, **curated_error_detail(event.payload)}
    if node.status == 'cancelled':
        _cancel_open_tools(open_tools, ended_at=event.ts)
    _close_unanswered_interrupts(node, ended_at=event.ts)
    tokens = trace_tokens(event.payload)
    if tokens is not None:
        node.tokens = tokens


def _cancel_open_tools(open_tools: dict[str, TraceNode], *, ended_at: str) -> None:
    for tool_node in open_tools.values():
        tool_node.status = 'cancelled'
        tool_node.ended_at = ended_at
    open_tools.clear()


_HUMAN_INPUT_TOOL = 'request_human_input'


def _is_human_input_tool(tool: TraceNode) -> bool:
    """Return whether a person, not code, supplied this tool's result."""
    if tool.name == _HUMAN_INPUT_TOOL:
        return True
    result = tool.detail.get('result')
    if not isinstance(result, Mapping):
        return False
    keys = cast('Mapping[object, object]', result)
    return 'answer' in keys and 'answer_format' in keys


def _resolve_waiting_interrupt(node: TraceNode, tool: TraceNode, *, ended_at: str) -> None:
    """Close the pause a human just ended.

    The pause node was opened when the run asked and, until now, stayed
    ``waiting`` forever: no event says "answered", the answer only arrives as
    the human-input tool's result. Pair the two here, so the reader sees how
    long the run waited and what came back, next to the tool that carried it.
    """
    waiting = [
        child for child in node.children if child.kind == 'interrupt' and child.status == 'waiting'
    ]
    if not waiting:
        return
    pause = waiting[-1]
    pause.status = 'completed'
    pause.name = 'Input received'
    pause.ended_at = ended_at
    pause.duration_ms = elapsed_ms(pause.started_at, ended_at)
    detail: dict[str, Any] = {'answered_by': 'human', 'tool_node_id': tool.node_id}
    arguments = tool.detail.get('arguments')
    if isinstance(arguments, Mapping):
        question = cast('Mapping[object, object]', arguments).get('question')
        if isinstance(question, str) and question:
            detail['question'] = question
    result = tool.detail.get('result')
    if isinstance(result, Mapping):
        answers = cast('Mapping[object, object]', result)
        if 'answer' in answers:
            detail['answer'] = answers['answer']
    pause.detail = {**pause.detail, **detail}


def _close_unanswered_interrupts(node: TraceNode, *, ended_at: str) -> None:
    """Close any pause still open when the run ends; nobody answered it."""
    for child in node.children:
        if child.kind == 'interrupt' and child.status == 'waiting':
            child.status = 'cancelled'
            child.name = 'Input never received'
            child.ended_at = ended_at
            child.duration_ms = elapsed_ms(child.started_at, ended_at)


def _fold_marker(node: TraceNode, event: Event, projected: str) -> None:
    if projected == 'trace.interrupt':
        node.children.append(
            TraceNode(
                node_id=f'interrupt--{event.event_id}',
                kind='interrupt',
                name='Waiting on input',
                status='waiting',
                started_at=event.ts,
            ),
        )
        return
    # A trigger that failed or declined to fire is why an expected run never
    # happened. Reading absence is the hardest debugging there is, so these say
    # so plainly rather than being filtered out as operational noise. Neither
    # carries user content.
    trigger_name, trigger_status = {
        'trace.trigger_failed': ('Trigger failed', 'failed'),
        'trace.trigger_skipped': ('Trigger skipped', 'cancelled'),
    }.get(projected, ('Trigger fired', 'completed'))
    node.children.insert(
        0,
        TraceNode(
            node_id=f'trigger--{event.event_id}',
            kind='trigger',
            name=trigger_name,
            status=cast('TraceNodeStatus', trigger_status),
            started_at=event.ts,
            ended_at=event.ts,
        ),
    )


def _fold_aspect(node: TraceNode, event: Event, kind: TraceNodeKind) -> None:
    last = node.children[-1] if node.children else None
    detail = aspect_detail(event, kind)
    if kind == 'shield':
        redacted_keys = detail.get('redacted_keys')
        if isinstance(redacted_keys, list):
            apply_redaction_receipt(node, cast('list[object]', redacted_keys))
    # Repeated phase markers may describe one ongoing stage. Hook firings and
    # route/usage receipts are separate observations: merging them invents a
    # duration spanning unrelated work and discards the later identity.
    if (
        kind not in {'hook', 'routing'}
        and last is not None
        and last.kind == kind
        and last.detail.get('phase') == detail.get('phase')
    ):
        last.ended_at = event.ts
        return
    node.children.append(
        TraceNode(
            node_id=f'{kind}--{event.event_id}',
            kind=kind,
            name=_aspect_name(event, kind),
            status=_aspect_status(detail),
            started_at=event.ts,
            ended_at=event.ts,
            detail=detail,
        ),
    )


def _fold_decision(node: TraceNode, event: Event) -> None:
    """Append one decision-model call as its own step.

    Never merged with a neighbour: each call is a separate observation, and
    two back-to-back decisions must read as two. The event is emitted when the
    call ends, so the step starts ``duration_ms`` earlier.
    """
    detail = decision_detail(event.payload)
    duration_ms = detail.get('duration_ms')
    node.children.append(
        TraceNode(
            node_id=f'decision--{event.event_id}',
            kind='decision',
            name='Decision',
            status='failed' if event.payload.get('status') == 'failed' else 'completed',
            started_at=_shift_ts(event.ts, duration_ms) if duration_ms else event.ts,
            ended_at=event.ts,
            duration_ms=duration_ms,
            detail=detail,
        ),
    )


_MILLISECOND_DIGITS = 3


def _shift_ts(ts: str, duration_ms: int) -> str:
    """Return ``ts`` moved ``duration_ms`` earlier, in the same text form.

    Children are ordered by comparing these strings, so the result keeps the
    source's zone suffix and fractional precision.
    """
    try:
        parsed = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError:
        return ts
    fraction = ts.split('.', 1)[1] if '.' in ts else ''
    digits = len(fraction) - len(fraction.lstrip('0123456789'))
    shifted = (parsed - timedelta(milliseconds=duration_ms)).isoformat(
        timespec='microseconds' if digits > _MILLISECOND_DIGITS else 'milliseconds',
    )
    return shifted.replace('+00:00', 'Z') if ts.endswith('Z') else shifted


def _aspect_status(detail: Mapping[str, Any]) -> TraceNodeStatus:
    """Aspect outcome, so a failure is not reported as a success.

    Aspects were hardcoded `completed` because most are instantaneous markers
    that cannot fail. Hooks can: a hook that raised carries `status: 'failed'`
    in its own detail while the node claimed `completed`, so every consumer
    that reads node status - the Errors filter, any failure highlighting -
    silently skipped it.
    """
    reported = detail.get('status')
    if reported in {'failed', 'error'}:
        return 'failed'
    if reported == 'cancelled':
        return 'cancelled'
    return 'completed'


def _aspect_name(event: Event, kind: TraceNodeKind) -> str:
    if kind == 'routing':
        model = event.payload.get('model')
        receipt_name = {
            'hop_timing': 'Response timing',
            'hop_usage': 'Usage recorded',
        }.get(str(event.payload.get('mode')))
        if receipt_name is not None:
            return (
                f'{receipt_name} for {model}' if isinstance(model, str) and model else receipt_name
            )
        if isinstance(model, str) and model:
            return (
                f'Final synthesis route to {model}'
                if event.payload.get('mode') == 'synthesis'
                else f'Routed to {model}'
            )
    if kind == 'hook':
        # The hook's own name is the useful label; "Hook" on every row would
        # say nothing about which one ran.
        hook_name = event.payload.get('name')
        if isinstance(hook_name, str) and hook_name:
            return hook_name
    phase = event.payload.get('phase')
    if isinstance(phase, str):
        document_name = _document_aspect_name(event, phase)
        if document_name is not None:
            return document_name
        name = _PHASE_NAMES.get(phase)
        if name is not None:
            return name
    return _ASPECT_NAMES.get(kind, kind.title())


def _document_aspect_name(event: Event, phase: str) -> str | None:
    """Name one value-free document strategy or aggregate coverage aspect."""
    memory_value = event.payload.get('memory')
    if not isinstance(memory_value, Mapping):
        return None
    memory_payload = cast('Mapping[str, object]', memory_value)
    if phase == 'document_analysis_selected':
        mode = memory_payload.get('mode')
        if not isinstance(mode, str):
            return None
        return {
            'focused_navigation': 'Focused document navigation',
            'direct_context': 'Direct document context',
            'recursive_navigation': 'Recursive document navigation',
        }.get(mode)
    if phase == 'document_evidence_coverage':
        return (
            'Document coverage complete'
            if memory_payload.get('coverage_complete') is True
            else 'Document coverage incomplete'
        )
    return None


def _tool_start_node(event: Event) -> TraceNode:
    payload = event.payload
    tool_name = str(payload.get('tool_name') or 'tool')
    raw_tool_type = payload.get('tool_type')
    tool_type = (
        str(raw_tool_type).lower()
        if isinstance(raw_tool_type, str) and raw_tool_type
        else ('system' if event.type.startswith('system_tool_') else 'func')
    )
    return TraceNode(
        node_id=f'tool--{event.correlation_id or event.event_id}',
        kind='tool',
        name=tool_name,
        status='running',
        started_at=event.ts,
        detail=tool_detail(payload, tool_type=tool_type),
    )


def _close_tool(
    node: TraceNode,
    event: Event,
    projected: str,
    open_tools: dict[str, TraceNode],
) -> None:
    status: TraceNodeStatus = 'failed' if projected == 'trace.tool_failed' else 'completed'
    tool = open_tools.pop(event.correlation_id, None) if event.correlation_id else None
    if tool is None:
        tool = TraceNode(
            node_id=f'tool--{event.correlation_id or event.event_id}',
            kind='tool',
            name=str(event.payload.get('tool_name') or 'tool'),
            status=status,
            started_at=event.ts,
        )
        node.children.append(tool)
    tool.status = status
    tool.ended_at = event.ts
    tool.detail = {
        **tool.detail,
        **tool_completion_detail(event.payload, failed=status == 'failed'),
    }
    if event.latency_ms is not None:
        tool.duration_ms = event.latency_ms
    if status == 'completed' and _is_human_input_tool(tool):
        _resolve_waiting_interrupt(node, tool, ended_at=event.ts)


__all__ = [
    'run_node',
]
