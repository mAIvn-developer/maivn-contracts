"""Metadata-only events emitted by an explicitly running local file watcher."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)

_FIRST_PRINTABLE = 32


class LocalFileEvent(BaseModel):
    """Immutable local event identity without file contents or absolute host paths."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    event_id: StrictStr = Field(
        pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    )
    watch_id: StrictStr = Field(
        min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$'
    )
    operation: Literal['created', 'modified']
    observed_at: AwareDatetime
    relative_path: StrictStr = Field(min_length=1, max_length=1024)
    size_bytes: StrictInt = Field(ge=0, le=2**53 - 1)
    mtime_ns: StrictStr = Field(pattern=r'^[0-9]{1,20}$')

    @field_validator('observed_at', mode='before')
    @classmethod
    def explicit_timestamp(cls, value: Any) -> Any:
        """Require an explicit timezone-aware timestamp rather than an inferred epoch."""
        if not isinstance(value, (str, datetime)) or (
            isinstance(value, str) and 'T' not in value.upper()
        ):
            message = 'observed_at must be an explicit timestamp with a timezone'
            raise ValueError(message)
        return value

    @field_validator('relative_path')
    @classmethod
    def relative_metadata_path(cls, value: str) -> str:
        """Accept only canonical POSIX relative paths with valid Unicode text."""
        if (
            '\\' in value
            or ':' in value
            or any(part in ('', '.', '..') for part in value.split('/'))
            or any(ord(char) < _FIRST_PRINTABLE for char in value)
        ):
            message = 'relative_path must be a canonical relative POSIX path'
            raise ValueError(message)
        try:
            value.encode('utf-8')
        except UnicodeError as exc:
            message = 'relative_path must contain valid Unicode text'
            raise ValueError(message) from exc
        return value
