"""Shared scalar projections and closed-model scaffolding for artifact contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
)
from pydantic import ValidationError as PydanticValidationError

__all__ = [
    'ASCII_CONTROL_LIMIT',
    'ASCII_DELETE',
    'CROP_PER_MILLE_SCALE',
    'MAX_DOCUMENT_BLOCKS',
    'MAX_DOCUMENT_FRAGMENTS',
    'MAX_DOCUMENT_REDACTED_UTF8_BYTES',
    'MAX_DOCUMENT_RUNS',
    'MAX_DOCUMENT_STRUCTURAL_IDS',
    'MAX_FORMULA_DEPTH',
    'MAX_FORMULA_NODES',
    'MAX_IMAGE_PIXELS',
    'MAX_TOTAL_DECODED_PIXELS',
    'MAX_VERIFIED_EXPORT_BYTES',
    'MAX_WORKBOOK_CELLS',
    'MAX_WORKBOOK_SHEETS',
    'MIME_TYPES_BY_KIND',
    'PRIVATE_DELETION_STATES',
    'PRIVATE_LABEL_BY_KIND',
    'VAULT_EFFECT_STATUS_BINDING_ERROR',
    'VERIFIED_EXPORT_IDENTITY_BY_MIME',
    '_JCS_SAFE_INTEGER_MAX',
    '_JCS_SAFE_INTEGER_MIN',
    '_OPAQUE_TOKEN_PATTERN',
    '_RFC3339_PATTERN',
    'ArtifactCustody',
    'ArtifactKind',
    'ArtifactRefInvariantError',
    'ClosedModel',
    'ImageAxisPixels',
    'JcsPositiveStrictInt',
    'JcsSafeNumber',
    'MimeType',
    'OpaqueTokenId',
    'OrdinaryArtifactState',
    'PositiveStrictInt',
    'PrivateArtifactState',
    'PrivateDisplayLabel',
    'ProducerClass',
    'Rfc3339Timestamp',
    'Sha256Hex',
    'ValidationProfile',
    'ValidationVersion',
    '_validate_rfc3339_timestamp',
    'is_mime_type_valid_for_artifact_kind',
    'value_free_model_input',
]

_OPAQUE_TOKEN_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'  # noqa: S105
_RFC3339_PATTERN = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$',
)
MIME_TYPES_BY_KIND: dict[str, frozenset[str]] = {
    'document': frozenset(
        {
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
    ),
    'spreadsheet': frozenset(
        {'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
    ),
    'presentation': frozenset(
        {'application/vnd.openxmlformats-officedocument.presentationml.presentation'},
    ),
    'image': frozenset({'image/jpeg', 'image/png'}),
    'audio': frozenset({'audio/mpeg', 'audio/wav'}),
    'other': frozenset({'application/octet-stream'}),
}
PRIVATE_LABEL_BY_KIND: dict[str, str] = {
    'document': 'Private document',
    'spreadsheet': 'Private spreadsheet',
    'presentation': 'Private presentation',
    'image': 'Private image',
    'audio': 'Private audio',
    'other': 'Private artifact',
}
PRIVATE_DELETION_STATES = frozenset(
    {'deleting', 'deletion_pending_backup_expiry', 'deleted', 'delete_incomplete'},
)
ASCII_CONTROL_LIMIT = 32
ASCII_DELETE = 127
MAX_DOCUMENT_REDACTED_UTF8_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_BLOCKS = 10_000
MAX_DOCUMENT_RUNS = 10_000
MAX_DOCUMENT_FRAGMENTS = 20_000
MAX_DOCUMENT_STRUCTURAL_IDS = 50_000
MAX_IMAGE_PIXELS = 40_000_000
MAX_TOTAL_DECODED_PIXELS = 160_000_000
MAX_WORKBOOK_CELLS = 1_000_000
MAX_WORKBOOK_SHEETS = 100
MAX_FORMULA_DEPTH = 32
MAX_FORMULA_NODES = 256
CROP_PER_MILLE_SCALE = 1000
_JCS_SAFE_INTEGER_MAX = (2**53) - 1
_JCS_SAFE_INTEGER_MIN = -_JCS_SAFE_INTEGER_MAX
VAULT_EFFECT_STATUS_BINDING_ERROR = 'vault effect/status identity binding mismatch'
MAX_VERIFIED_EXPORT_BYTES = 52_428_800
VERIFIED_EXPORT_IDENTITY_BY_MIME: dict[str, tuple[str, str]] = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': (
        'document',
        '.docx',
    ),
    'application/pdf': ('document', '.pdf'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': (
        'spreadsheet',
        '.xlsx',
    ),
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': (
        'presentation',
        '.pptx',
    ),
    'image/png': ('image', '.png'),
    'image/jpeg': ('image', '.jpeg'),
}


class ArtifactRefInvariantError(ValueError):
    """Value-free artifact reference invariant failure."""


def _validate_rfc3339_timestamp(value: str) -> str:
    try:
        datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError as error:
        raise ArtifactRefInvariantError from error
    if _RFC3339_PATTERN.fullmatch(value) is None:
        raise ArtifactRefInvariantError
    return value


OpaqueTokenId: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=_OPAQUE_TOKEN_PATTERN),
]
Sha256Hex: TypeAlias = Annotated[StrictStr, Field(pattern=r'^[0-9a-f]{64}$')]
Rfc3339Timestamp: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=_RFC3339_PATTERN.pattern),
    AfterValidator(_validate_rfc3339_timestamp),
]
PositiveStrictInt: TypeAlias = Annotated[StrictInt, Field(ge=1)]
JcsPositiveStrictInt: TypeAlias = Annotated[
    StrictInt,
    Field(ge=1, le=_JCS_SAFE_INTEGER_MAX),
]
JcsSafeNumber: TypeAlias = Annotated[
    StrictInt | StrictFloat,
    Field(ge=_JCS_SAFE_INTEGER_MIN, le=_JCS_SAFE_INTEGER_MAX),
]
ImageAxisPixels: TypeAlias = Annotated[StrictInt, Field(ge=1, le=40_000_000)]
ArtifactKind: TypeAlias = Literal[
    'document', 'spreadsheet', 'presentation', 'image', 'audio', 'other'
]
ArtifactCustody: TypeAlias = Literal['ordinary', 'vault_private']
OrdinaryArtifactState: TypeAlias = Literal[
    'available',
    'expired',
    'deleting',
    'deleted',
    'delete_incomplete',
]
PrivateArtifactState: TypeAlias = Literal[
    'available_in_vault',
    'expired',
    'deleting',
    'deletion_pending_backup_expiry',
    'deleted',
    'delete_incomplete',
]
ProducerClass: TypeAlias = Literal[
    'hosted_tool',
    'external_tool',
    'provider',
    'delegated_agent',
    'swarm_member',
    'rework',
    'vault',
]
MimeType: TypeAlias = Literal[
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'image/png',
    'image/jpeg',
    'audio/mpeg',
    'audio/wav',
    'application/octet-stream',
]


def is_mime_type_valid_for_artifact_kind(
    kind: ArtifactKind,
    mime_type: MimeType,
) -> bool:
    """Return whether a canonical MIME value belongs to an artifact kind."""
    return mime_type in MIME_TYPES_BY_KIND[kind]


PrivateDisplayLabel: TypeAlias = Literal[
    'Private document',
    'Private spreadsheet',
    'Private presentation',
    'Private image',
    'Private audio',
    'Private artifact',
]
ValidationProfile: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'),
]
ValidationVersion: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
]


class ClosedModel(BaseModel):
    """Base for every artifact contract: unknown fields rejected, instances frozen."""

    model_config = ConfigDict(extra='forbid', frozen=True)


def value_free_model_input(value: object, envelope: type[BaseModel]) -> object:
    """Pass sensitive input onward only after the complete closed envelope is valid."""
    if not isinstance(value, dict):
        return dict[str, object]()
    try:
        envelope.model_validate(value)
    except PydanticValidationError:
        return dict[str, object]()
    return cast('dict[str, object]', value)
