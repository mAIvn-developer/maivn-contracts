"""Explicit bounded detached-job options and durable, shielded status."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator
from typing_extensions import Self

from maivn_contracts.messages import Message  # noqa: TC001 - Pydantic field schema.
from maivn_contracts.scenarios import ScenarioAgentBinding  # noqa: TC001 - Pydantic field schema.

HOSTED_JOB_STANDARD_DURATION_SECONDS = 1800
HOSTED_JOB_EXTENDED_DURATION_SECONDS = 7200
HOSTED_JOB_EXTENDED_IDLE_SECONDS = 600


class HostedJobOptions(BaseModel):
    """Required opt-in bounds; ordinary invocation defaults are unaffected."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        json_schema_extra={
            'if': {'properties': {'profile': {'const': 'extended'}}, 'required': ['profile']},
            'else': {
                'properties': {
                    'max_duration_seconds': {'maximum': HOSTED_JOB_STANDARD_DURATION_SECONDS}
                }
            },
        },
    )
    idempotency_key: StrictStr = Field(min_length=1, max_length=200, pattern=r'\S')
    max_steps: Annotated[int, Field(gt=0, strict=True)]
    max_duration_seconds: Annotated[
        float,
        Field(gt=0, le=HOSTED_JOB_EXTENDED_DURATION_SECONDS, strict=True, allow_inf_nan=False),
    ]
    registered_agent: ScenarioAgentBinding | None = None
    profile: Literal['standard', 'extended'] = Field(
        default='standard',
        exclude_if=lambda value: value == 'standard',
        description=(
            'Standard permits up to 1800 seconds. Extended permits up to 7200 seconds '
            'and expires after 600 seconds without durable progress.'
        ),
    )

    @model_validator(mode='after')
    def within_profile_duration(self) -> Self:
        """Require explicit extended admission for a duration over thirty minutes."""
        if (
            self.profile == 'standard'
            and self.max_duration_seconds > HOSTED_JOB_STANDARD_DURATION_SECONDS
        ):
            message = 'standard hosted jobs allow at most 1800 seconds'
            raise ValueError(message)
        return self


JobTerminalReason = Literal[
    'completed',
    'failed',
    'cancelled',
    'interrupted',
    'execution_outcome_unknown',
    'deadline_exceeded',
    'idle_timeout',
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
    profile: Literal['standard', 'extended'] = Field(
        default='standard', exclude_if=lambda value: value == 'standard'
    )
    idle_deadline_at: StrictStr | None = Field(default=None, exclude_if=lambda value: value is None)
