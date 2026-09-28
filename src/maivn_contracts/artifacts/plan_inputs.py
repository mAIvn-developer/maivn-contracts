"""Redacted payloads, plan input selections and declared resource bounds."""

from __future__ import annotations

import re
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import Field, StrictStr, field_validator

from maivn_contracts.artifacts.primitives import (
    ArtifactRefInvariantError,
    ClosedModel,
    JcsPositiveStrictInt,
    OpaqueTokenId,
    PositiveStrictInt,
)

__all__ = [
    'STRUCTURAL_ID_PATTERN',
    '_PRIVATE_PLACEHOLDER_PATTERN',
    'ArtifactPlanArtifactRef',
    'ArtifactPlanArtifactRefV2',
    'ArtifactPlanInputRef',
    'ArtifactPlanInputRefV2',
    'ArtifactPlanResourceRef',
    'ArtifactPlanResourceRefV2',
    'ArtifactPlanTemplateRef',
    'ArtifactPlanTemplateRefV2',
    'RedactedArtifactPayload',
    'RedactedTextFragment',
    'ResourceBounds',
    'RetentionRequest',
    'collect_placeholder_names',
    'input_ref_authority',
]

STRUCTURAL_ID_PATTERN = r'^[A-Za-z][A-Za-z0-9_-]{0,63}$'
_PRIVATE_PLACEHOLDER_PATTERN = re.compile(r'\{_\{[A-Za-z0-9][A-Za-z0-9_-]{0,127}\}_\}')


def collect_placeholder_names(value: object) -> frozenset[str]:
    """Return every private-placeholder name reachable anywhere inside a value."""
    if isinstance(value, str):
        return frozenset(match[3:-3] for match in _PRIVATE_PLACEHOLDER_PATTERN.findall(value))
    if isinstance(value, dict):
        mapping = cast('dict[object, object]', value)
        names: set[str] = set()
        for item in mapping.values():
            names.update(collect_placeholder_names(item))
        return frozenset(names)
    if isinstance(value, (list, tuple)):
        items = cast('list[object] | tuple[object, ...]', value)
        names = set()
        for item in items:
            names.update(collect_placeholder_names(item))
        return frozenset(names)
    return frozenset()


class RedactedTextFragment(ClosedModel):
    """One ordered, structurally-addressable redacted text fragment."""

    structural_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    text: Annotated[StrictStr, Field(min_length=1, max_length=16384)]

    @field_validator('text')
    @classmethod
    def _validate_placeholders(cls, value: str) -> str:
        remainder = _PRIVATE_PLACEHOLDER_PATTERN.sub('', value)
        if '{_{' in remainder or '}_}' in remainder:
            raise ArtifactRefInvariantError
        return value


class RedactedArtifactPayload(ClosedModel):
    """Dependency-free closed payload with structural private placeholders only."""

    fragments: tuple[RedactedTextFragment, ...] = Field(min_length=1, max_length=500)


class ArtifactPlanArtifactRef(ClosedModel):
    """Exact immutable artifact input selected for a plan."""

    ref_type: Literal['artifact']
    artifact_id: OpaqueTokenId
    revision: PositiveStrictInt


class ArtifactPlanResourceRef(ClosedModel):
    """Versioned project resource input selected for a plan."""

    ref_type: Literal['resource']
    resource_id: OpaqueTokenId
    revision: PositiveStrictInt


class ArtifactPlanTemplateRef(ClosedModel):
    """Versioned renderer template selected for a plan."""

    ref_type: Literal['template']
    template_id: OpaqueTokenId
    revision: PositiveStrictInt


ArtifactPlanInputRef: TypeAlias = Annotated[
    ArtifactPlanArtifactRef | ArtifactPlanResourceRef | ArtifactPlanTemplateRef,
    Field(discriminator='ref_type'),
]


class ArtifactPlanArtifactRefV2(ArtifactPlanArtifactRef):
    """Plan-local name for one exact immutable artifact input."""

    local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    revision: JcsPositiveStrictInt


class ArtifactPlanResourceRefV2(ArtifactPlanResourceRef):
    """Plan-local name for one exact immutable resource input."""

    local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    revision: JcsPositiveStrictInt


class ArtifactPlanTemplateRefV2(ArtifactPlanTemplateRef):
    """Plan-local name for one exact immutable template input."""

    local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    revision: JcsPositiveStrictInt


ArtifactPlanInputRefV2: TypeAlias = Annotated[
    ArtifactPlanArtifactRefV2 | ArtifactPlanResourceRefV2 | ArtifactPlanTemplateRefV2,
    Field(discriminator='ref_type'),
]


def input_ref_authority(item: ArtifactPlanInputRefV2) -> tuple[str, str, int]:
    """Return the (kind, id, revision) identity two plan inputs are compared on."""
    if isinstance(item, ArtifactPlanArtifactRefV2):
        return (item.ref_type, item.artifact_id, item.revision)
    if isinstance(item, ArtifactPlanResourceRefV2):
        return (item.ref_type, item.resource_id, item.revision)
    return (item.ref_type, item.template_id, item.revision)


class RetentionRequest(ClosedModel):
    """Non-authoritative retention request subject to policy evaluation."""

    retention_class: OpaqueTokenId


class ResourceBounds(ClosedModel):
    """Declared resource caps for renderer admission and service enforcement."""

    max_output_bytes: JcsPositiveStrictInt
    max_pages: JcsPositiveStrictInt | None = None
    max_sheets: JcsPositiveStrictInt | None = None
    max_cells: JcsPositiveStrictInt | None = None
    max_pixels: JcsPositiveStrictInt | None = None
    max_total_decoded_pixels: JcsPositiveStrictInt | None = None
    max_duration_seconds: JcsPositiveStrictInt | None = None
