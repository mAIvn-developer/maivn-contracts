"""Assemble a security-relevant audit log from ordered canonical events.

The audit projection is deliberately narrower than an event inspector. It retains
who acted, what security-relevant action occurred, its resource and outcome, a
safe reason code, and lineage. Payload values never cross this boundary unless a
projection mapping explicitly allowlists a scalar code, count, or boolean.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from maivn_contracts.events.loaders import load_projection, project_event_type

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from maivn_contracts.events.model import Event

_SAFE_CODE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,127}$')
_SAFE_DETAIL_TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


class AuditLineage(BaseModel):
    """Canonical identifiers that relate an audit entry to its event lineage."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    session_id: StrictStr = Field(..., min_length=1)
    root_event_id: StrictStr = Field(..., min_length=1)
    parent_session_id: StrictStr | None = None
    trigger_id: StrictStr | None = None
    parent_trigger_id: StrictStr | None = None
    correlation_id: StrictStr | None = None


class AuditEntry(BaseModel):
    """One security-curated, payload-safe record in a session audit log."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    event_id: StrictStr = Field(..., min_length=1)
    actor: StrictStr = Field(..., min_length=1)
    action: StrictStr = Field(..., min_length=1)
    resource: StrictStr = Field(..., min_length=1)
    outcome: StrictStr = Field(..., min_length=1)
    reason_code: StrictStr | None = None
    ts: StrictStr = Field(..., min_length=1)
    lineage: AuditLineage
    details: dict[str, int | bool | str] = Field(default_factory=dict)


class SessionAuditLog(BaseModel):
    """The ordered audit projection for a session's canonical event family."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    session_id: StrictStr = Field(..., min_length=1)
    entries: list[AuditEntry] = Field(default_factory=list)


def assemble_session_audit(
    events: Sequence[Event],
    *,
    session_id: str,
) -> SessionAuditLog:
    """Fold ordered canonical events into security-curated audit entries."""
    entries = [entry for event in events if (entry := _assemble_entry(event)) is not None]
    return SessionAuditLog(session_id=session_id, entries=entries)


def _assemble_entry(event: Event) -> AuditEntry | None:
    if project_event_type(event.type, 'audit') is None:
        return None
    mappings = cast('dict[str, dict[str, Any]]', load_projection('audit')['mappings'])
    mapping = mappings[event.type]
    return AuditEntry(
        event_id=event.event_id,
        actor=event.actor,
        action=cast('str', mapping['action']),
        resource=_resource(event, mapping),
        outcome=cast('str', mapping['outcome']),
        reason_code=_reason_code(event.payload, mapping),
        ts=event.ts,
        lineage=AuditLineage(
            session_id=event.session_id,
            root_event_id=event.root_event_id,
            parent_session_id=event.parent_session_id,
            trigger_id=event.trigger_id,
            parent_trigger_id=event.parent_trigger_id,
            correlation_id=event.correlation_id,
        ),
        details=_safe_details(event.payload, mapping),
    )


def _resource(event: Event, mapping: Mapping[str, Any]) -> str:
    resource_type = cast('str', mapping['resource_type'])
    resource_field = mapping.get('resource_field')
    if isinstance(resource_field, str):
        value = event.payload.get(resource_field)
        if isinstance(value, str) and value:
            return f'{resource_type}:{value}'
    return f'{resource_type}:{event.session_id}'


def _reason_code(payload: Mapping[str, Any], mapping: Mapping[str, Any]) -> str | None:
    field = mapping.get('reason_code_field')
    if not isinstance(field, str):
        return None
    value = payload.get(field)
    return value if isinstance(value, str) and _SAFE_CODE.fullmatch(value) else None


def _safe_details(
    payload: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> dict[str, int | bool | str]:
    details: dict[str, int | bool | str] = {}
    fields = mapping.get('payload_fields', ())
    if not isinstance(fields, list):
        return details
    for field in cast('list[object]', fields):
        if not isinstance(field, str):
            continue
        value = payload.get(field)
        if isinstance(value, (bool, int)) or (
            isinstance(value, str) and _SAFE_DETAIL_TOKEN.fullmatch(value)
        ):
            details[field] = value
    return details


__all__ = [
    'AuditEntry',
    'AuditLineage',
    'SessionAuditLog',
    'assemble_session_audit',
]
