"""Canonical Event contract loaders, validators, and typed wire model.

This module owns the public Python interface for `libraries/maivn-contracts/events`.
It depends only on the checked-in JSON contract files, Pydantic, and
jsonschema. It does not import any other mAIvn runtime module.
"""

from __future__ import annotations

from maivn_contracts.events.audit import (
    AuditEntry,
    AuditLineage,
    SessionAuditLog,
    assemble_session_audit,
)
from maivn_contracts.events.billing import (
    BillingEntry,
    BillingLedger,
    BillingLineage,
    BillingUnitKind,
    assemble_billing,
)
from maivn_contracts.events.loaders import (
    load_event_schema,
    load_projection,
    load_taxonomy,
    project_event_type,
    validate_event,
)
from maivn_contracts.events.model import Event
from maivn_contracts.events.replay import (
    ReplayCoverage,
    ReplayFrame,
    ReplayFrameKind,
    ReplayLineage,
    SessionReplay,
    assemble_session_replay,
)
from maivn_contracts.events.trace import (
    RecursiveSessionTrace,
    SessionTrace,
    TraceNode,
    TraceNodeKind,
    TraceNodeStatus,
    TraceTokens,
    assemble_session_trace,
    project_trace_for_staff,
)

__all__ = [
    'AuditEntry',
    'AuditLineage',
    'BillingEntry',
    'BillingLedger',
    'BillingLineage',
    'BillingUnitKind',
    'Event',
    'RecursiveSessionTrace',
    'ReplayCoverage',
    'ReplayFrame',
    'ReplayFrameKind',
    'ReplayLineage',
    'SessionAuditLog',
    'SessionReplay',
    'SessionTrace',
    'TraceNode',
    'TraceNodeKind',
    'TraceNodeStatus',
    'TraceTokens',
    'assemble_billing',
    'assemble_session_audit',
    'assemble_session_replay',
    'assemble_session_trace',
    'load_event_schema',
    'load_projection',
    'load_taxonomy',
    'project_event_type',
    'project_trace_for_staff',
    'validate_event',
]
