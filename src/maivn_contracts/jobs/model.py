"""Explicit bounded detached-job options and durable, shielded status."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from maivn_contracts.messages import Message  # noqa: TC001 - Pydantic field schema.
from maivn_contracts.scenarios import ScenarioAgentBinding  # noqa: TC001 - Pydantic field schema.


class HostedJobOptions(BaseModel):
    """Required opt-in bounds; ordinary invocation defaults are unaffected."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    idempotency_key: StrictStr = Field(min_length=1, max_length=200, pattern=r'\S')
    max_steps: Annotated[int, Field(gt=0, strict=True)]
    max_duration_seconds: Annotated[float, Field(gt=0, le=1800, strict=True, allow_inf_nan=False)]
    registered_agent: ScenarioAgentBinding | None = None


JobTerminalReason = Literal[
    'completed',
    'failed',
    'cancelled',
    'interrupted',
    'execution_outcome_unknown',
    'deadline_exceeded',
    'steps_exhausted',
    'budget_exhausted',
    'start_failed',
    'authorization_revoked',
]


class HostedJobStatus(BaseModel):
    """Durable root outcome and shielded output; never a promise of crash continuation."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    session_id: StrictStr = Field(min_length=1)
    state: Literal['running', 'completed', 'failed', 'cancelled', 'budget_exhausted']
    terminal_reason: JobTerminalReason | None = None
    deadline_at: StrictStr
    max_steps: Annotated[int, Field(gt=0, strict=True)]
    steps_used: Annotated[int, Field(ge=0, strict=True)]
    max_expense_usd: StrictStr
    progress_position: Annotated[int, Field(ge=0, strict=True)] = 0
    final_message: Message | None = None
    result: Any | None = None
