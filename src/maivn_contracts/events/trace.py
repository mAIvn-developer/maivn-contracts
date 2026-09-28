"""Assemble the user-facing session trace from ordered canonical events.

The trace is the product's answer to "what is happening in your server?": a run tree
with agents, tools, timings, tokens, and status - and nothing else. Classification comes
from the `trace` projection (the curated vocabulary), structure from the lineage fields
the event schema always carried (parent_session_id, correlation_id, job metadata).
Anything the projection drops never reaches a user, by construction.

The assembler lives in contracts because it is a pure fold over Event records and both
the data plane (API-key session traces) and the control plane (cookie-authed org run
views) serve it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, cast, overload

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from maivn_contracts.events.loaders import project_event_type

if TYPE_CHECKING:
    from collections.abc import Sequence

    from maivn_contracts.events.model import Event

TraceNodeKind: TypeAlias = Literal[
    'run',
    'tool',
    'working',
    'memory',
    'resource',
    'shield',
    'interrupt',
    'trigger',
    'routing',
    'model',
    'hook',
]
TraceNodeStatus: TypeAlias = Literal['running', 'completed', 'failed', 'cancelled', 'waiting']

# Recursive-assembly caps (S6 sessions trace): a pathological fan-out (e.g. a
# runaway trigger chain) must degrade to a bounded, deterministic truncation
# rather than an unbounded tree or an unbounded fold.
MAX_TRACE_DESCENDANT_SESSIONS = 200
MAX_TRACE_EVENTS = 20_000

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
# The routing aspect surfaces WHY a model served the run - the curated subset
# of the model_routing payload users see (traceability directive 2026-07-13).
_ROUTING_DETAIL_KEYS = (
    'planning_requested',
    'planning_tier',
    'planning_reason',
    'planning_auto',
    'mode',
    'pinned',
    'source_profile',
    'profile',
    'complexity',
    'model',
    'chain',
    'selection_policy',
    'fallback_policy',
    'policy_origin',
    'policy_id',
    'adaptation_reason',
    'evidence_status',
    'evidence_digest',
    'evidence_samples',
    'acceptance_rate',
    'acceptance_lower_bound',
    'expected_task_cost',
    'expected_wall_ms',
    'expected_wall_p95_ms',
    'expected_task_cost_ceiling_usd',
    'attempt_id',
    'first_event_ms',
    'first_useful_ms',
    'first_visible_ms',
    'elapsed_ms',
    'usage_status',
    'reasons',
)
# A hook aspect says WHICH developer hook ran and how it ended, never what
# passed through it. Structural only, mirroring how tool and model names are
# already public while their arguments and results are not.
_HOOK_DETAIL_KEYS = ('name', 'stage', 'status', 'target_type')
_ASPECT_DETAIL_KEYS = (
    'mode',
    'hit_count',
    'skill_count',
    'insight_count',
    'resource_count',
    'latency_ms',
    'extracted_count',
    'persisted_count',
    'vector_rows',
    'graph_edges',
)
_DOCUMENT_ASPECT_DETAIL_KEYS = {
    'document_analysis_selected': (
        'reason',
        'estimated_document_tokens',
        'estimated_protected_input_tokens',
        'context_ratio',
    ),
    'document_evidence_coverage': (
        'expected_resource_count',
        'packet_count',
        'complete_resource_count',
        'failed_resource_count',
        'unavailable_resource_count',
        'uncertain_resource_count',
        'partial_resource_count',
        'no_evidence_resource_count',
        'gap_resource_count',
        'missing_packet_count',
        'finding_count',
        'gap_count',
        'covered_page_count',
        'covered_section_count',
        'coverage_complete',
        'model_input_tokens',
        'model_output_tokens',
        'navigation_calls',
        'elapsed_ms',
        'budget_exhausted',
    ),
}
_SENSITIVE_DETAIL_KEY_PARTS = (
    'api_key',
    'address',
    'authorization',
    'chain_of_thought',
    'password',
    'phone',
    'private_data',
    'prompt',
    'reasoning',
    'secret',
    'ssn',
    'system_message',
    'system_prompt',
    'token',
    'email',
)
_MAX_DETAIL_DEPTH = 5
_MAX_DETAIL_ITEMS = 50
_MAX_DETAIL_TEXT = 2_000
# Detail keys whose values are caller-supplied and therefore never cross to staff.
_TENANT_VALUE_KEYS = frozenset(
    {
        'arguments',
        'error',
        'internal_narration',
        'output',
        'prompt',
        'result',
        'transcript',
    },
)
_PRIVATE_PLACEHOLDER_PATTERN = re.compile(
    r'\{_\{([A-Za-z0-9_.-]+)\}_\}|\{\{([A-Za-z0-9_.-]+)\}\}|\{_([A-Za-z0-9_.-]+)_\}',
)


class TraceTokens(BaseModel):
    """Token spend attributed to one run node."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    input_tokens: StrictInt = Field(default=0, ge=0)
    output_tokens: StrictInt = Field(default=0, ge=0)
    cache_read_tokens: StrictInt = Field(default=0, ge=0)
    cache_creation_tokens: StrictInt = Field(default=0, ge=0)


class TraceNode(BaseModel):
    """One curated node of the session trace tree."""

    model_config = ConfigDict(extra='forbid')

    node_id: StrictStr = Field(..., min_length=1)
    kind: TraceNodeKind
    name: StrictStr = Field(..., min_length=1)
    status: TraceNodeStatus
    started_at: StrictStr | None = None
    ended_at: StrictStr | None = None
    duration_ms: StrictInt | None = Field(default=None, ge=0)
    tokens: TraceTokens | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    children: list[TraceNode] = Field(default_factory=list)


class SessionTrace(BaseModel):
    """The assembled trace for one session and its delegated children.

    Single-level shape only - this model is unchanged from its pre-S6 form and its
    serialization is byte-identical to before. The recursive `/v1/sessions/{id}/trace`
    endpoint uses `RecursiveSessionTrace` below instead of adding a field here, so
    every existing single-level caller (data-plane session trace, control-plane
    `/v1/runs/{id}/trace`) keeps emitting exactly the same bytes it always has.
    """

    model_config = ConfigDict(extra='forbid')

    session_id: StrictStr = Field(..., min_length=1)
    root: TraceNode


class RecursiveSessionTrace(SessionTrace):
    """`SessionTrace` for the recursive assembly path - `truncated` is required.

    A `SessionTrace` never lies about truncation because it never claims to be
    complete: the field simply does not exist there. Only the recursive assembler,
    which actually enforces descendant-session and event caps, is allowed to say
    whether it cut the tree short.
    """

    truncated: bool = Field(
        ...,
        description='True when a descendant-session or event cap cut the assembled tree short.',
    )


@overload
def assemble_session_trace(
    events: Sequence[Event],
    *,
    session_id: str,
    recursive: Literal[False] = False,
    max_descendant_sessions: int = MAX_TRACE_DESCENDANT_SESSIONS,
    max_events: int = MAX_TRACE_EVENTS,
) -> SessionTrace: ...


@overload
def assemble_session_trace(
    events: Sequence[Event],
    *,
    session_id: str,
    recursive: Literal[True],
    max_descendant_sessions: int = MAX_TRACE_DESCENDANT_SESSIONS,
    max_events: int = MAX_TRACE_EVENTS,
) -> RecursiveSessionTrace: ...


def assemble_session_trace(
    events: Sequence[Event],
    *,
    session_id: str,
    recursive: bool = False,
    max_descendant_sessions: int = MAX_TRACE_DESCENDANT_SESSIONS,
    max_events: int = MAX_TRACE_EVENTS,
) -> SessionTrace:
    """Fold a session family's ordered events into the curated trace tree.

    Tool nodes pair start/completion by correlation_id; delegated child sessions become
    child run nodes under the event that spawned them; consecutive same-aspect activity
    collapses into a single node so a burst of memory phases reads as one step, not
    thirty. Detail carries names and argument KEYS only - values, prompts, and internals
    never enter the tree.

    By default (``recursive=False``) this assembles exactly one level of delegated
    children, unchanged from the original behavior, and returns a plain
    ``SessionTrace`` - existing single-level callers (the data-plane session trace and
    the control plane's `/v1/runs/{id}/trace`) are unaffected, byte-for-byte. Pass
    ``recursive=True`` to fold the FULL descendant family (any depth) reachable from
    ``session_id``, bounded by ``max_descendant_sessions`` and ``max_events``, and get
    back a ``RecursiveSessionTrace`` whose required ``truncated`` field is set when
    either cap cuts the assembled tree; cuts happen deterministically by event
    position. Cyclic or dangling parent lineage is handled defensively: a session
    whose declared parent never appears in ``events`` is still included, attached
    directly under the root with an ``orphaned`` detail marker; a session locked in a
    cycle with no path back to ``session_id`` is excluded rather than looped over.
    """
    if not recursive:
        return _assemble_single_level(events, session_id=session_id)
    return _assemble_recursive(
        events,
        session_id=session_id,
        max_descendant_sessions=max_descendant_sessions,
        max_events=max_events,
    )


def _assemble_single_level(events: Sequence[Event], *, session_id: str) -> SessionTrace:
    by_session: dict[str, list[Event]] = {}
    for event in events:
        by_session.setdefault(event.session_id, []).append(event)

    root = _run_node(by_session.get(session_id, ()), session_id=session_id)
    for child_session, child_events in by_session.items():
        if child_session == session_id:
            continue
        first = child_events[0]
        if first.parent_session_id != session_id:
            continue
        root.children.append(_run_node(child_events, session_id=child_session))
    _sort_children_by_start(root)
    return SessionTrace(session_id=session_id, root=root)


@dataclass(frozen=True, slots=True)
class _SessionIndex:
    ordered_sessions: list[str]
    all_sessions: dict[str, list[Event]]
    parent_of: dict[str, str | None]


@dataclass(frozen=True, slots=True)
class _Reachability:
    reachable: set[str]
    orphaned: set[str]
    descendant_cap_hit: bool


def _assemble_recursive(
    events: Sequence[Event],
    *,
    session_id: str,
    max_descendant_sessions: int,
    max_events: int,
) -> RecursiveSessionTrace:
    index = _index_sessions(events)
    reachability = _discover_reachable_sessions(
        index,
        session_id=session_id,
        max_descendant_sessions=max_descendant_sessions,
    )
    events_by_session, event_cap_hit = _cap_events_by_position(
        events,
        reachable=reachability.reachable,
        max_events=max_events,
    )
    root = _build_and_attach_nodes(
        index,
        events_by_session,
        session_id=session_id,
        reachability=reachability,
    )
    return RecursiveSessionTrace(
        session_id=session_id,
        root=root,
        truncated=reachability.descendant_cap_hit or event_cap_hit,
    )


def _index_sessions(events: Sequence[Event]) -> _SessionIndex:
    first_event_index: dict[str, int] = {}
    parent_of: dict[str, str | None] = {}
    all_sessions: dict[str, list[Event]] = {}
    for index, event in enumerate(events):
        bucket = all_sessions.setdefault(event.session_id, [])
        if not bucket:
            first_event_index[event.session_id] = index
            parent_of[event.session_id] = event.parent_session_id
        bucket.append(event)
    # Deterministic discovery order: earliest-first-seen event position, never dict order.
    ordered_sessions = sorted(all_sessions, key=lambda sid: first_event_index[sid])
    return _SessionIndex(
        ordered_sessions=ordered_sessions,
        all_sessions=all_sessions,
        parent_of=parent_of,
    )


def _discover_reachable_sessions(
    index: _SessionIndex,
    *,
    session_id: str,
    max_descendant_sessions: int,
) -> _Reachability:
    reachable: set[str] = {session_id}
    orphaned: set[str] = set()
    descendant_cap_hit = False

    # Fixed-point reachability pass over parent_session_id edges: a session joins once
    # its parent is already known-reachable. Iterating to a fixed point (rather than one
    # pass) resolves legitimate multi-hop chains regardless of input ordering, while a
    # cycle with no path back to `session_id` never stabilizes into `reachable` and is
    # excluded rather than looped over (the defensive visited-set cycle guard).
    changed = True
    while changed:
        changed = False
        for sid in index.ordered_sessions:
            if sid in reachable:
                continue
            parent = index.parent_of.get(sid)
            if parent != session_id and parent not in reachable:
                continue
            if len(reachable) - 1 >= max_descendant_sessions:
                descendant_cap_hit = True
                continue
            reachable.add(sid)
            changed = True

    # Dangling lineage: the declared parent never appears in the fetched family at all.
    # Rather than drop the session's events, attach it at root with an orphan marker.
    for sid in index.ordered_sessions:
        if sid in reachable or sid == session_id:
            continue
        parent = index.parent_of.get(sid)
        if parent is None or parent in index.all_sessions:
            continue
        if len(reachable) - 1 >= max_descendant_sessions:
            descendant_cap_hit = True
            continue
        reachable.add(sid)
        orphaned.add(sid)

    return _Reachability(
        reachable=reachable,
        orphaned=orphaned,
        descendant_cap_hit=descendant_cap_hit,
    )


def _cap_events_by_position(
    events: Sequence[Event],
    *,
    reachable: set[str],
    max_events: int,
) -> tuple[dict[str, list[Event]], bool]:
    # Deterministic event cap: cut the position-ordered stream, not per-session blocks.
    filtered_events = [event for event in events if event.session_id in reachable]
    event_cap_hit = len(filtered_events) > max_events
    if event_cap_hit:
        filtered_events = filtered_events[:max_events]
    events_by_session: dict[str, list[Event]] = {}
    for event in filtered_events:
        events_by_session.setdefault(event.session_id, []).append(event)
    return events_by_session, event_cap_hit


def _build_and_attach_nodes(
    index: _SessionIndex,
    events_by_session: dict[str, list[Event]],
    *,
    session_id: str,
    reachability: _Reachability,
) -> TraceNode:
    reachable = reachability.reachable
    nodes: dict[str, TraceNode] = {
        sid: _run_node(
            events_by_session.get(sid, ()),
            session_id=sid,
            scope_identity=True,
        )
        for sid in reachable
    }
    root = nodes[session_id]
    for sid in index.ordered_sessions:
        if sid == session_id or sid not in reachable:
            continue
        node = nodes[sid]
        parent = index.parent_of.get(sid)
        is_orphan = sid in reachability.orphaned
        parent_node = nodes.get(parent) if (parent is not None and not is_orphan) else None
        if parent_node is None:
            node.detail = {**node.detail, 'orphaned': True}
            root.children.append(node)
        else:
            parent_node.children.append(node)

    _sort_children_by_start(root)
    return root


def _sort_children_by_start(node: TraceNode) -> None:
    node.children.sort(key=lambda child: child.started_at or '')
    for child in node.children:
        _sort_children_by_start(child)


def _run_node(
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
    _finalize_legacy_model_span(node, events[0] if events else None)
    _close_terminal_model_exchanges(node)
    _apply_all_redaction_receipts(node)
    _add_structural_stages(node)
    _sanitize_public_text_fields(node)
    for tool_node in open_tools.values():
        tool_node.status = 'running'
    return node


def _close_terminal_model_exchanges(node: TraceNode) -> None:
    """Keep synthetic/legacy model children consistent with a terminal run."""
    if node.status not in {'completed', 'failed', 'cancelled'} or node.ended_at is None:
        return
    for child in node.children:
        if child.kind != 'model' or child.status != 'running':
            continue
        child.status = node.status
        child.ended_at = node.ended_at
        child.duration_ms = _elapsed_ms(child.started_at, child.ended_at)


def _apply_all_redaction_receipts(node: TraceNode) -> None:
    """Apply receipts after folding so event arrival order cannot restore private values."""
    previous_tool: TraceNode | None = None
    for child in node.children:
        if child.kind == 'tool':
            previous_tool = child
        elif child.kind == 'shield' and previous_tool is not None:
            redacted_keys = child.detail.get('redacted_keys')
            if isinstance(redacted_keys, list):
                previous_tool.detail = cast(
                    'dict[str, Any]',
                    _redact_matching_keys(
                        previous_tool.detail,
                        {
                            key.strip()
                            for key in cast('list[object]', redacted_keys)
                            if isinstance(key, str) and key.strip()
                        },
                    ),
                )
        _apply_all_redaction_receipts(child)


def _finalize_legacy_model_span(node: TraceNode, run_event: Event | None = None) -> None:
    """Infer provider time for reporters that predate explicit model lifecycle events."""
    exchange = next(
        (
            child
            for child in node.children
            if child.kind == 'model'
            and 'turn_index' not in child.detail
            and child.started_at is None
        ),
        None,
    )
    if exchange is None:
        return
    # A prompt placeholder and a selected route do not prove a provider call.
    # Deterministic jobs have both, but no lifecycle event or provider usage.
    # Explicit calls are handled above by turn/call identity, including zero usage.
    if node.tokens is None or not any(
        (
            node.tokens.input_tokens,
            node.tokens.output_tokens,
            node.tokens.cache_read_tokens,
            node.tokens.cache_creation_tokens,
        )
    ):
        exchange.kind = 'working'
        exchange.name = 'Run context'
        exchange.status = node.status
        exchange.started_at = node.started_at
        exchange.ended_at = node.ended_at
        exchange.detail['phase'] = 'request_context'
        return
    routing = next((child for child in node.children if child.kind == 'routing'), None)
    if routing is None or routing.started_at is None:
        return
    start = routing.started_at
    end_node = next(
        (
            child
            for child in node.children
            if child.started_at is not None
            and child.started_at >= start
            and (
                child.kind == 'tool'
                or (child.kind == 'working' and child.detail.get('phase') == 'executing_actions')
            )
        ),
        None,
    )
    ended_at = end_node.started_at if end_node is not None else node.ended_at
    if ended_at is None:
        return
    exchange.name = 'Model call 1' if run_event is None else _model_call_label(run_event, 0)
    exchange.started_at = start
    exchange.ended_at = ended_at
    exchange.duration_ms = _elapsed_ms(start, ended_at)
    exchange.status = (
        'completed' if node.status == 'completed' or end_node is not None else 'running'
    )
    if exchange.tokens is None:
        exchange.tokens = node.tokens.model_copy(deep=True)


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


def _sanitize_public_text_fields(node: TraceNode) -> None:
    for field in ('prompt', 'response'):
        value = node.detail.get(field)
        if not isinstance(value, str):
            continue
        safe_text, keys = _replace_private_placeholders(value)
        node.detail[field] = safe_text
        if keys:
            node.detail[f'{field}_private_keys'] = keys
    for child in node.children:
        _sanitize_public_text_fields(child)


def _replace_private_placeholders(value: str) -> tuple[str, list[str]]:
    keys: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = next(group for group in match.groups() if group is not None)
        if key not in keys:
            keys.append(key)
        return '[PRIVATE]'

    return _PRIVATE_PLACEHOLDER_PATTERN.sub(replace, value), keys


def _trace_projection(event: Event) -> str | None:
    """Resolve a public enrichment phase before falling back to its event type."""
    if event.type == 'progress_update':
        stage = event.payload.get('stage')
        if stage == 'model_call_started':
            return 'trace.model_started'
        if stage == 'model_call_completed':
            return 'trace.model_completed'
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
        node.name = _run_name(event.payload)
        if scope_identity:
            node.detail.update(_child_run_identity(event.payload))
        _fold_model_prompt(node, event)
        return
    if projected in {'trace.run_completed', 'trace.run_failed'}:
        if projected == 'trace.run_completed':
            _fold_model_final(node, event)
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
    if _fold_model_event(node, event, projected):
        return
    kind = _ASPECT_KINDS.get(projected)
    if kind is not None:
        _fold_aspect(node, event, kind)


def _fold_model_event(node: TraceNode, event: Event, projected: str) -> bool:
    handlers = {
        'trace.model_stream': _fold_model_stream,
        'trace.model_started': _fold_model_started,
        'trace.model_completed': _fold_model_completed,
    }
    handler = handlers.get(projected)
    if handler is None:
        return False
    handler(node, event)
    return True


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


def _identified_model_exchange(
    node: TraceNode,
    model_children: list[TraceNode],
    model_call_id: str,
    turn_index: int | None,
) -> TraceNode:
    for child in model_children:
        if child.detail.get('model_call_id') == model_call_id:
            return child
    placeholder = next(
        (
            child
            for child in model_children
            if child.started_at is None and 'model_call_id' not in child.detail
        ),
        None,
    )
    if placeholder is not None:
        placeholder.detail.update(model_call_id=model_call_id, turn_index=turn_index)
        return placeholder
    exchange = TraceNode(
        node_id=f'model--{node.node_id}--call-{model_call_id}',
        kind='model',
        name='Model call',
        status='running',
        detail={'model_call_id': model_call_id, 'turn_index': turn_index},
    )
    node.children.append(exchange)
    return exchange


def _model_exchange(
    node: TraceNode,
    *,
    turn_index: int | None = None,
    model_call_id: str | None = None,
) -> TraceNode:
    model_children = [child for child in node.children if child.kind == 'model']
    if model_call_id is not None:
        return _identified_model_exchange(node, model_children, model_call_id, turn_index)
    if turn_index is not None:
        for child in model_children:
            if child.detail.get('turn_index') == turn_index:
                return child
        if turn_index == 0 and len(model_children) == 1 and model_children[0].started_at is None:
            model_children[0].detail['turn_index'] = turn_index
            return model_children[0]
    elif model_children:
        running = next(
            (child for child in reversed(model_children) if child.status == 'running'),
            None,
        )
        return running or model_children[-1]
    node_id = f'model--{node.node_id}'
    if turn_index is not None and turn_index > 0:
        node_id = f'{node_id}--turn-{turn_index + 1}'
    exchange = TraceNode(
        node_id=node_id,
        kind='model',
        name='Model call' if turn_index is not None else 'Model exchange',
        status='running',
        detail={} if turn_index is None else {'turn_index': turn_index},
    )
    node.children.append(exchange)
    return exchange


def _model_call_label(event: Event, turn_index: int) -> str:
    """Name a model call by where its run sits, relative to that run's parent.

    `Model call {turn + 1}` alone is per-run, so every run's first call is "Model call
    1". Decomposition puts several runs in one tree, and adjacent siblings then render
    the same label - the trace reads as one run calling the model twice.

    A decomposed run is named DEPTH.INDEX, both one-based, so the three subsystem jobs
    of a graph read 1.1, 1.2, 1.3 and a job nested inside the first reads 2.1. The root
    run has no job coordinates and keeps a plain number.

    PARENT-RELATIVE, not globally unique: `job_index` counts within one parent, so two
    grandchildren under different parents are both 2.1. That is a real collision and
    the tree's nesting is what separates them - a globally unique coordinate would have
    to encode the whole path, which is longer than the label it replaces and reads as
    an identifier rather than a position. Sibling confusion was the reported problem;
    cousins were never adjacent.

    The turn is appended only for a run that actually takes more than one, because a
    trailing `.1` on every single-call run is noise that carries nothing.
    """
    turn = turn_index + 1
    if event.job_depth == 0:
        return f'Model call {turn}'
    coordinates = f'{event.job_depth}.{event.job_index + 1}'
    return f'Model call {coordinates}' if turn == 1 else f'Model call {coordinates} turn {turn}'


def _fold_model_started(node: TraceNode, event: Event) -> None:
    turn_index = event.payload.get('turn_index')
    if not isinstance(turn_index, int) or turn_index < 0:
        return
    call_id = event.payload.get('model_call_id')
    exchange = _model_exchange(
        node,
        turn_index=turn_index,
        model_call_id=call_id if isinstance(call_id, str) and call_id else None,
    )
    ordinal = event.payload.get('model_call_ordinal')
    display_ordinal = ordinal if isinstance(ordinal, int) and ordinal >= 0 else turn_index
    # Independent internal calls can restart their local ordinal. Keep their
    # measured identities intact but assign distinct human labels within a run.
    occupied_names = {child.name for child in node.children if child is not exchange}
    while _model_call_label(event, display_ordinal) in occupied_names:
        display_ordinal += 1
    exchange.name = _model_call_label(event, display_ordinal)
    exchange.status = 'running'
    exchange.started_at = event.ts
    exchange.ended_at = None
    exchange.duration_ms = None
    # A model node can exist before it starts: _model_exchange adopts an
    # unstamped placeholder created by an earlier model event, and that
    # placeholder sits wherever it was first appended - ahead of the routing
    # node that chose the model. Ordering by started_at normally corrects
    # that, but only while the two differ. Routing and model-call-started are
    # emitted back to back and land on the same millisecond often enough to
    # see, and a stable sort cannot reorder a tie, so the trace showed a model
    # call above the routing decision that produced it. Moving the node to the
    # point it actually starts makes fold order causal, so the tie resolves
    # correctly instead of exposing where the placeholder happened to sit.
    # Identity, not equality: `list.remove` on pydantic models compares by
    # value, and two unstarted model placeholders are equal by value.
    for index, child in enumerate(node.children):
        if child is exchange:
            del node.children[index]
            break
    node.children.append(exchange)
    routing = next((child for child in reversed(node.children) if child.kind == 'routing'), None)
    routed_model = event.payload.get('model') or (
        None if routing is None else routing.detail.get('model')
    )
    if isinstance(routed_model, str) and routed_model:
        exchange.detail['model'] = routed_model


def _fold_model_completed(node: TraceNode, event: Event) -> None:
    turn_index = event.payload.get('turn_index')
    if not isinstance(turn_index, int) or turn_index < 0:
        return
    call_id = event.payload.get('model_call_id')
    exchange = _model_exchange(
        node,
        turn_index=turn_index,
        model_call_id=call_id if isinstance(call_id, str) and call_id else None,
    )
    status = event.payload.get('model_call_status')
    exchange.status = status if status in {'failed', 'cancelled'} else 'completed'
    error_code = event.payload.get('model_error_code')
    if isinstance(error_code, str) and error_code:
        exchange.detail['error_code'] = error_code
    exchange.ended_at = event.ts
    exchange.duration_ms = (
        event.latency_ms
        if event.latency_ms is not None
        else _elapsed_ms(exchange.started_at, event.ts)
    )
    served_model = event.payload.get('model')
    if isinstance(served_model, str) and served_model:
        exchange.detail['model'] = served_model
    if isinstance(event.payload.get('call_usage'), Mapping):
        exchange.tokens = _tokens({'usage': event.payload['call_usage']})
        return
    if isinstance(call_id, str) and call_id:
        # Request-local identity requires request-local usage evidence. A run's
        # cumulative counters cannot fill in a missing provider receipt.
        exchange.tokens = None
        return
    cumulative = _tokens(event.payload)
    if cumulative is None:
        return
    # Lifecycle counters describe the run so far. Preserve their evidence,
    # while displaying only the current call's contribution. Each run node
    # owns its baseline; nested or concurrent sibling runs never share it.
    exchange.detail['cumulative_usage'] = cumulative.model_dump()
    previous = next(
        (
            child
            for child in node.children
            if child.kind == 'model' and child.detail.get('turn_index') == turn_index - 1
        ),
        None,
    )
    baseline = None if previous is None else previous.detail.get('cumulative_usage')
    if turn_index == 0:
        exchange.tokens = cumulative
    elif isinstance(baseline, dict):
        baseline_counts = cast('dict[str, int]', baseline)
        cumulative_counts = cast('dict[str, int]', cumulative.model_dump())
        counts = {key: value - baseline_counts[key] for key, value in cumulative_counts.items()}
        exchange.tokens = TraceTokens(**counts) if min(counts.values()) >= 0 else None
    else:
        # Missing lifecycle history cannot establish one call's token count.
        exchange.tokens = None


def _fold_model_prompt(node: TraceNode, event: Event) -> None:
    trace_input_scope = event.payload.get('trace_input_scope')
    protected_internal_input = event.payload.get('protected_internal_input') is True
    if event.parent_session_id is not None and not (
        trace_input_scope == 'request_context' and protected_internal_input
    ):
        return
    messages = event.payload.get('trace_messages')
    if not isinstance(messages, list | tuple):
        return
    public_messages: list[dict[str, str]] = []
    for item in cast('Iterable[object]', messages):
        if not isinstance(item, Mapping):
            continue
        message = cast('Mapping[str, object]', item)
        role = message.get('role')
        content = message.get('content')
        if role == 'system' or not isinstance(role, str) or not isinstance(content, str):
            continue
        public_messages.append({'role': role, 'content': content[:_MAX_DETAIL_TEXT]})
    if not public_messages:
        return
    exchange = _model_exchange(node)
    exchange.detail['prompt'] = public_messages[-1]['content']
    if trace_input_scope == 'request_context':
        exchange.detail['input_scope'] = 'request_context'
        exchange.detail['protected_internal_input'] = True


def _fold_model_stream(node: TraceNode, event: Event) -> None:
    stage = event.payload.get('stage')
    if stage not in {'model_stream', 'final_response_stream'}:
        return
    if event.payload.get('trace_public_response') is not True:
        return
    delta = event.payload.get('content_delta')
    if not isinstance(delta, str) or not delta:
        return
    exchange = _model_exchange(node)
    if (
        'turn_index' in exchange.detail
        and exchange.started_at is not None
        and 'time_to_first_token_ms' not in exchange.detail
    ):
        ttft = _elapsed_ms(exchange.started_at, event.ts)
        if ttft is not None:
            exchange.detail['time_to_first_token_ms'] = ttft
    buffered = bool(event.payload.get('buffered_final_response'))
    if buffered and exchange.detail.get('chunk_count'):
        return
    if exchange.started_at is None:
        exchange.started_at = event.ts
    exchange.ended_at = event.ts
    exchange.detail['response'] = (str(exchange.detail.get('response') or '') + delta)[
        :_MAX_DETAIL_TEXT
    ]
    exchange.detail['chunk_count'] = int(exchange.detail.get('chunk_count') or 0) + 1
    exchange.detail['streaming'] = not buffered
    exchange.detail['delivery'] = 'buffered replay' if buffered else 'live stream'


def _fold_model_final(node: TraceNode, event: Event) -> None:
    if event.payload.get('trace_public_response') is not True:
        return
    message = event.payload.get('trace_message')
    if not isinstance(message, Mapping):
        return
    content = cast('Mapping[str, object]', message).get('content')
    if not isinstance(content, str) or not content:
        return
    exchange = _model_exchange(node)
    exchange.started_at = exchange.started_at or event.ts
    if 'turn_index' not in exchange.detail:
        exchange.ended_at = event.ts
    exchange.status = 'completed'
    exchange.detail['response'] = content[:_MAX_DETAIL_TEXT]
    exchange.detail.setdefault('chunk_count', 0)
    exchange.detail.setdefault('streaming', False)


def _elapsed_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if started_at is None or ended_at is None:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        ended = datetime.fromisoformat(ended_at.replace('Z', '+00:00'))
    except ValueError:
        return None
    return max(0, round((ended - started).total_seconds() * 1000))


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
        node.detail = {**node.detail, **_curated_error_detail(event.payload)}
    if node.status == 'cancelled':
        _cancel_open_tools(open_tools, ended_at=event.ts)
    _close_unanswered_interrupts(node, ended_at=event.ts)
    tokens = _tokens(event.payload)
    if tokens is not None:
        node.tokens = tokens


def _curated_error_detail(payload: Mapping[str, Any]) -> dict[str, str]:
    """Retain only bounded, user-facing failure fields in a trace node."""
    detail: dict[str, str] = {}
    for key in ('error_type', 'reason', 'message'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            detail[key] = value[:500]
    return detail


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
    pause.duration_ms = _elapsed_ms(pause.started_at, ended_at)
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
            child.duration_ms = _elapsed_ms(child.started_at, ended_at)


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
    detail = _aspect_detail(event, kind)
    if kind == 'shield':
        redacted_keys = detail.get('redacted_keys')
        if isinstance(redacted_keys, list):
            _apply_redaction_receipt(node, cast('list[object]', redacted_keys))
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


def _document_aspect_detail(event: Event, phase: object) -> dict[str, Any]:
    """Project document-only counters only for their closed document phase."""
    if not isinstance(phase, str):
        return {}
    keys = _DOCUMENT_ASPECT_DETAIL_KEYS.get(phase, ())
    memory_value = event.payload.get('memory')
    if not keys or not isinstance(memory_value, Mapping):
        return {}
    memory_payload = cast('Mapping[str, object]', memory_value)
    return {
        key: _sanitize_detail_value(memory_payload[key]) for key in keys if key in memory_payload
    }


def _aspect_detail(  # noqa: C901 - closed projection over the trace aspect vocabulary.
    event: Event,
    kind: TraceNodeKind,
) -> dict[str, Any]:
    if kind == 'hook':
        return {
            key: _sanitize_detail_value(event.payload[key])
            for key in _HOOK_DETAIL_KEYS
            if key in event.payload
        }
    if kind == 'routing':
        return {
            key: _sanitize_detail_value(event.payload[key])
            for key in _ROUTING_DETAIL_KEYS
            if key in event.payload
        }
    detail: dict[str, Any] = {}
    phase = event.payload.get('phase')
    if isinstance(phase, str) and phase:
        detail['phase'] = phase
    for key in _ASPECT_DETAIL_KEYS:
        if key in event.payload:
            detail[key] = _sanitize_detail_value(event.payload[key])
    # Memory-family events nest their counters one level down, under `memory`
    # (see DurableMemoryRetrievalDetails and its resource/extraction siblings),
    # so the top-level sweep above finds nothing and the node collapses to a
    # bare {'phase': 'memory_retrieved'} marker. Every other aspect in the tree
    # carries its numbers; memory was the one that did not, which made
    # "Memory retrieved" the only node users could not learn anything from.
    #
    # Same allowlist, same sanitiser: only the counter keys already declared in
    # _ASPECT_DETAIL_KEYS cross over, so recalled skill and insight CONTENT
    # stays out of the trace. That content is caller-supplied and the trace
    # crosses to staff (see _TENANT_VALUE_KEYS), so counts may travel and text
    # may not. Top-level values win when both are present.
    memory_payload = event.payload.get('memory')
    if isinstance(memory_payload, Mapping):
        memory_detail = cast('Mapping[str, object]', memory_payload)
        for key in _ASPECT_DETAIL_KEYS:
            if key in memory_detail and key not in detail:
                detail[key] = _sanitize_detail_value(memory_detail[key])
    detail.update(_document_aspect_detail(event, phase))
    if kind == 'shield':
        redaction = event.payload.get('redaction')
        if isinstance(redaction, Mapping):
            redaction_detail = cast('Mapping[str, object]', redaction)
            count = redaction_detail.get('redacted_value_count')
            keys = redaction_detail.get('redacted_keys') or redaction_detail.get('inserted_keys')
            if isinstance(count, int) and count >= 0:
                detail['redacted_value_count'] = count
            if isinstance(keys, list | tuple):
                key_values = cast('Iterable[object]', keys)
                detail['redacted_keys'] = sorted(
                    {key.strip() for key in key_values if isinstance(key, str) and key.strip()}
                )
    return detail


def _apply_redaction_receipt(node: TraceNode, redacted_keys: list[object]) -> None:
    """Remove dynamic private values from the tool immediately preceding its receipt."""
    keys = {key.strip() for key in redacted_keys if isinstance(key, str) and key.strip()}
    if not keys:
        return
    tool = next((child for child in reversed(node.children) if child.kind == 'tool'), None)
    if tool is None:
        return
    tool.detail = cast('dict[str, Any]', _redact_matching_keys(tool.detail, keys))


def _redact_matching_keys(value: object, keys: set[str]) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for raw_key, item in cast('Mapping[object, object]', value).items():
            key = str(raw_key)
            matches = key in keys or any(path.endswith(f'.{key}') for path in keys)
            redacted[key] = '[REDACTED]' if matches else _redact_matching_keys(item, keys)
        return redacted
    if isinstance(value, list | tuple):
        return [_redact_matching_keys(item, keys) for item in cast('Iterable[object]', value)]
    return value


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
        detail=_tool_detail(payload, tool_type=tool_type),
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
        **_tool_completion_detail(event.payload, failed=status == 'failed'),
    }
    if event.latency_ms is not None:
        tool.duration_ms = event.latency_ms
    if status == 'completed' and _is_human_input_tool(tool):
        _resolve_waiting_interrupt(node, tool, ended_at=event.ts)


def _tool_detail(payload: Mapping[str, Any], *, tool_type: str) -> dict[str, Any]:
    """Return bounded tool arguments after defensive field-level scrubbing."""
    detail: dict[str, Any] = {'tool_type': tool_type}
    tool_call = payload.get('tool_call')
    if not isinstance(tool_call, Mapping):
        return detail
    arguments = cast('Mapping[str, object]', tool_call).get('arguments')
    if not isinstance(arguments, Mapping):
        return detail
    names = cast('Mapping[str, object]', arguments)
    detail.update(
        {
            'argument_names': sorted(str(key) for key in names),
            'arguments': _sanitize_detail_value(names),
        }
    )
    return detail


def _tool_completion_detail(payload: Mapping[str, Any], *, failed: bool) -> dict[str, Any]:
    outcome = payload.get('outcome')
    outcome_mapping: Mapping[str, object] = (
        cast('Mapping[str, object]', outcome) if isinstance(outcome, Mapping) else {}
    )
    if failed:
        error = outcome_mapping.get('error', cast('object', payload.get('error')))
        return {'error': _sanitize_detail_value(error)} if error is not None else {}
    result = outcome_mapping.get('result', cast('object', payload.get('result')))
    return {'result': _sanitize_detail_value(result)} if result is not None else {}


def _sanitize_detail_value(value: object, *, depth: int = 0, key: str | None = None) -> object:
    """Bound trace detail and redact fields that can carry secrets or internals."""
    if key is not None and any(part in key.lower() for part in _SENSITIVE_DETAIL_KEY_PARTS):
        sanitized: object = '[REDACTED]'
    elif depth >= _MAX_DETAIL_DEPTH:
        sanitized = '[TRUNCATED]'
    elif value is None or isinstance(value, bool | int | float):
        sanitized = value
    elif isinstance(value, str):
        sanitized = _replace_private_placeholders(value[:_MAX_DETAIL_TEXT])[0]
    elif isinstance(value, Mapping):
        items = list(cast('Mapping[object, object]', value).items())[:_MAX_DETAIL_ITEMS]
        sanitized = {
            str(item_key): _sanitize_detail_value(
                item_value,
                depth=depth + 1,
                key=str(item_key),
            )
            for item_key, item_value in items
        }
    elif isinstance(value, list | tuple | set):
        sanitized = [
            _sanitize_detail_value(item, depth=depth + 1)
            for item in list(cast('Iterable[object]', value))[:_MAX_DETAIL_ITEMS]
        ]
    else:
        sanitized = str(value)[:_MAX_DETAIL_TEXT]
    return sanitized


def _child_run_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Say WHAT KIND of run this is, for runs that are not the root.

    A tool job and a swarm member are both child runs at a job depth, and the trace
    rendered them identically - so a decomposed graph and a fanned-out swarm produced
    the same picture, and neither could be told from the other while reading it.

    Structural only, exactly like tool and model names: which kind of run, which plan
    node cut it, how deep. No arguments, no results, nothing a tenant authored.
    """
    run_config = payload.get('run_config')
    if not isinstance(run_config, Mapping):
        return {}
    config = cast('Mapping[str, object]', run_config)
    identity: dict[str, Any] = {}
    # WHICH KIND OF SCOPE ran, not just its name. `_run_name` returns `agent_id` or
    # `swarm_id` as a bare string and discards which it was, so nothing downstream could
    # tell a swarm root from an agent - counting them once reported a swarm root plus two
    # delegates as three agents, and a trace cannot be grouped by scope without it.
    if isinstance(config.get('swarm_id'), str) and config.get('swarm_id'):
        identity['scope_type'] = 'swarm'
    elif isinstance(config.get('agent_id'), str) and config.get('agent_id'):
        identity['scope_type'] = 'agent'
    kind = config.get('child_run_kind')
    # 'root' carries no information a reader needs - it is the absence of a parent,
    # which the tree already shows.
    if isinstance(kind, str) and kind and kind != 'root':
        identity['child_run_kind'] = kind
    plan_node_id = config.get('plan_node_id')
    if isinstance(plan_node_id, str) and plan_node_id:
        identity['plan_node_id'] = plan_node_id
    depth = config.get('decomposition_depth')
    if isinstance(depth, int):
        identity['decomposition_depth'] = depth
    return identity


def _run_name(payload: Mapping[str, Any]) -> str:
    run_config = payload.get('run_config')
    if isinstance(run_config, Mapping):
        config = cast('Mapping[str, object]', run_config)
        for key in ('agent_id', 'swarm_id'):
            value = config.get(key)
            if isinstance(value, str) and value:
                return value
    return 'Run'


def _tokens(payload: Mapping[str, Any]) -> TraceTokens | None:
    usage = payload.get('usage')
    if not isinstance(usage, Mapping):
        return None
    counts = cast('Mapping[str, object]', usage)

    def count(key: str) -> int:
        value = counts.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    return TraceTokens(
        input_tokens=count('input_tokens'),
        output_tokens=count('output_tokens'),
        cache_read_tokens=count('cache_read_input_tokens'),
        cache_creation_tokens=count('cache_creation_input_tokens'),
    )


_TraceT = TypeVar('_TraceT', bound=SessionTrace)


def project_trace_for_staff(trace: _TraceT) -> _TraceT:
    """Return the trace with tenant payload values removed, for cross-tenant staff reads.

    A tenant inspecting its own run may see the values it supplied. Platform staff
    reading another tenant's run may not: the key-name denylist behind
    `_sanitize_detail_value` cannot be complete, so anything that carries caller-
    supplied content is dropped wholesale rather than filtered. Structure, names,
    status, timing, and token spend are preserved - that is what the Admin
    operations surface actually renders.
    """
    return trace.model_copy(
        deep=True,
        update={'root': _staff_node(trace.root)},
    )


def _staff_node(node: TraceNode) -> TraceNode:
    detail = {key: value for key, value in node.detail.items() if key not in _TENANT_VALUE_KEYS}
    return node.model_copy(
        deep=True,
        update={'detail': detail, 'children': [_staff_node(child) for child in node.children]},
    )


__all__ = [
    'RecursiveSessionTrace',
    'SessionTrace',
    'TraceNode',
    'TraceNodeKind',
    'TraceNodeStatus',
    'TraceTokens',
    'assemble_session_trace',
    'project_trace_for_staff',
]
