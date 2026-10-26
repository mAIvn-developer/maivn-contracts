"""Node and trace models of the session trace; `maivn_contracts.events.trace` re-exports them."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

TraceNodeKind: TypeAlias = Literal[
    'run',
    'tool',
    'working',
    'memory',
    'resource',
    'shield',
    'interrupt',
    'trigger',
    'routing',
    'model',
    'hook',
    'decision',
]


TraceNodeStatus: TypeAlias = Literal['running', 'completed', 'failed', 'cancelled', 'waiting']


class TraceTokens(BaseModel):
    """Token spend attributed to one run node."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    input_tokens: StrictInt = Field(default=0, ge=0)
    output_tokens: StrictInt = Field(default=0, ge=0)
    cache_read_tokens: StrictInt = Field(default=0, ge=0)
    cache_creation_tokens: StrictInt = Field(default=0, ge=0)


class TraceNode(BaseModel):
    """One curated node of the session trace tree."""

    model_config = ConfigDict(extra='forbid')

    node_id: StrictStr = Field(..., min_length=1)
    kind: TraceNodeKind
    name: StrictStr = Field(..., min_length=1)
    status: TraceNodeStatus
    started_at: StrictStr | None = None
    ended_at: StrictStr | None = None
    duration_ms: StrictInt | None = Field(default=None, ge=0)
    tokens: TraceTokens | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    children: list[TraceNode] = Field(default_factory=list)


class SessionTrace(BaseModel):
    """The assembled trace for one session and its delegated children.

    Single-level shape only - this model is unchanged from its pre-S6 form and its
    serialization is byte-identical to before. The recursive `/v1/sessions/{id}/trace`
    endpoint uses `RecursiveSessionTrace` below instead of adding a field here, so
    every existing single-level caller (data-plane session trace, control-plane
    `/v1/runs/{id}/trace`) keeps emitting exactly the same bytes it always has.
    """

    model_config = ConfigDict(extra='forbid')

    session_id: StrictStr = Field(..., min_length=1)
    root: TraceNode


class RecursiveSessionTrace(SessionTrace):
    """`SessionTrace` for the recursive assembly path - `truncated` is required.

    A `SessionTrace` never lies about truncation because it never claims to be
    complete: the field simply does not exist there. Only the recursive assembler,
    which actually enforces descendant-session and event caps, is allowed to say
    whether it cut the tree short.
    """

    truncated: bool = Field(
        ...,
        description='True when a descendant-session or event cap cut the assembled tree short.',
    )


__all__ = [
    'RecursiveSessionTrace',
    'SessionTrace',
    'TraceNode',
    'TraceTokens',
]
