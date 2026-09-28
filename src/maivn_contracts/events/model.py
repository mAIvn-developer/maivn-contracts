"""Hand-authored Pydantic model for the canonical Event wire shape."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts import (
    ARTIFACT_LIFECYCLE_EVENT_TYPES,
)
from maivn_contracts.artifacts.lifecycle import parse_artifact_lifecycle_event_payload

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FrozenMapping(Mapping[str, Any]):
    """Recursively immutable JSON mapping that retains Mapping.get compatibility."""

    __slots__ = ('_data',)

    def __init__(self, value: Mapping[str, Any]) -> None:
        self._data = MappingProxyType({key: _freeze_json(item) for key, item in value.items()})

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __deepcopy__(self, memo: dict[int, Any]) -> _FrozenMapping:
        """Return this recursively immutable mapping during Pydantic deep copies."""
        del memo
        return self


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenMapping(cast('Mapping[str, Any]', value))
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in cast('list[Any]', value))
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        mapping = cast('Mapping[str, Any]', value)
        return {key: _thaw_json(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in cast('tuple[Any, ...]', value)]
    return value


EventType: TypeAlias = Literal[
    'tool_event',
    'interrupt_request',
    'interrupt_required',
    'assignment_received',
    'assignment_completed',
    'model_tool_complete',
    'heartbeat',
    'update',
    'progress_update',
    'model_routing',
    'status_message',
    'status_message_chunk',
    'final',
    'error',
    'system_tool_start',
    'system_tool_chunk',
    'system_tool_complete',
    'system_tool_error',
    'hook_fired',
    'enrichment',
    'evaluating',
    'planning',
    'searching_tools',
    'loading_tools',
    'planning_assignments',
    'executing_assignments',
    'executing_actions',
    'synthesizing',
    'finalizing',
    'reevaluate_accrued',
    'memory_summarizing',
    'memory_summarized',
    'memory_retrieving',
    'memory_retrieved',
    'memory_indexing',
    'memory_indexed',
    'memory_graph_extracting',
    'memory_skill_extracting',
    'memory_insight_extracting',
    'memory_skill_extracted',
    'memory_insight_extracted',
    'redaction_previewed',
    'message_redaction_applied',
    'resource_registering',
    'resource_registered',
    'resource_dedup_reused',
    'resource_version_superseded',
    'resource_extracting',
    'resource_extracted',
    'document_analysis_selected',
    'document_evidence_coverage',
    'trigger.fired',
    'trigger.skipped',
    'trigger.failed',
    'trigger.disabled',
    'trigger.enabled',
    'connection.event_received',
    'email.received',
    'conversation.reply_received',
    'memory.record_changed',
    'storage.object_uploaded',
    'trigger.fire_requested',
    'agent.thinking',
    'agent.tool_selected',
    'tool.dispatch_started',
    'tool.dispatch_completed',
    'agent.responded',
    'session.completed',
    'artifact.reserved',
    'artifact.uploaded',
    'artifact.validation_started',
    'artifact.validated',
    'artifact.available',
    'artifact.rejected',
    'artifact.failed',
    'artifact.selected',
    'artifact.delivery_queued',
    'artifact.delivery_started',
    'artifact.delivery_succeeded',
    'artifact.delivery_failed',
    'artifact.expired',
    'artifact.deletion_requested',
    'artifact.deletion_started',
    'artifact.deletion_pending_backup_expiry',
    'artifact.deleted',
    'artifact.delete_incomplete',
    'artifact.vault_authorization_pending',
    'artifact.vault_authorization_denied',
    'artifact.vault_render_started',
    'artifact.vault_render_failed',
]
Mode: TypeAlias = Literal['worker', 'webhook', 'hosted']
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]


class Event(BaseModel):
    """Canonical Event wire record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    event_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable unique identifier for this event record.',
        examples=['evt-01HY3K75PN8JMEQ5W1N6JAFM4C'],
    )
    ordinal: StrictStr = Field(
        ...,
        min_length=1,
        description=(
            'Per-producer monotonic or hybrid-logical-clock token; it is not a global '
            'gapless database sequence.'
        ),
        examples=['producer-agent-000001'],
    )
    type: EventType = Field(
        ...,
        description='Canonical event type from the event taxonomy.',
        examples=['planning'],
    )
    session_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Invocation or session identifier that owns this event.',
        examples=['ses-fire-0001'],
    )
    scenario_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional scenario identifier when the event belongs to a deployed scenario.',
        examples=['scn-customer-email-triage'],
    )
    trigger_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional trigger identifier when the event was caused by a trigger fire.',
        examples=['trg-inbound-email'],
    )
    root_event_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Root event identifier for cross-fire lineage and trigger-chain correlation.',
        examples=['evt-trigger-fired-0001'],
    )
    parent_session_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent session identifier for chained or nested invocations.',
        examples=['ses-fire-parent'],
    )
    parent_trigger_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent trigger identifier for chained trigger invocations.',
        examples=['trg-inbound-email'],
    )
    trigger_chain_depth: NonNegativeStrictInt = Field(
        ...,
        description=(
            'Depth of the trigger chain used for amplification guards and trace correlation.'
        ),
        examples=[1],
    )
    parent_assignment_uuid: StrictStr | None = Field(
        default=None,
        min_length=1,
        description=(
            'Optional parent assignment UUID for faithful swarm and nested-job reconstruction.'
        ),
        examples=['assign-parent-0005'],
    )
    job_depth: NonNegativeStrictInt = Field(
        ...,
        description='Execution-tree depth carried from build_config for nested assignment replay.',
        examples=[2],
    )
    job_index: NonNegativeStrictInt = Field(
        ...,
        description='Execution-tree sibling index carried from build_config for causal ordering.',
        examples=[1],
    )
    actor: StrictStr = Field(
        ...,
        min_length=1,
        description='Agent, node, trigger, or tool that emitted the event.',
        examples=['agent:triage'],
    )
    mode: Mode = Field(
        ...,
        description='Execution mode used for tool dispatch and canvas painting.',
        examples=['hosted'],
    )
    correlation_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional per-tool correlation identifier assigned at dispatch.',
        examples=['tool-call-0003'],
    )
    trace_id: StrictStr | None = Field(
        default=None,
        pattern=r'^[0-9a-f]{32}$',
        description=('Optional W3C/OpenTelemetry trace identifier for internal span correlation.'),
        examples=['4bf92f3577b34da6a3ce929d0e0e4736'],
    )
    payload: Mapping[str, Any] = Field(
        ...,
        description=(
            'Type-specific open payload for inspector rendering, inputs, outputs, and schemas.'
        ),
        examples=[{'phase': 'planning'}],
    )
    latency_ms: NonNegativeStrictInt | None = Field(
        default=None,
        description=(
            'Optional elapsed latency in milliseconds for connector animation and observability.'
        ),
        examples=[184],
    )
    ts: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when the event was emitted.',
        examples=['2026-07-01T14:00:00Z'],
    )

    @field_validator('trace_id')
    @classmethod
    def reject_zero_trace_id(cls, value: str | None) -> str | None:
        """Reject the invalid all-zero W3C/OpenTelemetry trace identifier."""
        if value == '0' * 32:
            msg = 'trace_id must not be the all-zero identifier'
            raise ValueError(msg)
        return value

    @model_validator(mode='after')
    def validate_artifact_lifecycle_payload(self) -> Event:
        """Bind every artifact event to its exact value-free lifecycle payload."""
        if self.type not in ARTIFACT_LIFECYCLE_EVENT_TYPES:
            return self
        payload = parse_artifact_lifecycle_event_payload(self.payload)
        if payload.event_type != self.type:
            message = 'artifact lifecycle payload event_type must equal Event.type'
            raise ValueError(message)
        object.__setattr__(self, 'payload', _FrozenMapping(payload.model_dump(mode='json')))
        return self

    @field_serializer('payload')
    def serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Serialize frozen artifact mappings and ordinary mappings as JSON objects."""
        return cast('dict[str, Any]', _thaw_json(value))
