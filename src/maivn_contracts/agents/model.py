"""Hand-authored Pydantic models for deployed-agent registry contracts."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

if TYPE_CHECKING:
    from maivn_contracts.tools import FunctionToolSpec, ToolDependencyEdge

AgentExecutionMode: TypeAlias = Literal['worker', 'webhook', 'hosted_only']
ModelTier: TypeAlias = Literal['auto', 'fast', 'balanced', 'max', 'ultra']
PlanningTier: TypeAlias = Literal['auto', 'standard', 'advanced', 'deep']
ReasoningLevel: TypeAlias = Literal['minimal', 'low', 'medium', 'high']
MemoryLevel: TypeAlias = Literal['none', 'glimpse', 'focus', 'clarity']
MemoryPersistenceMode: TypeAlias = Literal[
    'persist_none',
    'vector_only',
    'vector_plus_graph',
]
PositiveStrictInt: TypeAlias = Annotated[int, Field(ge=1, strict=True)]
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]
MemoryResultCount: TypeAlias = Annotated[int, Field(ge=1, le=16, strict=True)]
MemoryContextChars: TypeAlias = Annotated[int, Field(ge=32, le=12000, strict=True)]


class _ModelChoiceSelectionError(ValueError):
    """Raised when a model choice has zero or multiple selectors."""

    def __init__(self) -> None:
        """Build the invalid model choice error."""
        message = 'Exactly one of tier or model_id must be set'
        super().__init__(message)


class _WebhookEndpointRequiredError(ValueError):
    """Raised when webhook execution lacks an endpoint."""

    def __init__(self) -> None:
        """Build the missing webhook endpoint error."""
        message = 'webhook execution mode requires webhook_endpoint'
        super().__init__(message)


class _WebhookEndpointModeError(ValueError):
    """Raised when a webhook endpoint is configured outside webhook mode."""

    def __init__(self) -> None:
        """Build the invalid webhook endpoint mode error."""
        message = 'webhook_endpoint is only valid for webhook execution mode'
        super().__init__(message)


class _ToolExecutionModeError(ValueError):
    """Raised when a tool execution locus is invalid for the agent mode."""

    def __init__(self, locus: str, execution_mode: AgentExecutionMode) -> None:
        """Build the invalid tool execution locus error."""
        message = (
            f'tool execution locus {locus!r} is not valid for execution_mode {execution_mode!r}'
        )
        super().__init__(message)


class Agent(BaseModel):
    """Identity-only deployed-agent record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable deployed-agent identifier.',
        examples=['agt-customer-triage'],
    )
    project_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Project that owns this deployed agent.',
        examples=['prj-support'],
    )
    name: StrictStr = Field(
        ...,
        min_length=1,
        description='Human-readable deployed-agent name.',
        examples=['Customer triage'],
    )
    description: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional human-readable deployed-agent description.',
        examples=['Classifies incoming customer requests and drafts next steps.'],
    )
    latest_version: PositiveStrictInt = Field(
        ...,
        description='Latest immutable version number deployed for this agent.',
        examples=[3],
    )
    created_at: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when the agent identity was created.',
        examples=['2026-07-01T16:00:00Z'],
    )
    updated_at: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when the agent identity was last updated.',
        examples=['2026-07-01T16:30:00Z'],
    )


class ModelChoice(BaseModel):
    """A scoped model choice: exactly one tier or exact model id."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    tier: ModelTier | None = Field(
        default=None,
        description='Model tier for this framework part.',
        examples=['balanced'],
    )
    model_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Exact provider model id for this framework part.',
        examples=['gpt-5-mini'],
    )

    @model_validator(mode='after')
    def _validate_exactly_one_choice(self) -> ModelChoice:
        has_tier = self.tier is not None
        has_model_id = self.model_id is not None
        if has_tier == has_model_id:
            raise _ModelChoiceSelectionError
        return self


class PlanningChoice(BaseModel):
    """A planning selection: exactly one public tier or exact model id."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        json_schema_extra={
            'x-maivn-closed-union-validation': True,
            'oneOf': [
                {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['tier'],
                    'properties': {
                        'tier': {'type': 'string', 'enum': ['auto', 'standard', 'advanced', 'deep']}
                    },
                },
                {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['model_id'],
                    'properties': {'model_id': {'type': 'string', 'minLength': 1}},
                },
            ],
        },
    )

    tier: PlanningTier | None = Field(
        default=None,
        description='Planning tier for framework-owned planning work.',
        examples=['advanced'],
    )
    model_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Exact provider model id for framework-owned planning work.',
        examples=['gpt-5.6-terra'],
    )

    @model_validator(mode='after')
    def _validate_exactly_one_choice(self) -> PlanningChoice:
        has_tier = self.tier is not None
        has_model_id = self.model_id is not None
        if has_tier == has_model_id:
            raise _ModelChoiceSelectionError
        return self


class ModelSettings(BaseModel):
    """Scoped model settings for the immutable agent version."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    response: ModelChoice = Field(
        ...,
        description='Model choice for final/direct response generation.',
    )
    planning: PlanningChoice | None = Field(
        default=None,
        description='Model choice for framework-owned planning.',
    )
    thinking: ModelChoice | None = Field(
        default=None,
        description='Model choice for the think system tool.',
    )
    compose_argument: ModelChoice | None = Field(
        default=None,
        description='Model choice for compose_argument system-tool synthesis.',
    )
    repl: ModelChoice | None = Field(
        default=None,
        description='Model choice for REPL system-tool code generation and repair.',
    )


class InlineInstructions(BaseModel):
    """Inline system prompt or instruction content."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['inline'] = Field(..., description='Instruction source kind.')
    content: StrictStr = Field(
        ...,
        min_length=1,
        description='Inline system prompt or instruction content.',
    )


class ReferenceInstructions(BaseModel):
    """Server-resolved reference to immutable instruction content."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['ref'] = Field(..., description='Instruction source kind.')
    ref: StrictStr = Field(
        ...,
        min_length=1,
        description='Server-resolved reference to immutable prompt or instruction content.',
    )


Instructions: TypeAlias = Annotated[
    InlineInstructions | ReferenceInstructions,
    Field(discriminator='kind'),
]


class WorkerToolExecution(BaseModel):
    """Tool execution through a connected developer-side worker."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    locus: Literal['worker'] = Field(..., description='Tool execution locus.')


class WebhookToolExecution(BaseModel):
    """Tool execution through the version-level webhook endpoint."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    locus: Literal['webhook'] = Field(..., description='Tool execution locus.')
    path: StrictStr = Field(
        ...,
        min_length=1,
        # Lookahead-free equivalent of ^/(?!/)[^?#]*$ - pydantic-core (Rust)
        # and Go RE2 both reject look-around.
        pattern=r'^/([^/?#][^?#]*)?$',
        description='Relative absolute-path endpoint under the version-level webhook endpoint.',
    )


class HostedToolExecution(BaseModel):
    """Tool execution inside the hosted mAIvn connector/system-tool environment."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    locus: Literal['hosted'] = Field(..., description='Tool execution locus.')
    provider: StrictStr = Field(
        ...,
        min_length=1,
        description='Hosted connector, system tool, no-code tool, or hosted MCP provider.',
    )
    tool_ref: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable hosted tool reference within the provider.',
    )


ToolExecution: TypeAlias = Annotated[
    WorkerToolExecution | WebhookToolExecution | HostedToolExecution,
    Field(discriminator='locus'),
]


class ToolSnapshot(BaseModel):
    """Version-pinned tool shape captured at deployment time."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    tool_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Stable external tool specification identifier when captured.',
    )
    version: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Immutable external tool specification version when captured.',
    )
    idempotency: Literal['idempotent', 'non_idempotent', 'unknown'] | None = Field(
        default=None,
        description='Retry and duplicate-suppression declaration when captured.',
    )
    timeout_ms: PositiveStrictInt | None = Field(
        default=None,
        le=600000,
        description='Immutable external tool execution budget in milliseconds when captured.',
    )
    output_schema: dict[str, Any] | None = Field(
        default=None,
        description='Optional JSON Schema object for external tool results.',
    )
    expected_runtime_ms: NonNegativeStrictInt | None = Field(
        default=None,
        le=600000,
        description='Expected external tool execution duration in milliseconds when captured.',
    )
    name: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable tool name from the deployed tool spec.',
    )
    description: StrictStr = Field(
        ...,
        min_length=1,
        description='Human-readable tool behavior description from the deployed tool spec.',
    )
    parameters_schema: dict[str, Any] = Field(
        ...,
        description='Closed JSON-Schema subset for tool parameters.',
    )
    execution: ToolExecution = Field(
        ...,
        description='Execution-locus discriminator for the deployed tool.',
    )
    tool_dependencies: list[ToolDependencyEdge] | None = Field(
        default=None,
        max_length=256,
        description='Immutable tool outputs injected into this tool by argument name.',
    )


class VersionOptions(BaseModel):
    """Closed subset of invocation reconstruction options."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    reasoning: ReasoningLevel | None = Field(
        default=None,
        description='Reasoning level used for LLM depth.',
    )
    stream_response: StrictBool | None = Field(
        default=None,
        description='Whether synthesized response updates stream when supported.',
    )
    status_messages: StrictBool | None = Field(
        default=None,
        description='Whether swarm lifecycle status messages are emitted.',
    )
    force_final_tool: StrictBool | None = Field(
        default=None,
        description='Whether the final_tool result is the version output contract.',
    )
    sticky_workers: StrictBool | None = Field(
        default=None,
        description=(
            'Prefer a stable eligible Mode A worker for one agent session. '
            'Absent/None reads as false; None-defaulted so pre-existing '
            'version dumps round-trip unchanged.'
        ),
    )
    targeted_tools: list[StrictStr] | None = Field(
        default=None,
        description='Tool names targeted for invocation reconstruction.',
    )
    max_results: NonNegativeStrictInt | None = Field(
        default=None,
        description='Maximum number of tools to return from semantic search.',
    )
    allowed_system_tools: list[StrictStr] | None = Field(
        default=None,
        description='System tool allowlist captured from session-start configuration.',
    )


class WebhookEndpoint(BaseModel):
    """Mode B endpoint and vault-referenced signing secret."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    url: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^https://',
        description=(
            'HTTPS base URL used for Mode B tool delivery. Control-plane service validation '
            'also enforces the SSRF, host, port, userinfo, and fragment policy.'
        ),
        examples=['https://tools.example.com/maivn'],
    )
    secret_ref: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^vault://',
        description='Vault reference for the Mode B webhook HMAC secret.',
        examples=['vault://project/prj-support/agent/agt-customer-triage/webhook-hmac'],
    )


class AgentMemoryRetrievalPolicy(BaseModel):
    """Closed recall controls pinned to an immutable agent version."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    skills_enabled: StrictBool
    insights_enabled: StrictBool
    resources_enabled: StrictBool
    graph_enabled: StrictBool | None = Field(
        default=None,
        description=(
            'Recall graph assertions independently of the write mode; absent means enabled.'
        ),
    )
    max_graph_assertions: MemoryResultCount | None = Field(default=None)
    max_skills: MemoryResultCount
    max_insights: MemoryResultCount
    max_resources: MemoryResultCount
    max_context_chars: MemoryContextChars


class AgentMemoryExtractionPolicy(BaseModel):
    """Closed post-run extraction controls for one memory signal kind."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    enabled: StrictBool
    max_count: MemoryResultCount


class AgentMemoryPolicy(BaseModel):
    """Complete agent-level memory behavior pinned to an immutable version."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    enabled: StrictBool
    level: MemoryLevel
    persistence_mode: MemoryPersistenceMode
    retrieval: AgentMemoryRetrievalPolicy
    skill_extraction: AgentMemoryExtractionPolicy
    insight_extraction: AgentMemoryExtractionPolicy
    graph_extraction: AgentMemoryExtractionPolicy | None = Field(
        default=None,
        description=(
            'Optional graph extraction controls; writes still require vector_plus_graph mode.'
        ),
    )


class AgentOutputSchema(BaseModel):
    """Provider-neutral structured-output contract pinned to an agent version."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    name: StrictStr = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[A-Za-z_][A-Za-z0-9_-]*$',
        description='Portable provider-safe schema name used in traces.',
    )
    json_schema: dict[str, Any] = Field(
        ...,
        validation_alias='schema',
        serialization_alias='schema',
        description='JSON Schema object sent through the existing structured-output pipeline.',
    )


class AgentVersion(BaseModel):
    """Immutable deployed-agent version record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable deployed-agent identifier this version belongs to.',
    )
    version: PositiveStrictInt = Field(
        ...,
        description='Positive immutable deployed-agent version number.',
    )
    execution_mode: AgentExecutionMode = Field(
        ...,
        description=(
            'AgentExecutionMode bound to this immutable version. Switching modes requires '
            'a new version; in-flight invocations finish under their original version.'
        ),
    )
    model: ModelSettings = Field(
        ...,
        description='Model settings bound to this immutable version.',
    )
    instructions: Instructions = Field(
        ...,
        description='System prompt or instructions source bound to this immutable version.',
    )
    tools_snapshot: list[ToolSnapshot] = Field(
        ...,
        description='Tool specs captured at deployment time.',
    )
    attached_skill_ids: list[StrictStr] | None = Field(
        default=None,
        max_length=256,
        description='Optional immutable skills attached directly to the compiled Flow root.',
    )
    agents_snapshot: list[InvokeAgentSpec] | None = Field(
        default=None,
        max_length=64,
        description='Optional immutable invocation-local roster compiled for this version.',
    )
    agent_tool_dependencies: list[AgentToolDependency] | None = Field(
        default=None,
        max_length=256,
        description='Optional immutable delegated tool arguments compiled for this version.',
    )
    swarm_roster: StrictBool | None = Field(
        default=None,
        description='Whether this immutable version executes as a compiled swarm roster.',
    )
    options: VersionOptions | None = Field(
        default=None,
        description='Invocation reconstruction options captured at deployment time.',
    )
    memory: AgentMemoryPolicy | None = Field(
        default=None,
        description='Optional immutable agent-level memory policy.',
    )
    output_schema: AgentOutputSchema | None = Field(
        default=None,
        description='Optional provider-neutral structured-output contract.',
    )
    webhook_endpoint: WebhookEndpoint | None = Field(
        default=None,
        description='Mode B webhook endpoint and vault secret reference.',
    )
    created_at: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when this immutable version was created.',
    )
    created_by: StrictStr = Field(
        ...,
        min_length=1,
        description='User or service principal that created this immutable version.',
    )

    @model_validator(mode='after')
    def _validate_mode_bound_fields(self) -> AgentVersion:
        if self.execution_mode == 'webhook':
            if self.webhook_endpoint is None:
                raise _WebhookEndpointRequiredError
        elif self.webhook_endpoint is not None:
            raise _WebhookEndpointModeError

        allowed_loci = {
            'worker': {'worker', 'hosted'},
            'webhook': {'webhook', 'hosted'},
            'hosted_only': {'hosted'},
        }[self.execution_mode]
        for tool in self.tools_snapshot:
            if tool.execution.locus not in allowed_loci:
                raise _ToolExecutionModeError(tool.execution.locus, self.execution_mode)
        _validate_tool_snapshot_dependencies(self.tools_snapshot)
        _validate_runtime_topology(self)
        return self


class TemplateMessageBinding(BaseModel):
    """Serializable, portal-editable trigger message templates."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['template'] = Field(..., description='Message binding kind.')
    messages: list[StrictStr] = Field(
        ...,
        min_length=1,
        description='Message templates with {{event.path}} interpolation placeholders.',
    )


class CallableMessageBinding(BaseModel):
    """SDK-only callable binding resolved by deployed code reference."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['callable'] = Field(..., description='Message binding kind.')
    module_path: StrictStr = Field(
        ...,
        min_length=1,
        description='Importable module path containing the callable.',
    )
    qualified_name: StrictStr = Field(
        ...,
        min_length=1,
        description='Qualified callable name inside module_path.',
    )
    content_hash: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^sha256:[0-9a-f]{64}$',
        description='Content hash pin for the deployed callable implementation.',
    )


MessageBinding: TypeAlias = Annotated[
    TemplateMessageBinding | CallableMessageBinding,
    Field(discriminator='kind'),
]


class AgentPeerDependency(BaseModel):
    """One declared input edge on a swarm member: a peer agent's or a tool's output.

    The dependency's result is injected into the member's task as labelled context under
    `arg_name` before the member runs. `kind='agent'` names another member in the same
    roster; `kind='tool'` names an invocation-local tool the run carries.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['agent', 'tool'] = Field(..., description='What kind of producer feeds this.')
    name: StrictStr = Field(
        ...,
        min_length=1,
        description='Roster agent name, or invocation-local tool id, that produces the value.',
    )
    arg_name: StrictStr = Field(
        ...,
        min_length=1,
        description='Label the produced value is injected under in the member task context.',
    )


class InvokeSystemToolsConfig(BaseModel):
    """Invocation-local allowlist and approvals for built-in server tools."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    allowed_system_tools: list[StrictStr] = Field(default_factory=list, max_length=16)
    approved_compose_argument_targets: list[StrictStr] = Field(default_factory=list, max_length=64)
    allow_private_data_in_system_tools: StrictBool | None = None
    allow_private_data_placeholders_in_system_tools: StrictBool | None = None


class InvokeAgentSpec(BaseModel):
    """An agent supplied inline on one invoke, executable by the server.

    Distinct from `Agent`, which is the identity of a *deployed* agent in the registry. An
    SDK-defined agent is ephemeral - it exists only for the run that declares it - but the
    server still has to be able to execute it, which means it needs the agent's persona, its
    model, and the tools it is allowed to reach.

    Without this the server sees only a flat list of function tools and cannot know that an
    agent exists, let alone decide to delegate to one. That is why delegation ended up in the
    SDK: it was the only place that still knew.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    name: StrictStr = Field(
        ...,
        min_length=1,
        description='Name the agent is addressed by within this run.',
        examples=['researcher'],
    )
    system_prompt: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Persona the agent runs under; without it the server cannot reproduce it.',
    )
    model: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Provider model this agent runs on; falls back to the parent run model.',
    )
    tool_ids: list[StrictStr] = Field(
        default_factory=list,
        max_length=256,
        description='Ids of the invocation-local tools this agent may call.',
    )
    system_tools_config: InvokeSystemToolsConfig | None = Field(
        default=None,
        description='Member built-in tool policy; intersected with an explicit parent policy.',
    )
    tools: list[FunctionToolSpec] = Field(
        default_factory=list,
        max_length=256,
        description=(
            'Function tool specs owned by this agent alone. A delegated run is handed these '
            'directly; without them a delegate arrives with an empty tool list, because its '
            'tools were never part of the parent run.'
        ),
    )
    attached_skill_ids: list[StrictStr] = Field(
        default_factory=list,
        max_length=256,
        description='Skills resolved into this agent before its first turn.',
    )
    description: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='What this agent is for; the swarm planner chooses members by it.',
    )
    use_as_final_output: StrictBool = Field(
        default=False,
        description='This member speaks for the swarm: its result is the run final output.',
    )
    included_nested_synthesis: Literal['auto', True, False] = Field(
        default='auto',
        description=(
            'Whether a delegated member adds a prose synthesis turn after its tools. '
            'False returns the member tool value directly; auto preserves server policy.'
        ),
    )
    final_tool_ids: list[StrictStr] = Field(
        default_factory=list,
        max_length=256,
        description='Tool ids among this agent tools eligible to provide its final result.',
    )
    peer_dependencies: list[AgentPeerDependency] = Field(
        default_factory=list,
        max_length=64,
        description='Declared inputs this member needs from peers or tools before it runs.',
    )
    agents: list[InvokeAgentSpec] | None = Field(
        default=None,
        max_length=64,
        description='Delegates owned by this agent, not additional members of its parent swarm.',
    )
    agent_tool_dependencies: list[AgentToolDependency] | None = Field(
        default=None,
        max_length=256,
        description='Tool arguments supplied by this agent nested delegates.',
    )

    @model_validator(mode='after')
    def _validate_nested_dependencies(self) -> InvokeAgentSpec:
        """Keep each inline dependency graph closed within its owning agent."""
        names = [agent.name for agent in self.agents or ()]
        if len(names) != len(set(names)):
            message = 'nested inline agent names must be unique'
            raise ValueError(message)
        unknown = {edge.agent_name for edge in self.agent_tool_dependencies or ()} - set(names)
        if unknown:
            message = f'agent tool dependencies name undeclared nested agents: {sorted(unknown)}'
            raise ValueError(message)
        return self


class AgentToolDependency(BaseModel):
    """A tool argument that is satisfied by delegating to another agent.

    The declaring tool never receives this argument from the model - the model is not even
    shown it. The server runs the named agent, and binds its result to `arg_name` before the
    tool executes.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    tool_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Tool whose argument this dependency fills.',
    )
    agent_name: StrictStr = Field(
        ...,
        min_length=1,
        description='Agent to delegate to, named in this run agents list.',
    )
    arg_name: StrictStr = Field(
        ...,
        min_length=1,
        description='Argument on the tool that receives the delegated agent result.',
    )
    optional: StrictBool = Field(
        default=False,
        description=(
            'Whether the declaring tool marked this argument optional. An optional '
            'dependency is presented to the model as a boolean toggle and delegated '
            'only when the model asks; a required one always delegates.'
        ),
    )


def _validate_runtime_topology(version: AgentVersion) -> None:
    """Validate one immutable compiled roster without changing legacy versions."""
    roster = version.agents_snapshot or []
    dependencies = version.agent_tool_dependencies or []
    if version.swarm_roster is True and not roster:
        message = 'a swarm roster requires at least one agent snapshot'
        raise ValueError(message)
    if version.swarm_roster is not True and (roster or dependencies):
        message = 'non-swarm agent versions cannot carry roster topology'
        raise ValueError(message)
    if not roster:
        return

    names = [agent.name for agent in roster]
    if len(set(names)) != len(names):
        message = 'swarm roster agent names must be unique'
        raise ValueError(message)
    if sum(agent.use_as_final_output for agent in roster) > 1:
        message = 'swarm roster may designate at most one final-output agent'
        raise ValueError(message)

    known_tool_ids = _known_runtime_tool_ids(version, roster)
    known_names = set(names)
    for agent in roster:
        _validate_runtime_member(agent, known_names, known_tool_ids)
    for dependency in dependencies:
        if dependency.agent_name not in known_names or dependency.tool_id not in known_tool_ids:
            message = 'agent tool dependency must reference the immutable roster and tools'
            raise ValueError(message)


def _validate_tool_snapshot_dependencies(tools: list[ToolSnapshot]) -> None:
    """Require deterministic, acyclic references among immutable tool snapshots."""
    names = [tool.name for tool in tools]
    if len(set(names)) != len(names):
        message = 'tool snapshot names must be unique'
        raise ValueError(message)
    known = set(names)
    outgoing: dict[str, list[str]] = {name: [] for name in names}
    for target in tools:
        for dependency in target.tool_dependencies or []:
            if dependency.tool_name not in known:
                message = f'tool {target.name!r} depends on an unknown tool'
                raise ValueError(message)
            outgoing[dependency.tool_name].append(target.name)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            message = 'tool snapshot dependencies cannot contain a cycle'
            raise ValueError(message)
        if name in visited:
            return
        visiting.add(name)
        for target in outgoing[name]:
            visit(target)
        visiting.remove(name)
        visited.add(name)

    for name in names:
        visit(name)


def _known_runtime_tool_ids(
    version: AgentVersion,
    roster: list[InvokeAgentSpec],
) -> set[str]:
    root_tool_ids = {tool.tool_id for tool in version.tools_snapshot if tool.tool_id is not None}
    member_tool_ids = {tool.tool_id for agent in roster for tool in agent.tools}
    return root_tool_ids | member_tool_ids


def _validate_runtime_member(
    agent: InvokeAgentSpec,
    known_names: set[str],
    known_tool_ids: set[str],
) -> None:
    if not set(agent.tool_ids).issubset(known_tool_ids):
        message = f'swarm member {agent.name!r} references an unknown tool id'
        raise ValueError(message)
    if not set(agent.final_tool_ids).issubset(set(agent.tool_ids)):
        message = f'swarm member {agent.name!r} final tools must be granted to that member'
        raise ValueError(message)
    for dependency in agent.peer_dependencies:
        known = (
            dependency.name in known_names
            if dependency.kind == 'agent'
            else dependency.name in known_tool_ids
        )
        if not known:
            message = f'swarm member {agent.name!r} has an unknown peer dependency'
            raise ValueError(message)


def _tool_types_namespace() -> dict[str, object]:
    tools_module = import_module('maivn_contracts.tools')
    return {
        'FunctionToolSpec': cast('object', tools_module.FunctionToolSpec),
        'ToolDependencyEdge': cast('object', tools_module.ToolDependencyEdge),
    }


ToolSnapshot.model_rebuild(_types_namespace=_tool_types_namespace())
InvokeAgentSpec.model_rebuild(_types_namespace=_tool_types_namespace())
AgentVersion.model_rebuild(_types_namespace=_tool_types_namespace())
