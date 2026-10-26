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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar, overload

from maivn_contracts.events._trace_fold import run_node
from maivn_contracts.events._trace_nodes import (
    RecursiveSessionTrace,
    SessionTrace,
    TraceNode,
    TraceNodeKind,
    TraceNodeStatus,
    TraceTokens,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from maivn_contracts.events.model import Event

# Recursive-assembly caps (S6 sessions trace): a pathological fan-out (e.g. a
# runaway trigger chain) must degrade to a bounded, deterministic truncation
# rather than an unbounded tree or an unbounded fold.
MAX_TRACE_DESCENDANT_SESSIONS = 200

MAX_TRACE_EVENTS = 20_000


# Detail keys whose values are caller-supplied and therefore never cross to staff.
_TENANT_VALUE_KEYS = frozenset(
    {
        'answer',
        'arguments',
        'error',
        'internal_narration',
        'output',
        'prompt',
        'question',
        'result',
        'transcript',
    },
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

    root = run_node(by_session.get(session_id, ()), session_id=session_id)
    for child_session, child_events in by_session.items():
        if child_session == session_id:
            continue
        first = child_events[0]
        if first.parent_session_id != session_id:
            continue
        root.children.append(run_node(child_events, session_id=child_session))
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
        sid: run_node(
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
