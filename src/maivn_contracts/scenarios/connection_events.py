"""Source-owned payloads for signed developer connection producers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from typing_extensions import Self

_MAX_SAFE_INTEGER = 2**53 - 1
_MAX_BODY_BYTES = 262_144

FormIdentifier = Annotated[
    StrictStr, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$')
]
FormFieldName = Annotated[StrictStr, Field(min_length=1, max_length=100)]
FormScalar = (
    Annotated[StrictStr, Field(max_length=8192)]
    | Annotated[StrictInt, Field(ge=-_MAX_SAFE_INTEGER, le=_MAX_SAFE_INTEGER)]
    | Annotated[
        StrictFloat, Field(ge=-_MAX_SAFE_INTEGER, le=_MAX_SAFE_INTEGER, allow_inf_nan=False)
    ]
    | StrictBool
    | None
)
FormFieldValue = FormScalar | Annotated[list[FormScalar], Field(max_length=100)]


class FormSubmittedEvent(BaseModel):
    """Selected form fields with immutable caller-owned submission identity."""

    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

    form_id: FormIdentifier
    submission_id: StrictStr = Field(min_length=1, max_length=200, pattern=r'\S')
    submitted_at: AwareDatetime
    fields: dict[FormFieldName, FormFieldValue] = Field(max_length=100)

    @field_validator('submitted_at', mode='before')
    @classmethod
    def require_explicit_timestamp(cls, value: Any) -> Any:
        """Accept an explicit datetime, not an implicitly converted epoch number."""
        if not isinstance(value, (str, datetime)):
            message = 'submitted_at must be a timestamp with a timezone'
            raise ValueError(message)  # noqa: TRY004 - Pydantic converts ValueError into input refusal.
        if isinstance(value, str) and 'T' not in value.upper():
            message = 'submitted_at must be an ISO timestamp, not an epoch number'
            raise ValueError(message)
        return value

    @model_validator(mode='after')
    def bound_encoded_payload(self) -> Self:
        """Keep publisher and receiver payloads inside the same ingress budget."""
        try:
            body = json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode('utf-8')
        except UnicodeError as exc:
            message = 'form fields must contain valid Unicode text'
            raise ValueError(message) from exc
        if len(body) > _MAX_BODY_BYTES:
            message = 'form payload exceeds 262144 bytes'
            raise ValueError(message)
        return self
