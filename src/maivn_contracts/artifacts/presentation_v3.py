"""Closed static-rich presentation artifact plan."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from maivn_contracts.artifacts.common_v3 import (
    AccessibilityMetadata,
    ArtifactPlanMetadataV3,
    ChartSpec,
    HexColor,
    ImagePlacement,
    NonNegativePoints,
    PositivePoints,
    RichArtifactInvariantError,
    RichArtifactModel,
    RichText,
    StructuralId,
)
from maivn_contracts.artifacts.document_v3 import (
    DiagramEdgeV3,  # noqa: TC001 - Pydantic type
    DiagramNodeV3,  # noqa: TC001 - Pydantic type
)

_MAX_SLIDES = 500


class PresentationThemeV3(RichArtifactModel):
    """Portable presentation brand theme."""

    primary: HexColor
    secondary: HexColor
    accent: HexColor
    background: HexColor
    heading_font: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    body_font: Annotated[StrictStr, Field(min_length=1, max_length=128)]


class PresentationSlideSizeV3(RichArtifactModel):
    """Standard or custom slide dimensions."""

    preset: Literal['wide', 'standard', 'custom']
    width_points: PositivePoints | None
    height_points: PositivePoints | None

    @model_validator(mode='after')
    def _validate_custom_size(self) -> PresentationSlideSizeV3:
        has_custom_size = self.width_points is not None and self.height_points is not None
        if (self.preset == 'custom') != has_custom_size:
            raise RichArtifactInvariantError
        return self


class PresentationLayoutV3(RichArtifactModel):
    """Named slide layout."""

    layout_id: StructuralId
    name: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    background: HexColor


class PresentationSectionV3(RichArtifactModel):
    """Named deck section."""

    section_id: StructuralId
    title: Annotated[StrictStr, Field(min_length=1, max_length=256)]


class PresentationBoundsV3(RichArtifactModel):
    """Element geometry in points."""

    x: NonNegativePoints
    y: NonNegativePoints
    width: PositivePoints
    height: PositivePoints


class PresentationElementBaseV3(RichArtifactModel):
    """Shared static slide element fields."""

    element_id: StructuralId
    bounds: PresentationBoundsV3
    rotation_degrees: Annotated[StrictFloat, Field(ge=-360.0, le=360.0)]
    opacity: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    alt_text: Annotated[StrictStr, Field(min_length=1, max_length=2_048)]


class PresentationTextElementV3(PresentationElementBaseV3):
    """Editable rich text box."""

    element_type: Literal['text']
    content: RichText


class PresentationShapeElementV3(PresentationElementBaseV3):
    """Editable filled shape."""

    element_type: Literal['shape']
    shape: Literal['rectangle', 'rounded_rectangle', 'ellipse', 'triangle', 'chevron', 'hexagon']
    fill: HexColor
    line_color: HexColor
    line_width_points: NonNegativePoints
    content: RichText | None = None


class PresentationConnectorElementV3(PresentationElementBaseV3):
    """Editable connector line."""

    element_type: Literal['connector']
    connector: Literal['straight', 'elbow', 'curved']
    start_element_id: StructuralId | None = None
    end_element_id: StructuralId | None = None
    line_color: HexColor
    line_width_points: PositivePoints
    arrow_start: StrictBool
    arrow_end: StrictBool


class PresentationTableCellV3(RichArtifactModel):
    """Editable slide table cell."""

    content: RichText
    fill: HexColor | None = None
    column_span: Annotated[StrictInt, Field(ge=1, le=50)] = 1
    row_span: Annotated[StrictInt, Field(ge=1, le=500)] = 1


class PresentationTableRowV3(RichArtifactModel):
    """Editable slide table row."""

    cells: tuple[PresentationTableCellV3, ...] = Field(min_length=1, max_length=50)
    header: StrictBool


class PresentationTableElementV3(PresentationElementBaseV3):
    """Editable native slide table."""

    element_type: Literal['table']
    column_count: Annotated[StrictInt, Field(ge=1, le=50)]
    rows: tuple[PresentationTableRowV3, ...] = Field(min_length=1, max_length=500)
    banded_rows: StrictBool


class PresentationChartElementV3(PresentationElementBaseV3):
    """Editable native slide chart."""

    element_type: Literal['chart']
    chart: ChartSpec


class PresentationImageElementV3(PresentationElementBaseV3):
    """Verified raster on a slide."""

    element_type: Literal['image']
    image: ImagePlacement


class PresentationDiagramElementV3(PresentationElementBaseV3):
    """Editable node/edge diagram or timeline."""

    element_type: Literal['diagram']
    layout: Literal['horizontal', 'vertical', 'cycle', 'timeline']
    nodes: tuple[DiagramNodeV3, ...] = Field(min_length=2, max_length=64)
    edges: tuple[DiagramEdgeV3, ...] = Field(max_length=128)


PresentationElementV3: TypeAlias = Annotated[
    PresentationTextElementV3
    | PresentationShapeElementV3
    | PresentationConnectorElementV3
    | PresentationTableElementV3
    | PresentationChartElementV3
    | PresentationImageElementV3
    | PresentationDiagramElementV3,
    Field(discriminator='element_type'),
]


class PresentationSlideV3(RichArtifactModel):
    """One static-rich slide and its notes."""

    slide_id: StructuralId
    layout_id: StructuralId
    section_id: StructuralId | None
    title: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    hidden: StrictBool
    elements: tuple[PresentationElementV3, ...] = Field(max_length=500)
    speaker_notes: RichText | None
    show_slide_number: StrictBool
    footer: Annotated[StrictStr, Field(max_length=512)] | None
    transition: Literal['none']

    @model_validator(mode='after')
    def _validate_element_ids(self) -> PresentationSlideV3:
        element_ids = tuple(element.element_id for element in self.elements)
        if len(element_ids) != len(set(element_ids)):
            raise RichArtifactInvariantError
        return self


class PresentationBodyV3(RichArtifactModel):
    """Complete static-rich deck."""

    theme: PresentationThemeV3
    slide_size: PresentationSlideSizeV3
    layouts: tuple[PresentationLayoutV3, ...] = Field(min_length=1, max_length=64)
    sections: tuple[PresentationSectionV3, ...] = Field(max_length=64)
    slides: tuple[PresentationSlideV3, ...] = Field(min_length=1, max_length=500)
    accessibility: AccessibilityMetadata
    allow_animations: Literal[False]
    allow_embedded_media: Literal[False]
    allow_macros: Literal[False]
    allow_ole: Literal[False]

    @model_validator(mode='after')
    def _validate_references(self) -> PresentationBodyV3:
        layout_ids = {layout.layout_id for layout in self.layouts}
        section_ids = {section.section_id for section in self.sections}
        if any(slide.layout_id not in layout_ids for slide in self.slides):
            raise RichArtifactInvariantError
        if any(
            slide.section_id is not None and slide.section_id not in section_ids
            for slide in self.slides
        ):
            raise RichArtifactInvariantError
        return self


class PresentationArtifactPlanV3(ArtifactPlanMetadataV3):
    """Closed rich ordinary PPTX plan."""

    kind: Literal['presentation']
    output_mime_type: Literal[
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ]
    body: PresentationBodyV3

    @model_validator(mode='after')
    def _validate_presentation_bounds(self) -> PresentationArtifactPlanV3:
        if (
            self.resource_bounds.max_pages is None
            or self.resource_bounds.max_pages < len(self.body.slides)
            or self.resource_bounds.max_pages > _MAX_SLIDES
        ):
            raise RichArtifactInvariantError
        return self
