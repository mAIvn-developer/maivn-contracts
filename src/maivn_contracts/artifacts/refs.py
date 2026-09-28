"""Committed immutable artifact reference projections."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import (
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts.primitives import (
    ASCII_CONTROL_LIMIT,
    ASCII_DELETE,
    MIME_TYPES_BY_KIND,
    PRIVATE_DELETION_STATES,
    PRIVATE_LABEL_BY_KIND,
    ArtifactKind,
    ArtifactRefInvariantError,
    ClosedModel,
    ImageAxisPixels,
    MimeType,
    OpaqueTokenId,
    OrdinaryArtifactState,
    PositiveStrictInt,
    PrivateArtifactState,
    PrivateDisplayLabel,
    ProducerClass,
    Rfc3339Timestamp,
    ValidationProfile,
    ValidationVersion,
)

__all__ = [
    'ArtifactRef',
    'AudioSafePreview',
    'DocumentSafePreview',
    'EffectiveRetention',
    'ImageSafePreview',
    'OrdinaryArtifactRef',
    'PresentationSafePreview',
    'PrivateArtifactRef',
    'PrivateProducerLineage',
    'ProducerLineage',
    'RetrievalAction',
    'SafePreview',
    'ValidationReceipt',
    'WorkbookSafePreview',
    '_ArtifactRefBase',
]


class EffectiveRetention(ClosedModel):
    """Effective retention policy frozen for one immutable artifact revision."""

    policy_snapshot_id: OpaqueTokenId
    retention_class: OpaqueTokenId
    expires_at: Rfc3339Timestamp


class ProducerLineage(ClosedModel):
    """Value-free producer and invocation lineage identifiers."""

    producer_class: ProducerClass
    producer_id: OpaqueTokenId
    root_invocation_id: OpaqueTokenId
    session_id: OpaqueTokenId | None = None
    call_id: OpaqueTokenId | None = None
    dispatch_id: OpaqueTokenId | None = None
    attempt_id: OpaqueTokenId | None = None


class PrivateProducerLineage(ClosedModel):
    """Vault-only value-free producer lineage for a private artifact."""

    producer_class: Literal['vault']
    producer_id: OpaqueTokenId
    root_invocation_id: OpaqueTokenId
    session_id: OpaqueTokenId | None = None
    call_id: OpaqueTokenId | None = None
    dispatch_id: OpaqueTokenId | None = None
    attempt_id: OpaqueTokenId | None = None


class ValidationReceipt(ClosedModel):
    """Value-free evidence that ordinary artifact bytes were validated."""

    receipt_id: OpaqueTokenId
    status: Literal['validated']
    validator_profile: ValidationProfile
    validator_version: ValidationVersion


class RetrievalAction(ClosedModel):
    """Relation used to authorize later retrieval without embedding a URL."""

    relation: Literal[
        'artifact.download_authorization',
        'artifact.vault_download_authorization',
    ]


class DocumentSafePreview(ClosedModel):
    """Safe document characteristics derived during validation."""

    kind: Literal['document']
    page_count: Annotated[StrictInt, Field(ge=1, le=500)]


class WorkbookSafePreview(ClosedModel):
    """Safe workbook characteristics derived during validation."""

    kind: Literal['spreadsheet']
    sheet_count: Annotated[StrictInt, Field(ge=1, le=100)]


class PresentationSafePreview(ClosedModel):
    """Safe presentation characteristics derived during validation."""

    kind: Literal['presentation']
    slide_count: Annotated[StrictInt, Field(ge=1, le=500)]


class ImageSafePreview(ClosedModel):
    """Safe raster dimensions derived during validation."""

    kind: Literal['image']
    # The aggregate 40 MP policy is enforced at finalize, not in this public projection.
    width_pixels: ImageAxisPixels
    height_pixels: ImageAxisPixels


class AudioSafePreview(ClosedModel):
    """Safe audio duration derived during validation."""

    kind: Literal['audio']
    duration_seconds: Annotated[float, Field(strict=True, gt=0, le=7200)]


SafePreview: TypeAlias = Annotated[
    DocumentSafePreview
    | WorkbookSafePreview
    | PresentationSafePreview
    | ImageSafePreview
    | AudioSafePreview,
    Field(discriminator='kind'),
]


class _ArtifactRefBase(ClosedModel):
    artifact_id: OpaqueTokenId
    logical_output_id: OpaqueTokenId
    revision: PositiveStrictInt
    kind: ArtifactKind
    mime_type: MimeType
    created_at: Rfc3339Timestamp
    effective_retention: EffectiveRetention
    supersedes_artifact_id: OpaqueTokenId | None = None

    @model_validator(mode='after')
    def _validate_common_identity(self) -> _ArtifactRefBase:
        if (self.revision == 1) != (self.supersedes_artifact_id is None):
            raise ArtifactRefInvariantError
        if self.mime_type not in MIME_TYPES_BY_KIND[self.kind]:
            raise ArtifactRefInvariantError
        return self


class OrdinaryArtifactRef(_ArtifactRefBase):
    """Committed immutable reference to an ordinary-custody artifact."""

    custody: Literal['ordinary']
    state: OrdinaryArtifactState
    display_filename: StrictStr = Field(min_length=1, max_length=255)
    size_bytes: PositiveStrictInt
    sha256: StrictStr = Field(pattern=r'^[0-9a-f]{64}$')
    producer: ProducerLineage
    validation_receipt: ValidationReceipt
    safe_preview: SafePreview | None = None
    retrieval_action: RetrievalAction

    @field_validator('display_filename')
    @classmethod
    def _validate_display_filename(cls, value: str) -> str:
        if (
            value in {'.', '..'}
            or '/' in value
            or '\\' in value
            or value != value.strip()
            or any(
                ord(character) < ASCII_CONTROL_LIMIT or ord(character) == ASCII_DELETE
                for character in value
            )
        ):
            raise ArtifactRefInvariantError
        return value

    @model_validator(mode='after')
    def _validate_safe_preview_kind(self) -> OrdinaryArtifactRef:
        if self.retrieval_action.relation != 'artifact.download_authorization':
            raise ArtifactRefInvariantError
        if self.kind == 'other' and self.safe_preview is not None:
            raise ArtifactRefInvariantError
        if self.safe_preview is not None and self.safe_preview.kind != self.kind:
            raise ArtifactRefInvariantError
        return self


class PrivateArtifactRef(_ArtifactRefBase):
    """Committed immutable value-free reference issued by the private vault."""

    custody: Literal['vault_private']
    state: PrivateArtifactState
    display_label: PrivateDisplayLabel
    producer: PrivateProducerLineage
    creation_receipt_id: OpaqueTokenId
    deletion_receipt_id: OpaqueTokenId | None = None
    retrieval_action: RetrievalAction

    @model_validator(mode='after')
    def _validate_private_projection(self) -> PrivateArtifactRef:
        if self.retrieval_action.relation != 'artifact.vault_download_authorization':
            raise ArtifactRefInvariantError
        if self.display_label != PRIVATE_LABEL_BY_KIND[self.kind]:
            raise ArtifactRefInvariantError
        needs_deletion_receipt = self.state in PRIVATE_DELETION_STATES
        if needs_deletion_receipt != (self.deletion_receipt_id is not None):
            raise ArtifactRefInvariantError
        return self


ArtifactRef: TypeAlias = Annotated[
    OrdinaryArtifactRef | PrivateArtifactRef,
    Field(discriminator='custody'),
]
