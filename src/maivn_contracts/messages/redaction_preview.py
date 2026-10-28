"""Value-free wire models for POST /v1/redaction-previews."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from maivn_contracts.messages.model import (
    Attachment,  # noqa: TC001 - Pydantic resolves nested models at runtime.
    CoverRegion,  # noqa: TC001
    KnownPrivateData,  # noqa: TC001
    Message,  # noqa: TC001
    PIIWhitelist,  # noqa: TC001
)


class _PreviewModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)


class RedactionPreviewRequest(_PreviewModel):
    """Prompt or owned messages, with the same declarations as real intake."""

    prompt: StrictStr | Message | Annotated[list[Message], Field(min_length=1, max_length=128)] = (
        Field(repr=False)
    )
    attachments: list[Attachment] = Field(default_factory=list, max_length=32, repr=False)
    resources: list[StrictStr] = Field(default_factory=list, max_length=32)
    pii_whitelist: PIIWhitelist | None = Field(default=None, repr=False)
    known_pii_values: list[StrictStr | KnownPrivateData] | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        repr=False,
    )
    cover_regions: list[CoverRegion] | None = Field(
        default=None,
        max_length=256,
        description='Unconditional staff covers on the upright page frame; never whitelisted.',
        repr=False,
    )


class PreviewSpan(_PreviewModel):
    """Offsets into original and provider-bound text; never the covered value."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    redacted_start: int = Field(ge=0)
    redacted_end: int = Field(ge=0)


class PreviewRegion(_PreviewModel):
    """One-based page and top-left (x, y, width, height) page fractions.

    PDF crop box after rotation; images after EXIF transpose, matching PictureReport.
    """

    page: int = Field(ge=1)
    bbox: tuple[
        Annotated[float, Field(ge=0, le=1)],
        Annotated[float, Field(ge=0, le=1)],
        Annotated[float, Field(ge=0, le=1)],
        Annotated[float, Field(ge=0, le=1)],
    ]


class PreviewItem(_PreviewModel):
    """A redaction's key, type, context and placement, without its value."""

    key: str
    placeholder: str
    pii_type: str
    label: str | None = None
    description: str | None = None
    source: Literal['detected', 'declared', 'known_pii', 'caller_region', 'pattern']
    input_index: int = Field(ge=0)
    spans: list[PreviewSpan] = Field(default_factory=list)
    regions: list[PreviewRegion] = Field(default_factory=list)
    confidence: float | None = None


class PreviewStats(_PreviewModel):
    """Counts only; whitelisted values remain solely in the approved rendering."""

    entity_counts: dict[str, int] = Field(default_factory=dict)
    whitelisted: int = Field(default=0, ge=0)
    redacted_value_count: int = Field(default=0, ge=0)


class PreviewRefusal(_PreviewModel):
    """The same value-free refusal code and reason as invoke."""

    code: str
    reason: str


class PreviewCoveredImage(_PreviewModel):
    """The exact covered rendering the visual lane would send to a model."""

    inline_base64: str = Field(repr=False)
    media_type: str
    sha256: str


class PreviewInput(_PreviewModel):
    """One prompt, attachment or stored resource and its preview outcome."""

    kind: Literal['prompt', 'attachment', 'resource']
    message_index: int | None = None
    attachment_id: str | None = None
    resource_id: str | None = None
    redacted_text: str | None = Field(default=None, repr=False)
    covered_image: PreviewCoveredImage | None = Field(default=None, repr=False)
    status: Literal['redacted', 'unchanged', 'refused']
    refusal: PreviewRefusal | None = None
    stats: PreviewStats = Field(default_factory=PreviewStats)


class RedactionPreviewResponse(_PreviewModel):
    """Safe renderings, placement metadata and optional sealed approved-copy ticket."""

    preview_id: str | None = Field(default=None, repr=False)
    approved_request: list[Message] | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            'Exact shielded messages sealed by preview_id, including covered inline attachments, '
            'structured content and redaction policy. Present only when a ticket is issued.'
        ),
        repr=False,
    )
    inputs: list[PreviewInput]
    items: list[PreviewItem] = Field(default_factory=list)
    stats: PreviewStats = Field(default_factory=PreviewStats)
    declared_matched: list[str] = Field(default_factory=list)
    declared_unmatched: list[str] = Field(default_factory=list)
