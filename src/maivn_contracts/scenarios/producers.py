"""Typed application inputs and receipts for existing SLA and reply sources."""

from __future__ import annotations

import json
from datetime import datetime  # noqa: TC003 - Pydantic field.
from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003 - Pydantic field.

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictStr, model_validator

InstanceKey = Annotated[StrictStr, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$')]
_MAX_BODY_BYTES = 262_144


class ProducerBody(BaseModel):
    """Closed, bounded producer input; never a raw provider envelope."""

    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

    @model_validator(mode='after')
    def bounded_body(self) -> ProducerBody:
        """Keep the full normalized request within the producer payload budget."""
        if (
            len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode())
            > _MAX_BODY_BYTES
        ):
            message = 'producer body exceeds 262144 bytes'
            raise ValueError(message)
        return self


class ArmSLATimerRequest(ProducerBody):
    """Arm one immutable business instance with server-owned time and deadline."""

    instance_key: InstanceKey
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class SatisfySLATimerRequest(ProducerBody):
    """Record application evidence that the declared condition occurred."""

    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class ConversationReplyRequest(ProducerBody):
    """One developer-originated text reply with caller-stable retry identity."""

    conversation_key: StrictStr = Field(min_length=1, max_length=500, pattern=r'\S')
    reply_id: StrictStr = Field(min_length=1, max_length=200, pattern=r'\S')
    content: StrictStr = Field(min_length=1, max_length=65_536, pattern=r'\S')


class SLATimerReceipt(BaseModel):
    """Durable timer state; processed does not imply successful model execution."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    timer_id: StrictStr
    instance_key: InstanceKey
    condition: StrictStr
    fire_when: Literal['condition_met', 'condition_missing']
    started_at: datetime
    deadline_at: datetime
    condition_met_at: datetime | None
    processed_at: datetime | None
    process_outcome: StrictStr | None
    inserted: StrictBool = False


class ConversationReplyReceipt(BaseModel):
    """Committed source receipt, awaiting ordinary event-plane admission."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    event_id: StrictStr
    conversation_id: UUID
    reply_id: StrictStr
    sequence: int = Field(strict=True, gt=0)
    received_at: datetime
    inserted: StrictBool
