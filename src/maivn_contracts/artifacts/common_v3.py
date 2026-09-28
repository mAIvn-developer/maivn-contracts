"""Shared closed primitives for rich ordinary artifact plans."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias
from urllib.parse import urlsplit

from pydantic import (
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

from maivn_contracts.artifacts.plan_inputs import (
    ResourceBounds,  # noqa: TC001 - Pydantic runtime type
    RetentionRequest,  # noqa: TC001 - Pydantic runtime type
)
from maivn_contracts.artifacts.primitives import (
    ArtifactCustody,  # noqa: TC001 - Pydantic runtime type
    JcsPositiveStrictInt,  # noqa: TC001 - Pydantic runtime type
    MimeType,  # noqa: TC001 - Pydantic runtime type
    OpaqueTokenId,  # noqa: TC001 - Pydantic runtime type
    ValidationProfile,  # noqa: TC001 - Pydantic runtime type
    ValidationVersion,  # noqa: TC001 - Pydantic runtime type
)

_ASCII_CONTROL_LIMIT = 32
_ASCII_DELETE = 127

StructuralId: TypeAlias = Annotated[StrictStr, Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')]
HexColor: TypeAlias = Annotated[StrictStr, Field(pattern=r'^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$')]
PositivePoints: TypeAlias = Annotated[StrictFloat, Field(gt=0.0, le=20_000.0)]
NonNegativePoints: TypeAlias = Annotated[StrictFloat, Field(ge=0.0, le=20_000.0)]
NormalizedFraction: TypeAlias = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
FiniteNumber: TypeAlias = Annotated[StrictFloat | StrictInt, Field(ge=-1e15, le=1e15)]


class RichArtifactModel(BaseModel):
    """Frozen model-generated structure with no extension fields."""

    model_config = ConfigDict(extra='forbid', frozen=True)


class RichArtifactInvariantError(ValueError):
    """Value-free rich-plan invariant failure."""


class Insets(RichArtifactModel):
    """Four bounded inset measurements in points."""

    top: NonNegativePoints
    right: NonNegativePoints
    bottom: NonNegativePoints
    left: NonNegativePoints


class FontSpec(RichArtifactModel):
    """Portable typography resolved against runtime-owned fonts."""

    family: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    size_points: Annotated[StrictFloat, Field(ge=4.0, le=288.0)]
    weight: Literal[300, 400, 500, 600, 700, 800]
    italic: StrictBool
    color: HexColor


class InternalLinkTarget(RichArtifactModel):
    """Link to a declared bookmark, slide, sheet, or named range."""

    kind: Literal['internal'] = 'internal'
    bookmark_id: StructuralId


class HttpsLinkTarget(RichArtifactModel):
    """External link restricted to an absolute HTTPS URI."""

    kind: Literal['https'] = 'https'
    uri: Annotated[StrictStr, Field(min_length=9, max_length=2048)]

    @field_validator('uri')
    @classmethod
    def _require_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise RichArtifactInvariantError
        if any(
            ord(character) < _ASCII_CONTROL_LIMIT or ord(character) == _ASCII_DELETE
            for character in value
        ):
            raise RichArtifactInvariantError
        return value


LinkTarget: TypeAlias = Annotated[InternalLinkTarget | HttpsLinkTarget, Field(discriminator='kind')]


class TextRun(RichArtifactModel):
    """One bounded span of rich ordinary text."""

    text: Annotated[StrictStr, Field(min_length=1, max_length=16_384)]
    font: FontSpec | None = None
    bold: StrictBool | None = None
    italic: StrictBool | None = None
    underline: StrictBool = False
    strike: StrictBool = False
    link: LinkTarget | None = None
    language: (
        Annotated[StrictStr, Field(pattern=r'^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$')] | None
    ) = None


class Paragraph(RichArtifactModel):
    """One styled paragraph with bounded runs and list semantics."""

    paragraph_id: StructuralId
    runs: tuple[TextRun, ...] = Field(min_length=1, max_length=128)
    style_id: StructuralId | None = None
    alignment: Literal['left', 'center', 'right', 'justify']
    space_before_points: NonNegativePoints = 0.0
    space_after_points: NonNegativePoints = 0.0
    line_spacing: Annotated[StrictFloat, Field(ge=0.8, le=4.0)] = 1.0
    keep_with_next: StrictBool = False
    page_break_before: StrictBool = False
    list_id: StructuralId | None = None
    list_level: Annotated[StrictInt, Field(ge=0, le=8)] | None = None

    @model_validator(mode='after')
    def _validate_list_fields(self) -> Paragraph:
        if (self.list_id is None) != (self.list_level is None):
            raise RichArtifactInvariantError
        return self


class RichText(RichArtifactModel):
    """Bounded paragraphs used by document, slide, shape, and cell content."""

    paragraphs: tuple[Paragraph, ...] = Field(min_length=1, max_length=5_000)


class ArtifactInputRefV3(RichArtifactModel):
    """Exact immutable ordinary artifact input selected before rendering."""

    local_id: StructuralId
    artifact_id: OpaqueTokenId
    revision: JcsPositiveStrictInt
    generation: JcsPositiveStrictInt
    sha256: Annotated[StrictStr, Field(pattern=r'^[0-9a-f]{64}$')]
    expected_mime_type: MimeType
    purpose: Literal['image', 'edit_source', 'edit_mask', 'template', 'data']


class ImagePlacement(RichArtifactModel):
    """Placement and accessibility for one verified raster input."""

    input_local_id: StructuralId
    width_points: PositivePoints
    height_points: PositivePoints
    crop_left: NormalizedFraction
    crop_top: NormalizedFraction
    crop_right: NormalizedFraction
    crop_bottom: NormalizedFraction
    rotation_degrees: Annotated[StrictFloat, Field(ge=-360.0, le=360.0)]
    opacity: NormalizedFraction
    alt_text: Annotated[StrictStr, Field(min_length=1, max_length=2_048)]
    caption: RichText | None = None

    @model_validator(mode='after')
    def _validate_crop(self) -> ImagePlacement:
        if self.crop_left + self.crop_right >= 1.0 or self.crop_top + self.crop_bottom >= 1.0:
            raise RichArtifactInvariantError
        return self


class ChartSeries(RichArtifactModel):
    """One labeled finite chart series."""

    name: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    values: tuple[FiniteNumber, ...] = Field(min_length=1, max_length=5_000)
    color: HexColor


class ChartSpec(RichArtifactModel):
    """Portable editable chart data and presentation controls."""

    chart_id: StructuralId
    chart_type: Literal['bar', 'column', 'line', 'area', 'pie', 'doughnut', 'scatter']
    title: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    categories: tuple[Annotated[StrictStr, Field(max_length=256)], ...] = Field(
        min_length=1, max_length=5_000
    )
    series: tuple[ChartSeries, ...] = Field(min_length=1, max_length=32)
    show_legend: StrictBool
    show_data_labels: StrictBool
    alt_text: Annotated[StrictStr, Field(min_length=1, max_length=2_048)]

    @model_validator(mode='after')
    def _validate_series_lengths(self) -> ChartSpec:
        if any(len(series.values) != len(self.categories) for series in self.series):
            raise RichArtifactInvariantError
        return self


class AccessibilityMetadata(RichArtifactModel):
    """Document-level metadata needed by native accessibility surfaces."""

    title: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    description: Annotated[StrictStr, Field(min_length=1, max_length=2_048)]
    language: Annotated[StrictStr, Field(pattern=r'^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$')]


class ArtifactPlanMetadataV3(RichArtifactModel):
    """Shared plan envelope inherited by every deterministic V3 plan."""

    schema_version: Literal['v3']
    logical_output_name: StructuralId
    custody_request: ArtifactCustody
    input_refs: tuple[ArtifactInputRefV3, ...] = Field(max_length=32)
    renderer_profile: OpaqueTokenId
    renderer_min_version: ValidationVersion
    validation_profile: ValidationProfile
    disposition: Literal['intermediate', 'candidate', 'final']
    retention_request: RetentionRequest
    resource_bounds: ResourceBounds

    @model_validator(mode='after')
    def _validate_input_uniqueness(self) -> ArtifactPlanMetadataV3:
        local_ids = tuple(item.local_id for item in self.input_refs)
        identities = tuple(
            (item.artifact_id, item.revision, item.generation, item.sha256)
            for item in self.input_refs
        )
        if len(local_ids) != len(set(local_ids)) or len(identities) != len(set(identities)):
            raise RichArtifactInvariantError
        return self
