"""Hand-authored Pydantic models for Mode A worker contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictStr

WorkerConnectionStatus: TypeAlias = Literal['connected', 'draining', 'disconnected', 'stale']
WorkerFrameType: TypeAlias = Literal[
    'register',
    'registered',
    'heartbeat',
    'draining',
    'dispatch',
    'dispatch_ack',
    'tool_result',
    'error',
]
PositiveStrictInt: TypeAlias = Annotated[int, Field(ge=1, strict=True)]
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]
CapabilityValue: TypeAlias = bool | int | float | str


class WorkerConnection(BaseModel):
    """Observable, non-secret record for one authenticated worker connection."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal[1]
    connection_id: StrictStr = Field(..., min_length=1)
    worker_id: StrictStr = Field(..., min_length=1)
    connection_epoch: PositiveStrictInt
    organization_id: StrictStr = Field(..., min_length=1)
    project_id: StrictStr = Field(..., min_length=1)
    protocol_version: Literal[1]
    sdk_version: StrictStr = Field(..., min_length=1)
    capabilities: dict[StrictStr, CapabilityValue]
    max_in_flight: PositiveStrictInt = Field(..., le=1024)
    status: WorkerConnectionStatus
    connected_at: StrictStr = Field(..., min_length=1)
    last_heartbeat_at: StrictStr = Field(..., min_length=1)
    disconnected_at: StrictStr | None = Field(default=None, min_length=1)


class WorkerFrame(BaseModel):
    """Closed v1 worker frame; JSON Schema validates the type-specific payload."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    protocol_version: Literal[1]
    type: WorkerFrameType
    frame_id: StrictStr = Field(..., min_length=1)
    sent_at: StrictStr = Field(..., min_length=1)
    payload: dict[str, Any]
    frame_hmac: StrictStr = Field(..., min_length=1)
    extensions: dict[str, Any] | None = None
