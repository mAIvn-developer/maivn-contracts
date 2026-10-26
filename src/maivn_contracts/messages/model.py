"""Hand-authored Pydantic models for owned Message contracts."""

from __future__ import annotations

import re
import string
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts import ArtifactRef  # noqa: TC001

MessageRole: TypeAlias = Literal['user', 'assistant', 'system', 'tool']
MetadataValue: TypeAlias = StrictStr | StrictInt | float | StrictBool | None

HIPAA_SAFE_HARBOR_CATEGORIES: frozenset[str] = frozenset(
    {
        'person',
        'ssn',
        'phone',
        'fax',
        'email',
        'credit_card',
        'iban',
        'swift',
        'account_id',
        'medical_record_number',
        'health_plan_id',
        'certificate_id',
        'license_id',
        'vehicle_id',
        'device_id',
        'biometric_id',
        'ip_address',
        'url',
        'date',
        'datetime',
    },
)
_MIN_WHITELIST_VALUE_LENGTH = 3
_MIN_WHITELIST_JUSTIFICATION_LENGTH = 8
# One-character strings a whitelist pattern must not match (patterns compile case-insensitively).
_PERMISSIVE_PATTERN_PROBES = ('', *string.ascii_lowercase, *string.digits, *string.punctuation)


class _AttachmentSourceError(ValueError):
    """Raised when an attachment has zero or multiple sources."""

    def __init__(self) -> None:
        """Build the attachment source error."""
        message = 'exactly one of storage_ref or inline_base64 must be set'
        super().__init__(message)


class _WhitelistEntryKindError(ValueError):
    """Raised when a whitelist entry has zero or multiple selector kinds."""

    def __init__(self) -> None:
        """Build the whitelist selector error."""
        message = 'PIIWhitelistEntry requires exactly one of entity_type, pattern, or value'
        super().__init__(message)


class _PhiModeSafeHarborError(ValueError):
    """Raised when phi_mode whitelists a HIPAA Safe Harbor category."""

    def __init__(self, categories: list[str]) -> None:
        """Build the phi_mode category error."""
        message = (
            'phi_mode=True forbids entity_type whitelist entries for HIPAA Safe Harbor '
            f'categories: {sorted(set(categories))}'
        )
        super().__init__(message)


class _DuplicateArtifactRefError(ValueError):
    """Raised when a Message selects the same immutable artifact revision twice."""

    def __init__(self) -> None:
        """Build the duplicate immutable artifact identity error."""
        super().__init__('artifact_refs must not repeat an artifact_id and revision pair')


class AttachmentStorageRef(BaseModel):
    """Object-storage pointer for attachment bytes."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    bucket: StrictStr = Field(
        ...,
        min_length=1,
        description='Object-storage bucket containing the attachment bytes.',
    )
    path: StrictStr = Field(
        ...,
        min_length=1,
        description='Object-storage path for the attachment bytes.',
    )
    sha256: StrictStr = Field(
        ...,
        pattern=r'^[0-9a-f]{64}$',
        description='SHA-256 hex digest pinned on the storage object reference.',
    )


class Attachment(BaseModel):
    """Real attachment entity used by owned Message records."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    attachment_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable attachment identifier within the owning message or resource record.',
    )
    filename: StrictStr = Field(
        ...,
        min_length=1,
        max_length=255,
        description='Sanitized display filename for the attachment.',
    )
    mime_type: StrictStr = Field(
        ...,
        min_length=1,
        description='IANA media type used for provider content-block routing.',
    )
    size_bytes: StrictInt = Field(
        ...,
        ge=0,
        description='Attachment payload size in bytes before base64 encoding.',
    )
    storage_ref: AttachmentStorageRef | None = Field(
        default=None,
        description='Object-storage source for attachment bytes.',
    )
    inline_base64: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=69905068,
        pattern=r'^[A-Za-z0-9+/]*={0,2}$',
        description='Bounded base64 payload for small inline attachments.',
    )
    content_hash: StrictStr = Field(
        ...,
        pattern=r'^[0-9a-f]{64}$',
        description='SHA-256 hex digest of the attachment bytes.',
    )
    resource_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional back-reference to the registered resource row.',
    )

    @model_validator(mode='after')
    def _validate_exactly_one_source(self) -> Attachment:
        has_storage_ref = self.storage_ref is not None
        has_inline_base64 = self.inline_base64 is not None
        if has_storage_ref == has_inline_base64:
            raise _AttachmentSourceError
        return self


class TextContentBlock(BaseModel):
    """Plain text content block."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    type: Literal['text'] = Field(..., description='Content block discriminator.')
    text: StrictStr = Field(..., min_length=1, description='Plain text content block.')


class ImageContentBlock(BaseModel):
    """Image content block backed by an Attachment entity."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    type: Literal['image'] = Field(..., description='Content block discriminator.')
    attachment_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Attachment entity that carries the image bytes.',
    )
    mime_type: StrictStr = Field(
        ...,
        pattern=r'^image/',
        description='Image media type routed to provider image blocks.',
    )
    alt_text: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional human-readable image label.',
    )


class DocumentContentBlock(BaseModel):
    """PDF document content block backed by an Attachment entity."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    type: Literal['document'] = Field(..., description='Content block discriminator.')
    attachment_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Attachment entity that carries the document bytes.',
    )
    mime_type: Literal['application/pdf'] = Field(
        ...,
        description='PDF document media type routed to provider document blocks.',
    )
    title: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional document label.',
    )


class VideoContentBlock(BaseModel):
    """Native video bytes referenced through an Attachment entity."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    type: Literal['video'] = Field(..., description='Content block discriminator.')
    attachment_id: StrictStr = Field(..., min_length=1)
    mime_type: StrictStr = Field(..., pattern=r'^video/')
    title: StrictStr | None = Field(default=None, min_length=1)


ContentBlock: TypeAlias = Annotated[
    TextContentBlock | ImageContentBlock | DocumentContentBlock | VideoContentBlock,
    Field(discriminator='type'),
]


class KnownPrivateData(BaseModel):
    """Structured known private value descriptor."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    value: StrictStr = Field(..., min_length=1, description='Concrete private value to redact.')
    name: StrictStr | None = Field(
        default=None,
        min_length=1,
        pattern=r'^[A-Za-z_][A-Za-z0-9_]*$',
        description='Optional custom placeholder key used in the {_{key}_} convention.',
    )
    pii_type: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='PII entity type such as person, phone, email, ssn, date, or account_id.',
    )
    label: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Human-readable label included in the private_data_schema.',
    )
    description: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Human-readable description for LLM context.',
    )
    format: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Semantic format hint such as email, phone, date, ssn, or us_phone.',
    )


class PIIWhitelistEntry(BaseModel):
    """A single PII whitelist rule."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    entity_type: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='PII entity type to allow. Mutually exclusive with pattern and value.',
    )
    pattern: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Regex-like pattern matched against detected spans.',
    )
    value: StrictStr | None = Field(
        default=None,
        min_length=_MIN_WHITELIST_VALUE_LENGTH,
        description='Literal value to allow.',
    )
    justification: StrictStr = Field(
        ...,
        min_length=_MIN_WHITELIST_JUSTIFICATION_LENGTH,
        max_length=512,
        description='Human-readable business justification for audit evidence.',
    )
    label: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description='Optional audit label.',
    )

    @model_validator(mode='after')
    def _validate_exactly_one_kind(self) -> PIIWhitelistEntry:
        provided = sum(value is not None for value in (self.entity_type, self.pattern, self.value))
        if provided != 1:
            raise _WhitelistEntryKindError
        return self

    @field_validator('entity_type')
    @classmethod
    def _normalize_entity_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            message = 'entity_type cannot be blank'
            raise ValueError(message)
        return normalized

    @field_validator('pattern')
    @classmethod
    def _validate_pattern(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            message = 'pattern cannot be blank'
            raise ValueError(message)
        try:
            compiled = re.compile(value, re.IGNORECASE)
        except re.error as exc:
            message = f'invalid regex pattern: {exc}'
            raise ValueError(message) from exc
        if any(compiled.match(probe) is not None for probe in _PERMISSIVE_PATTERN_PROBES):
            message = (
                'pattern is too permissive (matches empty or single-character strings); '
                'narrow the pattern or use entity_type'
            )
            raise ValueError(message)
        return value

    @field_validator('value')
    @classmethod
    def _validate_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        if len(candidate) < _MIN_WHITELIST_VALUE_LENGTH:
            message = (
                f'value must be at least {_MIN_WHITELIST_VALUE_LENGTH} characters after stripping'
            )
            raise ValueError(message)
        return candidate

    @field_validator('justification')
    @classmethod
    def _validate_justification(cls, value: str) -> str:
        candidate = value.strip()
        if len(candidate) < _MIN_WHITELIST_JUSTIFICATION_LENGTH:
            message = (
                'justification must be at least '
                f'{_MIN_WHITELIST_JUSTIFICATION_LENGTH} characters after stripping'
            )
            raise ValueError(message)
        return candidate


class PIIWhitelist(BaseModel):
    """PII whitelist entries plus compliance flags for redaction."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    entries: list[PIIWhitelistEntry] | None = Field(
        default=None,
        max_length=256,
        description='Whitelist entries evaluated after detection and before redaction.',
    )
    phi_mode: StrictBool | None = Field(
        default=None,
        description='When true, HIPAA Safe Harbor entity-type categories cannot be whitelisted.',
    )

    @model_validator(mode='after')
    def _enforce_phi_mode(self) -> PIIWhitelist:
        if self.phi_mode is not True or self.entries is None:
            return self
        bad = [
            entry.entity_type
            for entry in self.entries
            if (entry.entity_type is not None and entry.entity_type in HIPAA_SAFE_HARBOR_CATEGORIES)
        ]
        if bad:
            raise _PhiModeSafeHarborError(bad)
        return self


class RedactionConfig(BaseModel):
    """Redacted-message boundary config carried on a Message."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    pii_whitelist: PIIWhitelist | None = Field(
        default=None,
        description='PII whitelist including phi_mode and audit justifications.',
    )
    known_pii_values: list[StrictStr | KnownPrivateData] | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description='Known private values seeded into redaction.',
    )
    private_data_schema: list[StrictStr] | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description='Reserved private-data field names represented as {_{key}_} placeholders.',
    )


class Message(BaseModel):
    """Owned Message wire record."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    message_id: StrictStr = Field(
        ...,
        min_length=1,
        description='Stable message identifier for id-based channel merge and replay.',
    )
    role: MessageRole = Field(..., description='Message role discriminator.')
    content: StrictStr | list[ContentBlock] = Field(
        ...,
        description='Message text or provider-grounded content blocks.',
    )
    attachments: list[Attachment] | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description='Attachment entities riding on this message.',
    )
    artifact_refs: tuple[ArtifactRef, ...] | None = Field(
        default=None,
        max_length=32,
        description=(
            'Optional ordered canonical immutable artifact references selected for this message.'
        ),
    )
    redaction: RedactionConfig | None = Field(
        default=None,
        description='Optional redacted-message boundary config.',
    )
    metadata: dict[str, MetadataValue] | None = Field(
        default=None,
        max_length=32,
        description='Bounded primitive metadata for tool call identifiers or trace hints.',
    )
    ts: StrictStr = Field(
        ...,
        description='RFC3339 timestamp for when the message was authored or emitted.',
    )

    @model_validator(mode='after')
    def _reject_duplicate_artifact_refs(self) -> Message:
        if self.artifact_refs is None:
            return self
        identities = {(ref.artifact_id, ref.revision) for ref in self.artifact_refs}
        if len(identities) != len(self.artifact_refs):
            raise _DuplicateArtifactRefError
        return self
