"""Hand-authored Pydantic models for scenario and trigger contracts."""

from __future__ import annotations

import calendar
import re
from importlib import import_module
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    StrictStr,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from maivn_contracts.artifacts.model import (
    ArtifactCustody,
    ArtifactKind,
    MimeType,
    OpaqueTokenId,
    is_mime_type_valid_for_artifact_kind,
)
from maivn_contracts.scenarios.connection_selectors import (
    ConnectionEventSelector,
    selector_supports_event,
)

if TYPE_CHECKING:
    from maivn_contracts.agents import AgentVersion, MessageBinding
    from maivn_contracts.flows import FlowGraph

PhaseOne: TypeAlias = Literal['phase_1']
PhaseTwo: TypeAlias = Literal['phase_2']
PhaseThree: TypeAlias = Literal['phase_3']
PhaseFour: TypeAlias = Literal['phase_4']
ChainedEventType: TypeAlias = Literal['session.completed', 'tool.dispatch_completed']
MemoryRecordKind: TypeAlias = Literal['skill', 'insight', 'resource_pointer', 'thread_message']
DataPlaneEventOperation: TypeAlias = Literal['inserted', 'updated']
SLAFireWhen: TypeAlias = Literal['condition_met', 'condition_missing']
StorageObjectKind: TypeAlias = Literal['source', 'artifact']
TriggerStatus: TypeAlias = Literal['enabled', 'paused', 'disabled']
TriggerPriority: TypeAlias = Literal['interactive', 'triggered', 'retry']
TriggerFireStatus: TypeAlias = Literal['pending', 'claimed', 'completed', 'failed', 'dead']
TriggerInvocationStatus: TypeAlias = Literal['completed', 'failed', 'dead']
TriggerOutcome: TypeAlias = Literal['success', 'failure', 'escalation']
BackoffStrategy: TypeAlias = Literal['fixed', 'exponential']
PositiveStrictInt: TypeAlias = Annotated[int, Field(ge=1, strict=True)]
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]
CoordinateValue: TypeAlias = int | float
EmailSenderPattern: TypeAlias = Annotated[
    StrictStr,
    Field(
        min_length=3,
        max_length=254,
        pattern=r"^(?:[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}|\*)@"
        r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+'
        r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$',
    ),
]


class _ScheduleSelectorError(ValueError):
    """Raised when a schedule source has zero or multiple selectors."""

    def __init__(self) -> None:
        """Build the invalid schedule selector error."""
        message = 'Exactly one of cron or interval_seconds must be set'
        super().__init__(message)


class _CronExpressionError(ValueError):
    """Raised when a cron expression cannot be scheduled by the event plane."""

    def __init__(self, detail: str) -> None:
        """Build an actionable cron validation error."""
        super().__init__(f'Invalid cron expression: {detail}')


_CRON_FIELDS: tuple[tuple[int, int, dict[str, int]], ...] = (
    (0, 59, {}),
    (0, 23, {}),
    (1, 31, {}),
    (
        1,
        12,
        {
            name: index
            for index, name in enumerate(
                (
                    'jan',
                    'feb',
                    'mar',
                    'apr',
                    'may',
                    'jun',
                    'jul',
                    'aug',
                    'sep',
                    'oct',
                    'nov',
                    'dec',
                ),
                start=1,
            )
        },
    ),
    (
        0,
        6,
        {
            name: index
            for index, name in enumerate(
                ('sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'),
            )
        },
    ),
)
_CRON_DESCRIPTORS = frozenset(
    ('@yearly', '@annually', '@monthly', '@weekly', '@daily', '@midnight', '@hourly'),
)
_CRON_RANGE = re.compile(r'([*?]|[0-9]+|[a-zA-Z]{3})(?:-([0-9]+|[a-zA-Z]{3}))?(?:/([0-9]+))?')
_MAX_CRON_STEP = 2**63 - 1


def _cron_field_values(field: str, minimum: int, maximum: int, names: dict[str, int]) -> set[int]:
    values: set[int] = set()
    for part in field.split(','):
        match = _CRON_RANGE.fullmatch(part)
        if match is None:
            message = f'invalid field {field!r}'
            raise _CronExpressionError(message)
        low, high, stride = match.groups()
        step = int(stride) if stride is not None else 1
        if not 1 <= step <= _MAX_CRON_STEP:
            message = 'steps must be positive 64-bit integers'
            raise _CronExpressionError(message)
        if low in ('*', '?'):
            if high is not None:
                message = 'wildcards cannot start a range'
                raise _CronExpressionError(message)
            start, end = minimum, maximum
        else:
            start = names.get(low.lower(), -1) if low.isalpha() else int(low)
            end = start if stride is None else maximum
            if high is not None:
                end = names.get(high.lower(), -1) if high.isalpha() else int(high)
        if not minimum <= start <= end <= maximum:
            message = f'field {field!r} must be within {minimum}..{maximum}'
            raise _CronExpressionError(message)
        values.update(range(start, end + 1, step))
    return values


def _validate_cron_expression(value: str) -> None:
    """Match the event plane's five-field cron parser, with no seconds or @every."""
    expression = value.strip()
    if expression.startswith(('CRON_TZ=', 'TZ=')):
        prefix, separator, expression = expression.partition(' ')
        timezone = prefix.split('=', maxsplit=1)[1]
        if not separator or not timezone:
            message = 'timezone prefix requires a zone and expression'
            raise _CronExpressionError(message)
        if timezone not in ('UTC', 'Local'):
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                message = f'unknown or unavailable timezone {timezone!r}'
                raise _CronExpressionError(message) from exc
        expression = expression.strip()
    if expression in _CRON_DESCRIPTORS:
        return
    fields = expression.split()
    if len(fields) != len(_CRON_FIELDS):
        message = 'expected five fields or a supported calendar descriptor'
        raise _CronExpressionError(message)
    parsed = [
        _cron_field_values(field, minimum, maximum, names)
        for field, (minimum, maximum, names) in zip(fields, _CRON_FIELDS, strict=True)
    ]
    # A restricted weekday is ORed with a restricted day of month by robfig/cron.
    weekday_wildcard = any(
        part.split('/')[0] in ('*', '?') and ('/' not in part or int(part.split('/')[1]) == 1)
        for part in fields[4].split(',')
    )
    if weekday_wildcard and not any(
        day <= calendar.monthrange(2000, month)[1] for month in parsed[3] for day in parsed[2]
    ):
        message = 'day of month never occurs in the selected months'
        raise _CronExpressionError(message)


class _LegacyExternalToolSnapshotError(ValueError):
    """Raised when a launch would guess missing external tool dispatch metadata."""

    def __init__(self) -> None:
        """Build the fail-closed legacy external snapshot error."""
        message = 'legacy_external_tool_snapshot_incomplete'
        super().__init__(message)


class _DuplicateEmailSenderError(ValueError):
    """Raised when an email trigger repeats a sender selector."""

    def __init__(self) -> None:
        """Build the duplicate sender-selector error."""
        message = 'sender_allowlist entries must be distinct'
        super().__init__(message)


class ScheduleSource(BaseModel):
    """Phase 1 schedule trigger source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['schedule'] = Field(..., description='Trigger source kind.')
    phase: PhaseOne = Field(..., description='Phase note for this source kind.')
    cron: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Cron expression for scheduled firing.',
    )
    interval_seconds: PositiveStrictInt | None = Field(
        default=None,
        le=31536000,
        description='Fixed interval in seconds for scheduled firing.',
    )
    jitter_seconds: NonNegativeStrictInt = Field(
        default=60,
        le=3600,
        description='Creation-time jitter window in seconds.',
    )

    @field_validator('cron')
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_cron_expression(value)
        return value

    @model_validator(mode='after')
    def _validate_exactly_one_schedule(self) -> ScheduleSource:
        has_cron = self.cron is not None
        has_interval = self.interval_seconds is not None
        if has_cron == has_interval:
            raise _ScheduleSelectorError
        return self


class WebhookSource(BaseModel):
    """Phase 1 inbound webhook trigger source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['webhook'] = Field(..., description='Trigger source kind.')
    phase: PhaseOne = Field(..., description='Phase note for this source kind.')
    secret_ref: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^vault://',
        description='Vault reference for the inbound webhook HMAC secret.',
    )


class ManualSource(BaseModel):
    """Phase 1 manual trigger source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['manual'] = Field(..., description='Trigger source kind.')
    phase: PhaseOne = Field(..., description='Phase note for this source kind.')


class ChainedEventSource(BaseModel):
    """Phase 3 same-project canonical completion-event source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['chained_event'] = Field(..., description='Trigger source kind.')
    phase: PhaseThree = Field(..., description='Phase note for this source kind.')
    event_type: ChainedEventType = Field(
        ...,
        description='Canonical completion event that can admit the child trigger.',
    )
    origin_trigger_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional same-project upstream trigger selector.',
    )


class ExternalConnectionEventSource(BaseModel):
    """Phase 2 same-project normalized external connection event source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['external_connection_event'] = Field(..., description='Trigger source kind.')
    phase: PhaseTwo = Field(..., description='Phase note for this source kind.')
    connection_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$',
        description='Opaque same-project connection selector.',
    )
    event_type: StrictStr = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r'^[a-z][a-z0-9_.-]{0,127}$',
        description='Normalized provider event machine identifier.',
    )
    table: StrictStr | None = Field(
        default=None,
        pattern=r'^[A-Za-z_][A-Za-z0-9_$]{0,62}\.[A-Za-z_][A-Za-z0-9_$]{0,62}$',
        description='Optional exact schema-qualified table in the developer-owned database.',
    )

    selector: ConnectionEventSelector | None = Field(
        default=None,
        description='Optional typed preset predicate applied alongside the user filter.',
    )

    @model_validator(mode='after')
    def _validate_selector(self) -> ExternalConnectionEventSource:
        if self.selector is not None:
            if self.table is not None:
                message = 'table and selector are mutually exclusive'
                raise ValueError(message)
            if not selector_supports_event(self.selector, self.event_type):
                message = 'selector fields are incompatible with event_type'
                raise ValueError(message)
        return self

    @model_serializer(mode='wrap')
    def serialize_source(self, handler: SerializerFunctionWrapHandler):  # noqa: ANN201
        """Keep absent selectors out of existing connection wire payloads."""
        # A return annotation replaces the typed serialization schema with a generic dict.
        result = cast('dict[str, Any]', handler(self))
        if self.table is None:
            result.pop('table', None)
        if self.selector is None:
            result.pop('selector', None)
        return result


class EmailToInvokeSource(BaseModel):
    """Phase 2 same-project project drop-zone email source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['email_to_invoke'] = Field(..., description='Trigger source kind.')
    phase: PhaseTwo = Field(..., description='Phase note for this source kind.')
    connection_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$',
        description='Opaque same-project email connection selector.',
    )
    sender_allowlist: tuple[EmailSenderPattern, ...] = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            'Lowercase exact sender mailboxes or whole-domain wildcards '
            'authorized to fire this trigger.'
        ),
    )

    @model_validator(mode='after')
    def _validate_distinct_senders(self) -> EmailToInvokeSource:
        if len(set(self.sender_allowlist)) != len(self.sender_allowlist):
            raise _DuplicateEmailSenderError
        return self


class SLATimerSource(BaseModel):
    """Phase 4 durable named-condition SLA timer source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['sla_timer'] = Field(..., description='Trigger source kind.')
    phase: PhaseFour = Field(..., description='Phase note for this source kind.')
    condition: StrictStr = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r'^[a-z][a-z0-9_.-]{0,127}$',
        description='Named condition machine identifier.',
    )
    fire_when: SLAFireWhen = Field(
        ...,
        description='Whether an on-time condition or its absence owes a fire.',
    )
    deadline_seconds: PositiveStrictInt = Field(
        ...,
        le=31536000,
        description='Seconds from arm time to the condition deadline.',
    )


class MemoryEventSource(BaseModel):
    """Phase 3 same-project durable memory-record change source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['memory_event'] = Field(..., description='Trigger source kind.')
    phase: PhaseThree = Field(..., description='Phase note for this source kind.')
    record_kind: MemoryRecordKind = Field(
        ...,
        description='Durable memory record kind or canonical new-thread-message source.',
    )
    operation: DataPlaneEventOperation = Field(..., description='Durable write operation.')


class StorageEventSource(BaseModel):
    """Phase 3 same-project private resource-object upload source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['storage_event'] = Field(..., description='Trigger source kind.')
    phase: PhaseThree = Field(..., description='Phase note for this source kind.')
    bucket: Literal['memory-resources'] = Field(..., description='Private resource bucket.')
    object_kind: StorageObjectKind = Field(..., description='Canonical resource object kind.')
    operation: DataPlaneEventOperation = Field(..., description='Storage write operation.')


class FireTriggerToolSource(BaseModel):
    """Phase 4 same-project server-resident fire-trigger tool source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['fire_trigger_tool'] = Field(..., description='Trigger source kind.')
    phase: PhaseFour = Field(..., description='Phase note for this source kind.')


class ReplyConversationSource(BaseModel):
    """Phase 4 database-owned conversation continuation source."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['reply_conversation'] = Field(..., description='Trigger source kind.')
    phase: PhaseFour = Field(..., description='Phase note for this source kind.')


TriggerSource: TypeAlias = Annotated[
    ScheduleSource
    | WebhookSource
    | ManualSource
    | ChainedEventSource
    | ExternalConnectionEventSource
    | EmailToInvokeSource
    | SLATimerSource
    | MemoryEventSource
    | StorageEventSource
    | ReplyConversationSource
    | FireTriggerToolSource,
    Field(discriminator='kind'),
]


class TriggerAgentBinding(BaseModel):
    """Agent target for a trigger definition."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(..., min_length=1, description='Agent identity to invoke.')
    version: PositiveStrictInt | Literal['latest'] = Field(
        ...,
        description='Immutable agent version number or latest for fire-time resolution.',
    )


class RetryPolicy(BaseModel):
    """Bounded launcher retry policy."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    max_attempts: NonNegativeStrictInt = Field(
        default=3,
        le=10,
        description='Maximum launcher retry attempts before dead-letter handling.',
    )
    initial_delay_seconds: PositiveStrictInt = Field(
        default=30,
        le=3600,
        description='Initial retry delay in seconds.',
    )
    max_delay_seconds: PositiveStrictInt = Field(
        default=3600,
        le=86400,
        description='Maximum retry delay in seconds.',
    )
    backoff: BackoffStrategy = Field(
        default='exponential',
        description='Retry delay strategy.',
    )


class TriggerOptions(BaseModel):
    """Bounded trigger guard options."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    concurrency: PositiveStrictInt = Field(
        default=4,
        le=100,
        description='Per-trigger concurrency cap.',
    )
    retry_policy: RetryPolicy | None = Field(
        default=None,
        description='Launcher retry policy.',
    )
    dedupe_window_seconds: PositiveStrictInt = Field(
        default=86400,
        le=604800,
        description='Sliding idempotency window in seconds.',
    )
    depth_cap: NonNegativeStrictInt = Field(
        default=8,
        le=32,
        description='Trigger-chain depth cap.',
    )
    fanout_cap: PositiveStrictInt = Field(
        default=100,
        le=10000,
        description='Runtime fanout cap per root event.',
    )
    shadow: bool = Field(
        default=False,
        description='Shadow mode: fires are admitted and recorded but never execute effects.',
    )
    fire_budget: NonNegativeStrictInt = Field(
        default=5,
        le=100,
        description='Per-agent-invocation fire budget for future fire-trigger tool source.',
    )


class Trigger(BaseModel):
    """Project-scoped trigger definition."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    trigger_id: StrictStr = Field(..., min_length=1, description='Stable trigger identifier.')
    project_id: StrictStr = Field(..., min_length=1, description='Owning project identifier.')
    name: StrictStr = Field(..., min_length=1, description='Human-readable trigger name.')
    status: TriggerStatus = Field(..., description='Operational trigger status.')
    source: TriggerSource = Field(..., description='Typed phased trigger source.')
    filter: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional JSONPath predicate; JSONPath is the only filter language.',
    )
    binding: MessageBinding = Field(
        ...,
        description='Message binding imported from the agents contract public interface.',
    )
    agent: TriggerAgentBinding = Field(..., description='Agent invoked by this trigger.')
    options: TriggerOptions | None = Field(default=None, description='Bounded guard options.')
    scenario_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent scenario back-reference.',
    )
    created_at: StrictStr = Field(..., description='RFC3339 creation timestamp.')
    updated_at: StrictStr = Field(..., description='RFC3339 update timestamp.')


class TriggerConversationContext(BaseModel):
    """Database-owned conversation identity and monotonic reply order."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    conversation_id: StrictStr = Field(..., min_length=1)
    sequence: PositiveStrictInt


class TriggerFire(BaseModel):
    """Durable trigger fire outbox row."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    fire_id: StrictStr = Field(..., min_length=1, description='Stable fire row identifier.')
    trigger_id: StrictStr = Field(..., min_length=1, description='Trigger that produced the fire.')
    dedupe_key: StrictStr = Field(..., min_length=1, description='Idempotency key.')
    priority: TriggerPriority = Field(..., description='Priority lane.')
    shadow: bool = Field(
        default=False,
        description='Whether this fire was admitted in shadow mode.',
    )
    status: TriggerFireStatus = Field(..., description='Outbox processing status.')
    available_at: StrictStr = Field(..., description='RFC3339 claimable timestamp.')
    attempt: NonNegativeStrictInt = Field(..., description='Zero-based launcher attempt count.')
    payload: dict[str, Any] = Field(..., description='Normalized inbound event payload.')
    root_event_id: StrictStr = Field(..., min_length=1, description='Root lineage event id.')
    parent_session_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent session id.',
    )
    parent_trigger_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent trigger id.',
    )
    trigger_chain_depth: NonNegativeStrictInt = Field(
        ...,
        description='Trigger lineage depth.',
    )
    conversation: TriggerConversationContext | None = Field(
        default=None,
        description='Optional database-owned reply/conversation continuation context.',
    )


class TriggerInvocation(BaseModel):
    """Terminal trigger invocation history record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    invocation_id: StrictStr = Field(..., min_length=1, description='Stable history id.')
    fire_id: StrictStr = Field(..., min_length=1, description='Source fire row id.')
    trigger_id: StrictStr = Field(..., min_length=1, description='Source trigger id.')
    session_id: StrictStr = Field(..., min_length=1, description='Launched session id.')
    status: TriggerInvocationStatus = Field(..., description='Terminal invocation status.')
    shadow: bool = Field(
        default=False,
        description='Whether this invocation records a shadow fire.',
    )
    outcome: TriggerOutcome | None = Field(
        default=None,
        description='Reserved for future outcome-based pricing.',
    )
    started_at: StrictStr = Field(..., description='RFC3339 invocation start timestamp.')
    finished_at: StrictStr = Field(..., description='RFC3339 terminal timestamp.')
    root_event_id: StrictStr = Field(..., min_length=1, description='Root lineage event id.')
    parent_session_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent session id.',
    )
    parent_trigger_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent trigger id.',
    )
    trigger_chain_depth: NonNegativeStrictInt = Field(
        ...,
        description='Trigger lineage depth.',
    )


class TriggerLaunch(BaseModel):
    """Authenticated internal launch envelope pinned to one immutable agent version."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal[1]
    fire_id: StrictStr = Field(..., min_length=1)
    trigger_id: StrictStr = Field(..., min_length=1)
    invocation_id: StrictStr = Field(..., min_length=1)
    organization_id: StrictStr = Field(..., min_length=1)
    project_id: StrictStr = Field(..., min_length=1)
    agent_id: StrictStr = Field(..., min_length=1)
    agent_version: PositiveStrictInt
    agent_version_snapshot: AgentVersion
    payload: dict[str, Any]
    binding: MessageBinding | None = Field(
        default=None, description='Message binding pinned with the admitted trigger target.'
    )
    session_id: StrictStr = Field(..., min_length=1)
    root_event_id: StrictStr = Field(..., min_length=1)
    parent_session_id: StrictStr | None = Field(default=None, min_length=1)
    parent_trigger_id: StrictStr | None = Field(default=None, min_length=1)
    trigger_chain_depth: NonNegativeStrictInt
    conversation: TriggerConversationContext | None = None

    @model_validator(mode='after')
    def _validate_external_tool_snapshots(self) -> TriggerLaunch:
        required_fields = (
            'tool_id',
            'version',
            'idempotency',
            'timeout_ms',
            'output_schema',
            'expected_runtime_ms',
        )
        for tool in self.agent_version_snapshot.tools_snapshot:
            if tool.execution.locus not in {'worker', 'webhook'}:
                continue
            if any(getattr(tool, field_name) is None for field_name in required_fields):
                raise _LegacyExternalToolSnapshotError
        return self


class ScenarioAgentBinding(BaseModel):
    """Agent version pin for a scenario."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(..., min_length=1, description='Agent identity used by scenario.')
    version: PositiveStrictInt = Field(..., description='Immutable scenario agent version.')


class ScenarioSubworkflowBinding(BaseModel):
    """Immutable same-project child scenario pin."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    scenario_id: StrictStr = Field(..., min_length=1, description='Child scenario identity.')
    version: PositiveStrictInt = Field(..., description='Immutable child scenario revision.')


class SlackMessageTarget(BaseModel):
    """Slack output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    channel_ref: StrictStr = Field(..., min_length=1, description='Slack channel reference.')


class DiscordMessageTarget(BaseModel):
    """Discord output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    channel_ref: StrictStr = Field(
        ...,
        min_length=1,
        description=(
            'Connection-scoped Discord channel reference; never a raw URL, token, or secret.'
        ),
    )


class GitHubCommentTarget(BaseModel):
    """GitHub comment output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    repository_ref: StrictStr = Field(
        ...,
        min_length=1,
        description=(
            'Connection-scoped GitHub repository reference; never a raw URL, token, or secret.'
        ),
    )
    issue_ref: StrictStr = Field(
        ...,
        min_length=1,
        description=(
            'Connection-scoped GitHub issue or pull request reference; never a raw URL, token, '
            "or secret. A pull request is an issue to GitHub's comment API."
        ),
    )


class EmailReplyTarget(BaseModel):
    """Email reply output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    thread_ref: StrictStr = Field(..., min_length=1, description='Email thread reference.')


class DatabaseRecordTarget(BaseModel):
    """Database record output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    table_ref: StrictStr = Field(..., min_length=1, description='Database table reference.')


class EventEmissionTarget(BaseModel):
    """Event emission output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    event_type: StrictStr = Field(..., min_length=1, description='Emitted event type.')


class WebhookOutputTarget(BaseModel):
    """Webhook output target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    endpoint_ref: StrictStr = Field(
        ...,
        min_length=1,
        description='Connection-scoped webhook endpoint reference; never a raw URL or secret.',
    )


class DisplayInAppOutputBinding(BaseModel):
    """Scenario output binding that renders the result in the app UI. No target."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['display_in_app'] = Field(..., description='Output binding kind.')


class WebhookOutputBinding(BaseModel):
    """Scenario output binding that calls an external webhook with the result."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['webhook'] = Field(..., description='Output binding kind.')
    target: WebhookOutputTarget = Field(..., description='Webhook output target.')


class SlackMessageOutputBinding(BaseModel):
    """Scenario output binding for Slack messages."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['slack_message'] = Field(..., description='Output binding kind.')
    target: SlackMessageTarget = Field(..., description='Slack output target.')


class EmailReplyOutputBinding(BaseModel):
    """Scenario output binding for email replies."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['email_reply'] = Field(..., description='Output binding kind.')
    target: EmailReplyTarget = Field(..., description='Email reply target.')


class DatabaseRecordOutputBinding(BaseModel):
    """Scenario output binding for database records."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['database_record'] = Field(..., description='Output binding kind.')
    target: DatabaseRecordTarget = Field(..., description='Database output target.')


class EventEmissionOutputBinding(BaseModel):
    """Scenario output binding for event emissions."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['event_emission'] = Field(..., description='Output binding kind.')
    target: EventEmissionTarget = Field(..., description='Event emission target.')


class DiscordMessageOutputBinding(BaseModel):
    """Scenario output binding for Discord messages."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['discord_message'] = Field(..., description='Output binding kind.')
    target: DiscordMessageTarget = Field(..., description='Discord output target.')


class GitHubCommentOutputBinding(BaseModel):
    """Scenario output binding for GitHub issue and pull request comments."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['github_comment'] = Field(..., description='Output binding kind.')
    target: GitHubCommentTarget = Field(..., description='GitHub comment output target.')


class LogicalOutputFileSelector(BaseModel):
    """Select an artifact candidate by its authored logical output name."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    selector_type: Literal['logical_output']
    logical_output_name: OpaqueTokenId


class ExplicitSelectionFileSelector(BaseModel):
    """Select an artifact using a separately authored selection rule."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    selector_type: Literal['explicit_selection']
    selection_rule_ref: OpaqueTokenId


FileOutputSelector: TypeAlias = Annotated[
    LogicalOutputFileSelector | ExplicitSelectionFileSelector,
    Field(discriminator='selector_type'),
]
FileDeliveryMode: TypeAlias = Literal[
    'attachment',
    'authenticated_reference',
    'vault_retrieval',
]


class FileDeliveryPolicy(BaseModel):
    """Bounded delivery behavior for a Scenario file output."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    max_size_bytes: Annotated[StrictInt, Field(ge=1, le=1_073_741_824)]
    authorization_ttl_seconds: Annotated[StrictInt, Field(ge=60, le=3600)]
    max_attempts: Annotated[StrictInt, Field(ge=1, le=10)]
    initial_retry_delay_seconds: Annotated[StrictInt, Field(ge=1, le=3600)]


class FileOutputBinding(BaseModel):
    """Author-time artifact selection and delivery policy without mutable identity."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['file']
    selector: FileOutputSelector
    required_kind: ArtifactKind
    allowed_mime_types: tuple[MimeType, ...] = Field(min_length=1, max_length=8)
    required_custody: ArtifactCustody
    destination_connection_ref: OpaqueTokenId
    mode: FileDeliveryMode
    delivery_policy: FileDeliveryPolicy
    private_export_authorization_required: StrictBool
    idempotency_key_template: Literal[
        '{scenario_revision}:{invocation_id}:{artifact_id}:{destination_revision}'
    ]

    @model_validator(mode='after')
    def validate_file_policy(self) -> FileOutputBinding:
        """Enforce unique kind-matching MIME values and custody-safe delivery."""
        if len(set(self.allowed_mime_types)) != len(self.allowed_mime_types):
            message = 'allowed_mime_types entries must be distinct'
            raise ValueError(message)
        if any(
            not is_mime_type_valid_for_artifact_kind(self.required_kind, mime_type)
            for mime_type in self.allowed_mime_types
        ):
            message = 'allowed_mime_types must match required_kind'
            raise ValueError(message)

        if self.required_custody == 'ordinary':
            valid_delivery = (
                self.mode in {'attachment', 'authenticated_reference'}
                and not self.private_export_authorization_required
            )
        elif self.mode == 'vault_retrieval':
            valid_delivery = not self.private_export_authorization_required
        else:
            valid_delivery = self.private_export_authorization_required
        if not valid_delivery:
            message = 'file delivery mode and private export authorization must match custody'
            raise ValueError(message)
        return self


OutputBinding: TypeAlias = Annotated[
    DisplayInAppOutputBinding
    | WebhookOutputBinding
    | SlackMessageOutputBinding
    | EmailReplyOutputBinding
    | DatabaseRecordOutputBinding
    | EventEmissionOutputBinding
    | DiscordMessageOutputBinding
    | GitHubCommentOutputBinding
    | FileOutputBinding,
    Field(discriminator='kind'),
]


class CanvasNodePosition(BaseModel):
    """Canvas node position."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    x: CoordinateValue = Field(..., description='Canvas x-coordinate.')
    y: CoordinateValue = Field(..., description='Canvas y-coordinate.')


class CanvasLayout(BaseModel):
    """Bounded scenario canvas metadata."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    node_positions: dict[StrictStr, CanvasNodePosition] = Field(
        ...,
        min_length=1,
        max_length=64,
        description='Node positions keyed by node id.',
    )


class Scenario(BaseModel):
    """Single-trigger Alpha scenario record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    scenario_id: StrictStr = Field(..., min_length=1, description='Stable scenario id.')
    project_id: StrictStr = Field(..., min_length=1, description='Owning project id.')
    name: StrictStr = Field(..., min_length=1, description='Human-readable scenario name.')
    trigger_id: StrictStr = Field(..., min_length=1, description='Exactly one trigger id.')
    revision: PositiveStrictInt = Field(
        ...,
        description='Positive optimistic revision of the current scenario canvas.',
    )
    agent: ScenarioAgentBinding = Field(..., description='Scenario agent version pin.')
    subworkflow: ScenarioSubworkflowBinding | None = Field(
        default=None,
        description='Optional immutable same-project child scenario pin.',
    )
    output_binding: OutputBinding = Field(..., description='Scenario output binding.')
    layout: CanvasLayout = Field(..., description='Bounded canvas layout metadata.')
    notes: StrictStr | None = Field(
        default=None,
        max_length=12000,
        pattern=r'\S',
        description='Optional bounded authoring context preserved with every revision.',
    )
    flow_graph: FlowGraph | None = Field(
        default=None,
        description=(
            'Optional canonical Flow authoring topology. '
            'Legacy records without a graph remain valid.'
        ),
    )
    created_at: StrictStr = Field(..., description='RFC3339 creation timestamp.')
    updated_at: StrictStr = Field(..., description='RFC3339 update timestamp.')

    @field_serializer('flow_graph')
    def _serialize_flow_graph(self, graph: FlowGraph | None) -> object:
        """Emit absent optional node selectors as missing keys, never invalid JSON nulls."""
        if graph is None:
            return None
        return graph.model_dump(mode='json', exclude_none=True)


def _message_binding_types_namespace() -> dict[str, object]:
    agents_module = import_module('maivn_contracts.agents')
    return {
        'AgentVersion': cast('object', agents_module.AgentVersion),
        'MessageBinding': cast('object', agents_module.MessageBinding),
    }


def _flow_types_namespace() -> dict[str, object]:
    flows_module = import_module('maivn_contracts.flows')
    return {'FlowGraph': cast('object', flows_module.FlowGraph)}


Trigger.model_rebuild(_types_namespace=_message_binding_types_namespace())
TriggerLaunch.model_rebuild(_types_namespace=_message_binding_types_namespace())
Scenario.model_rebuild(_types_namespace=_flow_types_namespace())
