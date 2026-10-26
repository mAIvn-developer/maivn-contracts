"""Hand-authored Pydantic models for owned tool contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from maivn_contracts.artifacts import ArtifactRef
from maivn_contracts.tools.authorization import ToolSafetyLabels

IdempotencyHint: TypeAlias = Literal['idempotent', 'non_idempotent', 'unknown']
AuthScheme: TypeAlias = Literal['api_key', 'bearer', 'basic', 'oauth', 'custom']
SchemaPolicy: TypeAlias = Literal['passthrough']
TimeoutMs: TypeAlias = Annotated[int, Field(ge=1, le=600000, strict=True)]
PositiveStrictInt: TypeAlias = Annotated[int, Field(ge=1, strict=True)]
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]


class AuthRef(BaseModel):
    """Vault-referenced authentication material for tool execution."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    scheme: AuthScheme = Field(..., description='Authentication scheme resolved by the executor.')
    secret_ref: StrictStr = Field(
        ...,
        pattern=r'^vault://',
        description='Vault reference for credentials; raw secrets are structurally absent.',
    )


class MCPRegistryServerRef(BaseModel):
    """Registered official MCP server reference."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['registry'] = Field(..., description='MCP server reference discriminator.')
    name: StrictStr = Field(..., min_length=1, description='Registered official MCP server name.')


class MCPUrlServerRef(BaseModel):
    """Vault-referenced MCP server URL."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['url'] = Field(..., description='MCP server reference discriminator.')
    url_ref: StrictStr = Field(
        ...,
        pattern=r'^vault://',
        description='Vault reference containing the MCP server URL.',
    )


MCPServerRef: TypeAlias = Annotated[
    MCPRegistryServerRef | MCPUrlServerRef,
    Field(discriminator='kind'),
]


class ToolSpec(ToolSafetyLabels):
    """Shared fields for every owned tool specification."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    tool_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable tool specification identifier.',
    )
    namespace: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z][A-Za-z0-9_.-]*$',
        description='Registration namespace.',
    )
    version: StrictStr = Field(..., min_length=1, description='Tool spec version stamp.')
    idempotency: IdempotencyHint = Field(..., description='Retry and duplicate-suppression hint.')
    timeout_ms: TimeoutMs = Field(..., description='Maximum execution budget in milliseconds.')
    auth: AuthRef | None = Field(
        default=None,
        description='Optional vault-referenced auth material.',
    )


class ToolDependencyEdge(BaseModel):
    """Tool->tool argument edge: arg_name is produced by tool_name's result."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    tool_name: StrictStr = Field(..., min_length=1, description='Producing tool name.')
    arg_name: StrictStr = Field(..., min_length=1, description='Consuming argument name.')
    result_scope: Literal['invocation', 'conversation'] = Field(
        default='invocation',
        description='Conversation permits reuse of a retained producer result in the same thread.',
    )
    revision_policy: Literal['on_validation_error'] | None = Field(
        default=None,
        description=(
            'Explicit authorization for SDK-local reconstruction after a validation failure. '
            'Absent policy never permits revision.'
        ),
    )


class ToolArgumentProducerRequirement(BaseModel):
    """A caller-authored argument reference that must come from another tool."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    argument_path: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$',
        description='Dot-separated path to the consuming argument or nested field.',
    )
    producer_tool_name: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z_][A-Za-z0-9_-]*$',
        description='Tool whose returned reference must be supplied at argument_path.',
    )
    reference_kind: Literal['composition_reference'] = Field(
        ...,
        description='Nominal kind of producer-issued reference required by the consumer.',
    )


class ToolArgumentDependency(BaseModel):
    """Human-owned function argument resolved through the canonical interrupt plane."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    arg_name: StrictStr = Field(..., min_length=1, description='Human-supplied argument name.')
    prompt_source: Literal['authored', 'agent_generated', 'fallback'] = Field(
        default='authored',
        description='Provenance governing question materialization.',
    )
    question: StrictStr = Field(
        default='',
        description='Authored question, or blank until agent generation.',
    )
    response_schema: dict[str, Any] = Field(
        default_factory=lambda: {'type': 'string'},
        description='Stored JSON Schema used to validate the human answer.',
    )


class FunctionToolSpec(ToolSpec):
    """Function tool specification for SDK callables and method tools."""

    kind: Literal['function'] = Field(..., description='Tool spec discriminator.')
    name: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z_][A-Za-z0-9_-]*$',
        description='Model-facing function tool name.',
    )
    description: StrictStr = Field(
        ...,
        min_length=1,
        description='Human-readable behavior description for model planning.',
    )
    input_schema: dict[str, Any] = Field(
        ...,
        min_length=1,
        description='JSON Schema for tool arguments.',
    )
    output_schema: dict[str, Any] | None = Field(
        default=None,
        min_length=1,
        description='Optional JSON Schema for tool results.',
    )
    model_constructor: bool | None = Field(
        default=None,
        description='True when this SDK function tool constructs a Pydantic model.',
    )
    always_execute: bool | None = Field(
        default=None,
        description='Deterministically execute once declared dependencies resolve.',
    )
    tool_dependencies: tuple[ToolDependencyEdge, ...] | None = Field(
        default=None,
        description='Tool->tool argument edges feeding this tool.',
    )
    argument_producer_requirements: tuple[ToolArgumentProducerRequirement, ...] | None = Field(
        default=None,
        description=(
            'Caller-authored argument paths that require references issued by named producer tools.'
        ),
    )
    interrupt_dependencies: tuple[ToolArgumentDependency, ...] | None = Field(
        default=None,
        description='Human-owned arguments resolved through durable interrupt checkpoints.',
    )

    @model_validator(mode='after')
    def _unique_argument_producer_paths(self) -> FunctionToolSpec:
        paths: set[str] = set()
        for requirement in self.argument_producer_requirements or ():
            if requirement.argument_path in paths:
                message = f'duplicate argument producer requirement for {requirement.argument_path}'
                raise ValueError(message)
            paths.add(requirement.argument_path)
        return self


class MCPToolSpec(ToolSpec):
    """MCP tool specification for official server-backed connectors."""

    kind: Literal['mcp'] = Field(..., description='Tool spec discriminator.')
    server_ref: MCPServerRef = Field(..., description='MCP server reference.')
    tool_name: StrictStr = Field(..., min_length=1, description='Raw MCP server tool name.')
    schema_policy: SchemaPolicy = Field(
        ...,
        description='MCP schema handling policy.',
    )
    input_schema: dict[str, Any] = Field(
        ...,
        min_length=1,
        description='MCP-published JSON Schema for tool arguments.',
    )
    output_schema: dict[str, Any] | None = Field(
        default=None,
        min_length=1,
        description='Optional MCP-published JSON Schema for tool results.',
    )


class SystemToolSpec(ToolSpec):
    """Platform built-in tool specification."""

    kind: Literal['system'] = Field(..., description='Tool spec discriminator.')
    name: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z_][A-Za-z0-9_-]*$',
        description='Platform built-in tool name.',
    )
    description: StrictStr = Field(
        ...,
        min_length=1,
        description='Human-readable behavior description for model planning.',
    )
    input_schema: dict[str, Any] = Field(
        ...,
        min_length=1,
        description='JSON Schema for system tool arguments.',
    )
    output_schema: dict[str, Any] | None = Field(
        default=None,
        min_length=1,
        description='Optional JSON Schema for system tool results.',
    )


ToolSpecVariant: TypeAlias = Annotated[
    FunctionToolSpec | MCPToolSpec | SystemToolSpec,
    Field(discriminator='kind'),
]


class ToolSpecRef(BaseModel):
    """Reference to a versioned ToolSpec."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    tool_id: StrictStr = Field(..., min_length=1, description='Referenced ToolSpec.tool_id.')
    namespace: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z][A-Za-z0-9_.-]*$',
        description='Referenced ToolSpec.namespace.',
    )
    version: StrictStr = Field(..., min_length=1, description='Referenced ToolSpec.version.')


class ToolCallLineage(BaseModel):
    """Trace lineage for a model-emitted tool call."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    session_id: StrictStr = Field(..., min_length=1, description='Owning session id.')
    invocation_id: StrictStr = Field(..., min_length=1, description='Owning invocation id.')
    agent_id: StrictStr | None = Field(default=None, min_length=1, description='Emitting agent id.')
    message_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Assistant message or provider event that emitted this call.',
    )
    parent_call_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Parent tool call id for nested calls.',
    )
    root_call_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Root tool call id for nested calls.',
    )
    relation: Literal['dependency_revision'] | None = Field(
        default=None,
        description='Explicit relation for an SDK-local dependency reconstruction call.',
    )


class RetainedToolResult(BaseModel):
    """Server-bound earlier result for an explicitly reusable dependency argument."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    thread_id: StrictStr = Field(..., min_length=1)
    source_session_id: StrictStr = Field(..., min_length=1)
    source_call_id: StrictStr = Field(..., min_length=1)
    producer: ToolSpecRef
    result: Any = Field(
        ..., description='Retained tool result, with private placeholders preserved.'
    )


class ToolCall(BaseModel):
    """Model-emitted request to invoke a referenced ToolSpec."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    call_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Provider/model tool-call identifier.',
    )
    spec_ref: ToolSpecRef = Field(..., description='Referenced tool specification.')
    arguments: dict[str, Any] = Field(
        ...,
        description='Model-supplied JSON arguments validated against the ToolSpec.',
    )
    lineage: ToolCallLineage = Field(..., description='Tool call trace lineage.')
    retained_dependencies: dict[str, RetainedToolResult] | None = Field(
        default=None,
        description='Server-bound prior results by consuming argument; never model-authored.',
    )


ToolOutcomeArtifactRef: TypeAlias = ArtifactRef
"""Deprecated import-compatibility alias for the canonical ArtifactRef union."""


class ToolOutcomeError(BaseModel):
    """Typed tool execution error."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    code: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[a-z][a-z0-9_]*$',
        description='Stable machine-readable error code.',
    )
    message: StrictStr = Field(
        ...,
        min_length=1,
        max_length=2048,
        description='Non-sensitive human-readable error summary.',
    )
    retryable: StrictBool = Field(
        ...,
        description='Whether the caller may retry the same call after backoff.',
    )


class ToolOutcome(BaseModel):
    """Shared fields for every tool execution outcome."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    call_id: StrictStr = Field(..., min_length=1, description='ToolCall.call_id this resolves.')
    duration_ms: NonNegativeStrictInt = Field(..., description='Execution duration in ms.')
    artifact_refs: tuple[ArtifactRef, ...] | None = Field(
        default=None,
        max_length=32,
        description='Optional canonical immutable artifact references produced by the tool.',
    )


class OkToolOutcome(ToolOutcome):
    """Successful tool execution outcome."""

    status: Literal['ok'] = Field(..., description='Outcome discriminator.')
    result: Any = Field(..., description='JSON-serializable tool result payload.')


class ErrorToolOutcome(ToolOutcome):
    """Failed tool execution outcome."""

    status: Literal['error'] = Field(..., description='Outcome discriminator.')
    error: ToolOutcomeError = Field(..., description='Typed execution error.')


ToolOutcomeVariant: TypeAlias = Annotated[
    OkToolOutcome | ErrorToolOutcome,
    Field(discriminator='status'),
]


class ToolDispatch(ToolSafetyLabels):
    """JSON-only external tool delivery envelope."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal[1]
    dispatch_id: StrictStr = Field(..., min_length=1)
    attempt_id: StrictStr = Field(..., min_length=1)
    attempt: PositiveStrictInt
    organization_id: StrictStr = Field(..., min_length=1)
    project_id: StrictStr = Field(..., min_length=1)
    agent_id: StrictStr = Field(..., min_length=1)
    agent_version: PositiveStrictInt
    execution_mode: Literal['worker', 'webhook']
    session_id: StrictStr = Field(..., min_length=1)
    call_id: StrictStr = Field(..., min_length=1)
    tool_id: StrictStr = Field(..., min_length=1)
    tool_name: StrictStr = Field(..., min_length=1)
    arguments: dict[str, Any]
    idempotency: IdempotencyHint
    timeout_ms: TimeoutMs
    created_at: StrictStr = Field(..., min_length=1)
    deadline_at: StrictStr = Field(..., min_length=1)
    response_mode: Literal['sync', 'async']
    callback_url: StrictStr | None = Field(default=None, min_length=1)
    callback_token: StrictStr | None = Field(default=None, min_length=1)
    extensions: dict[str, Any] | None = None


class ToolCallback(BaseModel):
    """External tool result envelope containing the established ToolOutcome union."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal[1]
    dispatch_id: StrictStr = Field(..., min_length=1)
    attempt_id: StrictStr = Field(..., min_length=1)
    session_id: StrictStr = Field(..., min_length=1)
    call_id: StrictStr = Field(..., min_length=1)
    completed_at: StrictStr = Field(..., min_length=1)
    outcome: ToolOutcomeVariant
