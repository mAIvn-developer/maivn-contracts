"""Hand-authored Pydantic models for runtime protocol contracts."""

from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
)

from maivn_contracts.agents import (
    ModelChoice,  # noqa: TC001 - Pydantic resolves this field at runtime.
    PlanningChoice,  # noqa: TC001 - Pydantic resolves this field at runtime.
)
from maivn_contracts.runtime.customer_scope import memory_owner_user_id

if TYPE_CHECKING:
    from maivn_contracts.messages import Message

ModelDirective: TypeAlias = Literal['auto', 'fast', 'balanced', 'max', 'ultra', 'force']
# What a caller wants auto routing to lean toward when the request content alone
# does not settle it. Mutually exclusive by construction: one value, not a set of
# flags a caller could contradict itself with.
RoutingPreference: TypeAlias = Literal['speed', 'cost', 'quality']
Durability: TypeAlias = Literal['exit', 'async', 'sync']
StreamMode: TypeAlias = Literal['values', 'messages', 'updates', 'custom']
RunStatus: TypeAlias = Literal[
    'pending',
    'running',
    'interrupted',
    'completed',
    'failed',
    'cancelled',
    # Terminal, and not a synonym for either neighbour. The run neither reported an error
    # nor was asked to stop: the process owning it died and nobody knows how it would have
    # ended. Only startup reconciliation writes it, and only onto rows that were already
    # ghosts - no live run ever transitions into it (owner ruling 2026-08-21).
    'abandoned',
]
InterruptKind: TypeAlias = Literal['tool_argument', 'tool_approval', 'agent_followup']
PromptSource: TypeAlias = Literal['authored', 'agent_generated', 'fallback']
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]
RecursionLimit: TypeAlias = Annotated[int, Field(ge=1, le=1000, strict=True)]
# What produced this run. `root` is an ordinary top-level invocation; `swarm_member`
# is an agent the swarm planner selected; `tool_job` is a subgraph the job planner
# cut out of a tool graph and gave its own execution context; `decision_run` marks a
# decision-only run, a root run with no model loop that holds only Decision steps.
ChildRunKind: TypeAlias = Literal['root', 'swarm_member', 'tool_job', 'decision_run']


def _positive_expense_ceiling(value: str) -> str:
    if Decimal(value) <= 0:
        message = 'expense ceiling must be positive'
        raise ValueError(message)
    return value


ExpenseCeilingUsd: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=r'^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?$'),
    AfterValidator(_positive_expense_ceiling),
]


class SystemModelChoices(BaseModel):
    """Optional model choices for framework-owned system tools."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    thinking: ModelChoice | None = Field(
        default=None,
        description='Optional model choice for the think system tool.',
    )
    compose_argument: ModelChoice | None = Field(
        default=None,
        description='Optional model choice for compose_argument synthesis.',
    )
    repl: ModelChoice | None = Field(
        default=None,
        description='Optional model choice for REPL code generation and repair.',
    )


class RunConfig(BaseModel):
    """Owned runtime invocation configuration."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    user_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=256,
        description=(
            'Developer-asserted customer subject within the authenticated project; '
            'not independently verified end-user authentication. sdk-user disables private memory.'
        ),
    )

    @field_validator('user_id')
    @classmethod
    def validate_customer_subject(cls, value: str) -> str:
        """Validate without normalizing the thread and memory owner."""
        memory_owner_user_id(value)
        return value

    thread_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Runtime thread identifier used to bind checkpoint state.',
    )
    session_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional session identifier used for tool execution context.',
    )
    redaction_preview_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        repr=False,
        description='Opaque sealed redaction preview approval; consumed once by the data plane.',
    )
    invocation_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional invocation identifier for trace and retry correlation.',
    )
    project_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional project identifier used for policy and spend attribution.',
    )
    organization_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Organization the run belongs to; stamped from the authenticated caller.',
    )
    agent_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Agent scope this run executes as; required to reach agent-bound memory.',
    )
    swarm_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Swarm scope this run executes as; required to reach swarm-bound memory.',
    )
    client_timezone: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional IANA timezone reported by the invoking SDK client.',
    )
    sdk_deployment_timezone: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional IANA timezone configured for the SDK deployment.',
    )
    model_directive: ModelDirective | None = Field(
        default=None,
        description='Optional runtime model directive selected at invocation time.',
    )
    routing_preference: RoutingPreference | None = Field(
        default=None,
        description=(
            'Ask auto routing to lean faster, cheaper, or stronger than the request '
            'content alone would pick. Absent means no preference. Only auto routing '
            'reads it; every other directive already names its own tier. One value '
            'rather than separate flags, because these are mutually exclusive and a '
            'caller cannot ask for two at once.'
        ),
    )
    system_model_choices: SystemModelChoices | None = Field(
        default=None,
        description=(
            'Optional explicit model choices for framework-owned system tools. '
            "Absent preserves each tool's internal default profile."
        ),
    )
    max_expense_usd: ExpenseCeilingUsd | None = Field(
        default=None,
        description=(
            'Optional lower total mAIvn execution expense ceiling in exact USD. '
            'Capped runs exclude paid hosted search/sandbox and background enrichment. '
            'This limits new work and never changes customer billing rates.'
        ),
    )
    planning: PlanningChoice | None = Field(
        default=None,
        description='Optional model choice for framework-owned planning.',
    )
    job_depth: NonNegativeStrictInt | None = Field(
        default=None,
        description='Execution-tree depth for nested assignment replay and ordering.',
    )
    job_index: NonNegativeStrictInt | None = Field(
        default=None,
        description='Execution-tree sibling index for causal ordering within a parent.',
    )
    parent_assignment_uuid: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional parent assignment UUID for nested job lineage.',
    )
    child_run_kind: ChildRunKind | None = Field(
        default=None,
        description=(
            'Absent means an ordinary root invocation, matching the other lineage '
            'fields beside it, so an existing run config serializes byte-identically. '
            'What KIND of child run this is, not merely that it is one. '
            '`job_depth` alone cannot answer this: a swarm member and a decomposed '
            'tool job both report depth 1, so any consumer trying to prove a job ran '
            'was reduced to guessing from names. `decision_run` also marks a '
            'decision-only run, which is a root run with no model loop.'
        ),
    )
    plan_node_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description=(
            'Stable identifier of the plan node this run executes. Survives retries '
            'and re-planning, which a sibling ordinal does not.'
        ),
    )
    decomposition_depth: NonNegativeStrictInt | None = Field(
        default=None,
        description=(
            'How many JOB boundaries deep this run is, counted separately from '
            '`job_depth`. They diverge as soon as a swarm delegates: a swarm hop '
            'raises job_depth without spending any of the decomposition budget, and '
            'conflating them would let a few agent hops exhaust the job allowance.'
        ),
    )
    recursion_limit: RecursionLimit = Field(
        default=100,
        description='Runtime cycle guard; defaults to the v1 parity value of 100.',
    )
    durability: Durability = Field(
        default='exit',
        description='Checkpoint persistence mode; exit persists at run exit or interrupt.',
    )
    origin: StrictStr | None = Field(
        default=None,
        min_length=1,
        description=(
            'Optional self-reported invoking client, display/filter only, never consulted '
            'for authorization. Conventional starting set: studio, alpha, portal, sdk. Not '
            'an enforced enum - unrecognized values from newer clients are accepted and '
            'read back as-is; absent on historical rows.'
        ),
    )


class StartCommand(BaseModel):
    """Start a run with initial owned messages."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['start'] = Field(..., description='Command discriminator.')
    messages: list[Message] = Field(
        ...,
        min_length=1,
        max_length=128,
        description='Initial owned Message inputs for a start command.',
    )
    options: dict[str, Any] | None = Field(
        default=None,
        description='Optional open invocation options interpreted by the runtime.',
    )


class ResumeCommand(BaseModel):
    """Resume an interrupted run checkpoint."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['resume'] = Field(..., description='Command discriminator.')
    checkpoint_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Checkpoint identifier to resume from.',
    )
    value: Any = Field(..., description='Resume payload supplied to the interrupted checkpoint.')


class CancelCommand(BaseModel):
    """Cancel a running invocation."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['cancel'] = Field(..., description='Command discriminator.')
    reason: StrictStr = Field(
        ...,
        min_length=1,
        max_length=1024,
        description='Human-readable cancellation reason.',
    )


Command: TypeAlias = Annotated[
    StartCommand | ResumeCommand | CancelCommand,
    Field(discriminator='kind'),
]


class StreamPart(BaseModel):
    """Owned runtime streaming envelope."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    event: StrictStr = Field(
        ...,
        min_length=1,
        description='Namespaced event name; message events use the messages prefix by convention.',
    )
    stream_mode: StreamMode | None = Field(
        default=None,
        description='Optional stream mode that produced this part.',
    )
    data: dict[str, Any] = Field(
        ...,
        description='Open event payload for this stream part.',
    )
    subgraph_path: list[StrictStr] = Field(
        ...,
        description='Required subgraph namespace path; empty means the root graph.',
    )
    ordinal: StrictStr = Field(
        ...,
        min_length=1,
        description='Per-producer stream ordering token matching the Event ordinal contract.',
    )
    ts: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when the stream part was emitted.',
    )


class Interrupt(BaseModel):
    """Owned human-in-the-loop interrupt surface."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    checkpoint_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Owned checkpoint identifier used by resume commands.',
    )
    reason: StrictStr = Field(
        ...,
        min_length=1,
        description='Machine-readable or human-readable interrupt reason.',
    )
    payload: dict[str, Any] = Field(
        ...,
        description='Open HITL payload surfaced to the caller.',
    )
    kind: InterruptKind = Field(
        default='tool_approval',
        description='Canonical reason category for the human-in-the-loop pause.',
    )
    prompt_source: PromptSource = Field(
        default='authored',
        description='Provenance of the question shown to the responder.',
    )
    question: StrictStr = Field(
        default='',
        description='Canonical question rendered by typed interrupt clients.',
    )
    response_schema: dict[str, Any] = Field(
        default_factory=dict,
        description='Stored JSON Schema used to render and validate the response.',
    )
    thread_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional runtime thread identifier for historical compatibility.',
    )
    session_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional runtime session identifier for historical compatibility.',
    )


class FreeTextInterruptResponse(BaseModel):
    """Free-text response to a canonical interrupt."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['free_text'] = Field(..., description='Response envelope discriminator.')
    value: StrictStr = Field(..., description='Free-text answer supplied by the responder.')


class BooleanInterruptResponse(BaseModel):
    """Boolean response to a canonical interrupt."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['boolean'] = Field(..., description='Response envelope discriminator.')
    value: StrictBool = Field(..., description='Boolean answer supplied by the responder.')


class SingleChoiceInterruptResponse(BaseModel):
    """Single-choice response to a canonical interrupt."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['single_choice'] = Field(..., description='Response envelope discriminator.')
    value: StrictStr = Field(..., description='Selected choice supplied by the responder.')


class MultipleChoiceInterruptResponse(BaseModel):
    """Multiple-choice response to a canonical interrupt."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['multiple_choice'] = Field(..., description='Response envelope discriminator.')
    value: list[StrictStr] = Field(
        ...,
        min_length=1,
        description='Selected choices supplied by the responder.',
    )


class StructuredInterruptResponse(BaseModel):
    """Declared-schema object response to a canonical interrupt."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['structured'] = Field(..., description='Response envelope discriminator.')
    value: dict[str, Any] = Field(
        ...,
        description='Structured answer validated against the interrupt stored schema.',
    )


InterruptResponse: TypeAlias = Annotated[
    FreeTextInterruptResponse
    | BooleanInterruptResponse
    | SingleChoiceInterruptResponse
    | MultipleChoiceInterruptResponse
    | StructuredInterruptResponse,
    Field(discriminator='kind'),
]


class RunState(BaseModel):
    """Queryable runtime thread/run state snapshot."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    thread_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Runtime thread identifier for the queried state.',
    )
    run_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Runtime run identifier for this state snapshot.',
    )
    status: RunStatus = Field(..., description='Run lifecycle status.')
    interrupt: Interrupt | None = Field(
        default=None,
        description='Optional owned checkpoint interrupt surface.',
    )
    values: dict[str, Any] = Field(
        ...,
        description='Open runtime state values visible to state readers.',
    )
    ts: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when the snapshot was observed.',
    )


def _message_types_namespace() -> dict[str, object]:
    messages_module = import_module('maivn_contracts.messages')
    return {'Message': cast('object', messages_module.Message)}


StartCommand.model_rebuild(_types_namespace=_message_types_namespace())
