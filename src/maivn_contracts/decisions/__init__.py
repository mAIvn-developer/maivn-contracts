"""Shared, bounded inline image evidence for categorical Decisions."""

from __future__ import annotations

import base64
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

DecisionImageMime = Literal['image/png', 'image/jpeg', 'image/webp']
MAX_DECISION_IMAGE_BYTES = 1024 * 1024
_WEBP_HEADER_BYTES = 12


def _signature_matches(raw: bytes, mime_type: DecisionImageMime) -> bool:
    if mime_type == 'image/png':
        return raw.startswith(b'\x89PNG\r\n\x1a\n')
    if mime_type == 'image/jpeg':
        return raw.startswith(b'\xff\xd8\xff')
    return len(raw) >= _WEBP_HEADER_BYTES and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'


class DecisionImage(BaseModel):
    """Immutable inline public image evidence; never a URL or storage capability.

    Signature checks establish the declared container type, not image decodability
    or pixel redaction. The caller must authorize the complete image as public.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra='forbid',
        hide_input_in_errors=True,
        revalidate_instances='always',
    )

    mime_type: DecisionImageMime
    inline_base64: str = Field(min_length=1, max_length=1398104, repr=False)
    size_bytes: int = Field(ge=1, le=MAX_DECISION_IMAGE_BYTES)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def _validate_bytes(self) -> Self:
        try:
            raw = base64.b64decode(self.inline_base64, validate=True)
        except ValueError:
            message = 'Decision image requires canonical base64'
            raise ValueError(message) from None
        if base64.b64encode(raw).decode('ascii') != self.inline_base64:
            message = 'Decision image requires canonical base64'
            raise ValueError(message)
        if len(raw) != self.size_bytes or hashlib.sha256(raw).hexdigest() != self.content_hash:
            message = 'Decision image bytes do not match size and hash'
            raise ValueError(message)
        if not _signature_matches(raw, self.mime_type):
            message = 'Decision image signature does not match MIME type'
            raise ValueError(message)
        return self

    @classmethod
    def from_bytes(cls, raw: bytes, mime_type: DecisionImageMime) -> Self:
        """Validate image bytes and calculate their immutable size and hash."""
        if type(raw) is not bytes:
            message = 'Decision image requires bytes'
            raise TypeError(message)
        return cls(
            mime_type=mime_type,
            inline_base64=base64.b64encode(raw).decode('ascii'),
            size_bytes=len(raw),
            content_hash=hashlib.sha256(raw).hexdigest(),
        )


__all__ = ['MAX_DECISION_IMAGE_BYTES', 'DecisionImage', 'DecisionImageMime']
