"""Hand-authored Pydantic models for resource-processing contracts."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

if TYPE_CHECKING:
    from maivn_contracts.messages import Attachment

ResourceTier: TypeAlias = Literal['direct', 'indexed', 'secure']
ProcessingStatus: TypeAlias = Literal[
    'pending',
    'processing',
    'ready',
    'failed',
    'quarantined',
    'redaction_failed',
]
ArtifactKind: TypeAlias = Literal['markdown', 'redacted_markdown', 'redacted_image', 'sidecar_map']
PositiveStrictInt: TypeAlias = Annotated[int, Field(ge=1, strict=True)]
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(ge=0, strict=True)]
OcrConfidence: TypeAlias = Annotated[float, Field(ge=0, le=1)]
InlineArtifactText: TypeAlias = Annotated[StrictStr, Field(min_length=1, max_length=262144)]

_RESOURCE_TIERS: frozenset[str] = frozenset({'direct', 'indexed', 'secure'})


class ResourceTierResolutionError(ValueError):
    """Base error for resource tier boundary-rule failures."""


class ResourceTierDowngradeError(ResourceTierResolutionError):
    """Raised when a redacted message attempts to lower the secure floor."""

    def __init__(self, policy_tier: str) -> None:
        """Build the secure-floor downgrade error."""
        message = f'Redacted message attachments have a secure floor; got {policy_tier!r}'
        super().__init__(message)


class UnknownResourceTierError(ResourceTierResolutionError):
    """Raised when a caller passes a tier outside the public vocabulary."""

    def __init__(self, policy_tier: str) -> None:
        """Build the unknown-tier error."""
        message = f'Unknown resource tier: {policy_tier!r}'
        super().__init__(message)


class _ArtifactBodyError(ValueError):
    """Raised when a derived artifact has zero or multiple bodies."""

    def __init__(self) -> None:
        """Build the artifact body source error."""
        message = 'exactly one of storage_ref or inline_text must be set'
        super().__init__(message)


class VersionStamps(BaseModel):
    """Extractor, OCR, model, redaction, and policy versions for artifacts."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    extractor_version: StrictStr | None = Field(
        ...,
        min_length=1,
        description='Extractor implementation version used for derived artifacts.',
    )
    ocr_version: StrictStr | None = Field(
        ...,
        min_length=1,
        description='OCR implementation version used for derived artifacts.',
    )
    model_version: StrictStr | None = Field(
        ...,
        min_length=1,
        description='Model version used for layout, OCR repair, or redaction assistance.',
    )
    redaction_version: StrictStr | None = Field(
        ...,
        min_length=1,
        description='Redaction policy or detector implementation version.',
    )
    policy_version: StrictStr | None = Field(
        ...,
        min_length=1,
        description='Resource policy resolver version.',
    )


class ResourcePolicy(BaseModel):
    """Intent-level resource processing policy."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    resource: Attachment | StrictStr = Field(
        ...,
        description='Attachment entity or registered resource_id to process.',
    )
    tier: ResourceTier | None = Field(
        ...,
        description='Requested tier, or null to derive from the carrying message.',
    )
    persist: StrictBool | None = Field(
        ...,
        description='Durability intent, or null for the smart default.',
    )


class ProcessingState(BaseModel):
    """Resource processing lifecycle record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    resource_id: StrictStr = Field(..., min_length=1, description='Registered resource id.')
    tier: ResourceTier = Field(..., description='Resolved resource processing tier.')
    status: ProcessingStatus = Field(..., description='Processing lifecycle status.')
    processed_at: StrictStr | None = Field(
        ...,
        description='RFC3339 processing timestamp, or null before processing evidence exists.',
    )
    attempt: NonNegativeStrictInt = Field(..., description='Zero-based processing attempt count.')
    error: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description='Optional non-sensitive error summary.',
    )
    version_stamps: VersionStamps = Field(..., description='Artifact lineage version stamps.')


class ArtifactStorageRef(BaseModel):
    """Storage bucket/path pointer for a derived artifact body."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    bucket: StrictStr = Field(
        ...,
        min_length=1,
        description='Storage bucket, grounded in v1 storage_bucket.',
    )
    path: StrictStr = Field(
        ...,
        min_length=1,
        description='Storage object path, grounded in v1 storage_path.',
    )


class DerivedArtifact(BaseModel):
    """Produced artifact record for resource-processing outputs."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    artifact_id: StrictStr = Field(..., min_length=1, description='Stable artifact id.')
    resource_id: StrictStr = Field(..., min_length=1, description='Registered resource id.')
    kind: ArtifactKind = Field(..., description='Produced artifact kind.')
    storage_ref: ArtifactStorageRef | None = Field(
        default=None,
        description='Storage reference for large artifact bodies.',
    )
    inline_text: InlineArtifactText | None = Field(
        default=None,
        description='Bounded inline artifact body.',
    )
    content_hash: StrictStr = Field(
        ...,
        pattern=r'^[0-9a-f]{64}$',
        description='SHA-256 hex digest of the artifact body.',
    )
    conversion_method: StrictStr = Field(
        ...,
        min_length=1,
        description='Internal conversion method name.',
    )
    ocr_confidence: OcrConfidence | None = Field(
        default=None,
        description='Optional OCR confidence score from 0 through 1.',
    )
    version: PositiveStrictInt = Field(..., description='Positive artifact version number.')
    supersedes_artifact_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional prior artifact replaced by this version.',
    )
    version_stamps: VersionStamps = Field(..., description='Artifact lineage version stamps.')
    created_at: StrictStr = Field(..., description='RFC3339 creation timestamp.')

    @model_validator(mode='after')
    def _validate_exactly_one_body(self) -> DerivedArtifact:
        has_storage_ref = self.storage_ref is not None
        has_inline_text = self.inline_text is not None
        if has_storage_ref == has_inline_text:
            raise _ArtifactBodyError
        return self


def resolve_tier(
    message_has_redaction: bool,  # noqa: FBT001
    policy_tier: str | None,
) -> ResourceTier:
    """Resolve the resource tier at the message boundary."""
    if policy_tier is not None and policy_tier not in _RESOURCE_TIERS:
        raise UnknownResourceTierError(policy_tier)

    if message_has_redaction:
        if policy_tier in {'direct', 'indexed'}:
            raise ResourceTierDowngradeError(policy_tier)
        return 'secure'

    if policy_tier is None:
        return 'direct'

    return cast('ResourceTier', policy_tier)


def _attachment_types_namespace() -> dict[str, object]:
    messages_module = import_module('maivn_contracts.messages')
    return {'Attachment': cast('object', messages_module.Attachment)}


ResourcePolicy.model_rebuild(_types_namespace=_attachment_types_namespace())
