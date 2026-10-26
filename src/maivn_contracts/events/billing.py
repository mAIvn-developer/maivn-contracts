"""Assemble payload-safe billable usage units from canonical events.

Billing is intentionally narrower than an event inspector. It retains only the
caller-supplied org/project scope, canonical lineage, unit kind, integer
quantity, timestamp, and source event id. No event payload content crosses this
boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from maivn_contracts.events.loaders import load_projection, project_event_type

if TYPE_CHECKING:
    from maivn_contracts.events.model import Event

BillingUnitKind = Literal['tokens', 'requests', 'storage', 'redaction', 'fires']


class BillingLineage(BaseModel):
    """Org/project scope and canonical identifiers for a billable unit."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    org_id: StrictStr = Field(..., min_length=1)
    project_id: StrictStr = Field(..., min_length=1)
    session_id: StrictStr = Field(..., min_length=1)
    root_event_id: StrictStr = Field(..., min_length=1)
    parent_session_id: StrictStr | None = None
    trigger_id: StrictStr | None = None
    parent_trigger_id: StrictStr | None = None
    correlation_id: StrictStr | None = None


class BillingEntry(BaseModel):
    """One integer billable usage unit derived from one canonical event."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    source_event_id: StrictStr = Field(..., min_length=1)
    unit_kind: BillingUnitKind
    quantity: StrictInt = Field(..., ge=1)
    ts: StrictStr = Field(..., min_length=1)
    lineage: BillingLineage


class BillingLedger(BaseModel):
    """The ordered billing projection for one org/project event family."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    org_id: StrictStr = Field(..., min_length=1)
    project_id: StrictStr = Field(..., min_length=1)
    entries: list[BillingEntry] = Field(default_factory=list)


def assemble_billing(
    events: Sequence[Event],
    *,
    org_id: str,
    project_id: str,
) -> BillingLedger:
    """Fold canonical events into integer-only billable usage entries."""
    entries: list[BillingEntry] = []
    for event in events:
        entries.extend(
            _assemble_entries(event, org_id=org_id, project_id=project_id),
        )
    return BillingLedger(org_id=org_id, project_id=project_id, entries=entries)


def _assemble_entries(event: Event, *, org_id: str, project_id: str) -> list[BillingEntry]:
    if project_event_type(event.type, 'billing') is None:
        return []

    mappings = cast('dict[str, dict[str, Any]]', load_projection('billing')['mappings'])
    mapping = mappings[event.type]
    units = mapping.get('units')
    if not isinstance(units, list):
        return []

    lineage = BillingLineage(
        org_id=org_id,
        project_id=project_id,
        session_id=event.session_id,
        root_event_id=event.root_event_id,
        parent_session_id=event.parent_session_id,
        trigger_id=event.trigger_id,
        parent_trigger_id=event.parent_trigger_id,
        correlation_id=event.correlation_id,
    )
    entries: list[BillingEntry] = []
    for raw_unit in cast('list[object]', units):
        if not isinstance(raw_unit, dict):
            continue
        unit = cast('dict[str, Any]', raw_unit)
        unit_kind = unit.get('unit_kind')
        if not isinstance(unit_kind, str):
            continue
        quantity = _quantity(event.payload, unit)
        if quantity is None or quantity < 1:
            continue
        entries.append(
            BillingEntry(
                source_event_id=event.event_id,
                unit_kind=cast('BillingUnitKind', unit_kind),
                quantity=quantity,
                ts=event.ts,
                lineage=lineage,
            ),
        )
    return entries


def _quantity(payload: Mapping[str, Any], unit: Mapping[str, Any]) -> int | None:
    fixed_quantity = unit.get('quantity')
    if isinstance(fixed_quantity, int) and not isinstance(fixed_quantity, bool):
        return fixed_quantity if fixed_quantity >= 0 else None

    quantity_field = unit.get('quantity_field')
    if isinstance(quantity_field, str):
        value = _integer_at_path(payload, quantity_field)
        return value if value is not None and value >= 0 else None

    quantity_fields = unit.get('quantity_fields')
    if not isinstance(quantity_fields, list):
        return None
    total = 0
    found = False
    for raw_field in cast('list[object]', quantity_fields):
        if not isinstance(raw_field, str):
            return None
        value = _integer_at_path(payload, raw_field, missing_is_zero=True)
        if value is None or value < 0:
            return None
        found = found or _path_exists(payload, raw_field)
        total += value
    return total if found else None


_MISSING = object()


def _value_at_path(payload: Mapping[str, Any], path: str) -> object:
    value: object = payload
    for part in path.split('.'):
        if not isinstance(value, Mapping) or part not in value:
            return _MISSING
        value = cast('Mapping[str, object]', value)[part]
    return value


def _integer_at_path(
    payload: Mapping[str, Any],
    path: str,
    *,
    missing_is_zero: bool = False,
) -> int | None:
    value = _value_at_path(payload, path)
    if value is _MISSING:
        return 0 if missing_is_zero else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _path_exists(payload: Mapping[str, Any], path: str) -> bool:
    return _value_at_path(payload, path) is not _MISSING


__all__ = [
    'BillingEntry',
    'BillingLedger',
    'BillingLineage',
    'BillingUnitKind',
    'assemble_billing',
]
