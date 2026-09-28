"""Assemble a durable, curated session replay from positioned event records.

Replay preserves the event-spine append position as the client's resume currency,
but exposes only the fields needed to reconstruct a visible timeline. Canonical
payloads, tool arguments and results, stream chunks, and private internals never
cross this projection boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from maivn_contracts.events.loaders import load_projection, project_event_type

if TYPE_CHECKING:
    from maivn_contracts.events.model import Event

ReplayFrameKind = Literal[
    'tool_event',
    'interrupt_request',
    'interrupt_required',
    'assignment_received',
    'assignment_completed',
    'model_tool_complete',
    'progress_update',
    'model_routing',
    'status_message',
    'final',
    'error',
    'system_tool_start',
    'system_tool_complete',
    'system_tool_error',
    'redaction_previewed',
    'message_redaction_applied',
    'trigger.fired',
    'trigger.skipped',
    'trigger.failed',
    'trigger.disabled',
    'trigger.enabled',
    'tool.dispatch_started',
    'tool.dispatch_completed',
    'session.completed',
]

ReplayScalar = int | bool | str


class _PositionedEvent(Protocol):
    """Minimal event-spine shape required by the contracts package."""

    @property
    def position(self) -> int:
        """Durable event-spine position."""
        ...

    @property
    def event(self) -> Event:
        """The canonical event at this position."""
        ...


class ReplayLineage(BaseModel):
    """Canonical execution identifiers retained for replay reconstruction."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    session_id: StrictStr = Field(..., min_length=1)
    root_event_id: StrictStr = Field(..., min_length=1)
    parent_session_id: StrictStr | None = None
    trigger_id: StrictStr | None = None
    parent_trigger_id: StrictStr | None = None
    trigger_chain_depth: StrictInt = Field(..., ge=0)
    parent_assignment_uuid: StrictStr | None = None
    job_depth: StrictInt = Field(..., ge=0)
    job_index: StrictInt = Field(..., ge=0)
    correlation_id: StrictStr | None = None


class ReplayFrame(BaseModel):
    """One position-bearing, payload-curated visible timeline frame."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    event_id: StrictStr = Field(..., min_length=1)
    position: StrictInt = Field(..., ge=1)
    ts: StrictStr = Field(..., min_length=1)
    kind: ReplayFrameKind
    actor: StrictStr = Field(..., min_length=1)
    summary: dict[str, ReplayScalar] = Field(default_factory=dict)
    lineage: ReplayLineage


class ReplayCoverage(BaseModel):
    """Durable position span and explicit reasons for omitted events."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    first_position: StrictInt | None = Field(default=None, ge=1)
    last_position: StrictInt | None = Field(default=None, ge=1)
    dropped_count_by_reason: dict[str, StrictInt] = Field(default_factory=dict)


class SessionReplay(BaseModel):
    """The curated, ordered replay and its durable coverage metadata."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    session_id: StrictStr = Field(..., min_length=1)
    frames: list[ReplayFrame] = Field(default_factory=list)
    coverage: ReplayCoverage


def assemble_session_replay(
    events: Sequence[_PositionedEvent],
    *,
    session_id: str,
) -> SessionReplay:
    """Assemble a session-family replay in authoritative durable position order."""
    scoped = sorted(
        (
            entry
            for entry in events
            if session_id in {entry.event.session_id, entry.event.parent_session_id}
        ),
        key=lambda entry: entry.position,
    )
    mappings = cast('dict[str, dict[str, Any]]', load_projection('replay')['mappings'])
    frames: list[ReplayFrame] = []
    dropped: dict[str, int] = {}
    for entry in scoped:
        event = entry.event
        projected = project_event_type(event.type, 'replay')
        if projected is None:
            reason = cast('str', mappings[event.type]['drop_reason'])
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        frames.append(
            _assemble_frame(entry, cast('ReplayFrameKind', projected), mappings[event.type]),
        )

    positions = [entry.position for entry in scoped]
    return SessionReplay(
        session_id=session_id,
        frames=frames,
        coverage=ReplayCoverage(
            first_position=min(positions) if positions else None,
            last_position=max(positions) if positions else None,
            dropped_count_by_reason=dropped,
        ),
    )


def _assemble_frame(
    entry: _PositionedEvent,
    kind: ReplayFrameKind,
    mapping: Mapping[str, Any],
) -> ReplayFrame:
    event = entry.event
    return ReplayFrame(
        event_id=event.event_id,
        position=entry.position,
        ts=event.ts,
        kind=kind,
        actor=event.actor,
        summary=_summary(event, kind, mapping),
        lineage=ReplayLineage(
            session_id=event.session_id,
            root_event_id=event.root_event_id,
            parent_session_id=event.parent_session_id,
            trigger_id=event.trigger_id,
            parent_trigger_id=event.parent_trigger_id,
            trigger_chain_depth=event.trigger_chain_depth,
            parent_assignment_uuid=event.parent_assignment_uuid,
            job_depth=event.job_depth,
            job_index=event.job_index,
            correlation_id=event.correlation_id,
        ),
    )


def _summary(
    event: Event,
    kind: ReplayFrameKind,
    mapping: Mapping[str, Any],
) -> dict[str, ReplayScalar]:
    curated = mapping.get('curated_fields')
    fields: set[str] = (
        {field for field in cast('list[object]', curated) if isinstance(field, str)}
        if isinstance(curated, list)
        else set()
    )
    if kind in {
        'tool_event',
        'model_tool_complete',
        'system_tool_start',
        'system_tool_complete',
        'system_tool_error',
        'tool.dispatch_started',
        'tool.dispatch_completed',
    }:
        return _tool_summary(event, kind, fields)

    if kind == 'status_message':
        return _status_summary(event.payload, fields)

    if kind == 'model_routing':
        return _routing_summary(event, fields)

    if kind in {'final', 'error', 'session.completed'}:
        return _terminal_summary(event.payload, fields)

    if kind in {'redaction_previewed', 'message_redaction_applied'}:
        return _redaction_summary(event.payload, fields)

    return _generic_summary(event.payload, fields)


def _tool_summary(
    event: Event,
    kind: ReplayFrameKind,
    fields: set[str],
) -> dict[str, ReplayScalar]:
    summary: dict[str, ReplayScalar] = {}
    _put_string(summary, 'tool_name', _tool_name(event.payload), fields)
    status = _string(event.payload.get('status'))
    if status is None:
        status = {
            'system_tool_start': 'running',
            'system_tool_complete': 'completed',
            'system_tool_error': 'failed',
            'model_tool_complete': 'completed',
            'tool.dispatch_started': 'running',
            'tool.dispatch_completed': 'completed',
            'tool_event': 'completed',
        }.get(kind)
    _put_string(summary, 'status', status, fields)
    if 'duration_ms' in fields and event.latency_ms is not None:
        summary['duration_ms'] = event.latency_ms
    return summary


def _status_summary(
    payload: Mapping[str, Any],
    fields: set[str],
) -> dict[str, ReplayScalar]:
    summary: dict[str, ReplayScalar] = {}
    _put_string(
        summary,
        'message',
        _first_string(payload, ('message', 'data.text', 'text')),
        fields,
    )
    return summary


def _routing_summary(event: Event, fields: set[str]) -> dict[str, ReplayScalar]:
    summary: dict[str, ReplayScalar] = {}
    mode = _string(event.payload.get('mode')) or event.mode
    _put_string(summary, 'mode', mode, fields)
    _put_string(summary, 'profile', _string(event.payload.get('profile')), fields)
    return summary


def _terminal_summary(
    payload: Mapping[str, Any],
    fields: set[str],
) -> dict[str, ReplayScalar]:
    summary: dict[str, ReplayScalar] = {}
    _put_string(summary, 'stop_reason', _string(payload.get('stop_reason')), fields)
    _put_string(summary, 'reason_code', _string(payload.get('reason_code')), fields)
    usage = payload.get('usage')
    if isinstance(usage, Mapping):
        typed_usage = cast('Mapping[str, object]', usage)
        for field in (
            'input_tokens',
            'output_tokens',
            'cache_read_input_tokens',
            'cache_creation_input_tokens',
        ):
            value = _non_negative_int(typed_usage.get(field))
            if field in fields and value is not None:
                summary[field] = value
    return summary


def _redaction_summary(
    payload: Mapping[str, Any],
    fields: set[str],
) -> dict[str, ReplayScalar]:
    summary: dict[str, ReplayScalar] = {}
    for field in ('entity_count', 'redaction_count'):
        value = _non_negative_int(payload.get(field))
        if field in fields and value is not None:
            summary[field] = value
    return summary


def _generic_summary(
    payload: Mapping[str, Any],
    fields: set[str],
) -> dict[str, ReplayScalar]:
    summary: dict[str, ReplayScalar] = {}

    for field in fields:
        value = _scalar_at_path(payload, field)
        if value is not None:
            summary[field] = value
    return summary


def _tool_name(payload: Mapping[str, Any]) -> str | None:
    for path in ('tool_name', 'tool_type', 'name', 'tool_call.name'):
        value = _scalar_at_path(payload, path)
        if isinstance(value, str) and value:
            return value
    return None


def _first_string(payload: Mapping[str, Any], paths: Sequence[str]) -> str | None:
    for path in paths:
        value = _scalar_at_path(payload, path)
        if isinstance(value, str):
            return value
    return None


def _scalar_at_path(payload: Mapping[str, Any], path: str) -> ReplayScalar | None:
    value: object = payload
    for part in path.split('.'):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = cast('Mapping[str, object]', value)[part]
    return value if isinstance(value, (bool, int, str)) else None


def _put_string(
    summary: dict[str, ReplayScalar],
    field: str,
    value: str | None,
    fields: set[str],
) -> None:
    if field in fields and value is not None:
        summary[field] = value


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


__all__ = [
    'ReplayCoverage',
    'ReplayFrame',
    'ReplayFrameKind',
    'ReplayLineage',
    'SessionReplay',
    'assemble_session_replay',
]
