"""Closed rich document and PDF artifact plan."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from maivn_contracts.artifacts.common_v3 import (
    AccessibilityMetadata,
    ArtifactPlanMetadataV3,
    ChartSpec,
    FontSpec,
    HexColor,
    ImagePlacement,
    Insets,
    NonNegativePoints,
    PositivePoints,
    RichArtifactInvariantError,
    RichArtifactModel,
    RichText,
    StructuralId,
)


class DocumentThemeV3(RichArtifactModel):
    """Portable report color and font theme."""

    primary: HexColor
    secondary: HexColor
    accent: HexColor
    background: HexColor
    heading_font: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    body_font: Annotated[StrictStr, Field(min_length=1, max_length=128)]


class DocumentPageV3(RichArtifactModel):
    """Bounded page geometry."""

    width_points: PositivePoints
    height_points: PositivePoints
    margins: Insets
    orientation: Literal['portrait', 'landscape']
    columns: Annotated[StrictInt, Field(ge=1, le=4)]

    @model_validator(mode='after')
    def _validate_printable_area(self) -> DocumentPageV3:
        if (
            self.margins.left + self.margins.right >= self.width_points
            or self.margins.top + self.margins.bottom >= self.height_points
        ):
            raise RichArtifactInvariantError
        return self


class DocumentStyleV3(RichArtifactModel):
    """Named paragraph style."""

    style_id: StructuralId
    font: FontSpec
    based_on: StructuralId | None = None
    alignment: Literal['left', 'center', 'right', 'justify']
    space_before_points: NonNegativePoints
    space_after_points: NonNegativePoints
    line_spacing: Annotated[StrictFloat, Field(ge=0.8, le=4.0)]


class DocumentRegionV3(RichArtifactModel):
    """Header or footer region."""

    slot: Literal['default', 'first', 'even']
    content: RichText
    page_number: StrictBool = False
    total_pages: StrictBool = False


class DocumentNoteV3(RichArtifactModel):
    """Footnote or endnote content."""

    note_id: StructuralId
    kind: Literal['footnote', 'endnote']
    content: RichText


class DocumentTextBlockV3(RichArtifactModel):
    """Flowing body text."""

    block_type: Literal['text']
    block_id: StructuralId
    content: RichText
    bookmark_id: StructuralId | None = None


class DocumentHeadingBlockV3(RichArtifactModel):
    """Outline heading and optional bookmark."""

    block_type: Literal['heading']
    block_id: StructuralId
    level: Annotated[StrictInt, Field(ge=1, le=9)]
    content: RichText
    bookmark_id: StructuralId | None = None


class DocumentTocBlockV3(RichArtifactModel):
    """Generated table of contents field."""

    block_type: Literal['toc']
    block_id: StructuralId
    title: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    min_level: Annotated[StrictInt, Field(ge=1, le=9)]
    max_level: Annotated[StrictInt, Field(ge=1, le=9)]

    @model_validator(mode='after')
    def _validate_levels(self) -> DocumentTocBlockV3:
        if self.min_level > self.max_level:
            raise RichArtifactInvariantError
        return self


class DocumentTableCellV3(RichArtifactModel):
    """Merged, styled table cell."""

    cell_id: StructuralId
    content: RichText
    column_span: Annotated[StrictInt, Field(ge=1, le=100)]
    row_span: Annotated[StrictInt, Field(ge=1, le=10_000)]
    fill: HexColor | None = None
    vertical_alignment: Literal['top', 'center', 'bottom'] = 'top'


class DocumentTableRowV3(RichArtifactModel):
    """Table row with header semantics."""

    row_id: StructuralId
    header: StrictBool
    repeat_header: StrictBool
    cells: tuple[DocumentTableCellV3, ...] = Field(min_length=1, max_length=100)


class DocumentTableBlockV3(RichArtifactModel):
    """Rich accessible table."""

    block_type: Literal['table']
    block_id: StructuralId
    column_count: Annotated[StrictInt, Field(ge=1, le=100)]
    rows: tuple[DocumentTableRowV3, ...] = Field(min_length=1, max_length=10_000)
    banded_rows: StrictBool
    header_rows: Annotated[StrictInt, Field(ge=0, le=100)]

    @model_validator(mode='after')
    def _validate_table(self) -> DocumentTableBlockV3:
        if self.header_rows > len(self.rows):
            raise RichArtifactInvariantError
        if any(
            sum(cell.column_span for cell in row.cells) != self.column_count for row in self.rows
        ):
            raise RichArtifactInvariantError
        return self


class DocumentImageBlockV3(RichArtifactModel):
    """Verified image and caption block."""

    block_type: Literal['image']
    block_id: StructuralId
    image: ImagePlacement
    alignment: Literal['left', 'center', 'right']


class DocumentChartBlockV3(RichArtifactModel):
    """Editable chart block."""

    block_type: Literal['chart']
    block_id: StructuralId
    chart: ChartSpec
    width_points: PositivePoints
    height_points: PositivePoints


class DiagramNodeV3(RichArtifactModel):
    """One labeled diagram node."""

    node_id: StructuralId
    label: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    fill: HexColor


class DiagramEdgeV3(RichArtifactModel):
    """One directed diagram edge."""

    source_id: StructuralId
    target_id: StructuralId
    label: Annotated[StrictStr, Field(max_length=256)] | None = None


class DocumentDiagramBlockV3(RichArtifactModel):
    """Portable process or relationship diagram."""

    block_type: Literal['diagram']
    block_id: StructuralId
    layout: Literal['horizontal', 'vertical', 'cycle', 'timeline']
    nodes: tuple[DiagramNodeV3, ...] = Field(min_length=2, max_length=64)
    edges: tuple[DiagramEdgeV3, ...] = Field(max_length=128)
    alt_text: Annotated[StrictStr, Field(min_length=1, max_length=2_048)]


class DocumentPageBreakV3(RichArtifactModel):
    """Explicit page break."""

    block_type: Literal['page_break']
    block_id: StructuralId


DocumentBlockV3: TypeAlias = Annotated[
    DocumentTextBlockV3
    | DocumentHeadingBlockV3
    | DocumentTocBlockV3
    | DocumentTableBlockV3
    | DocumentImageBlockV3
    | DocumentChartBlockV3
    | DocumentDiagramBlockV3
    | DocumentPageBreakV3,
    Field(discriminator='block_type'),
]


class DocumentSectionV3(RichArtifactModel):
    """Section boundary with optional geometry override."""

    section_id: StructuralId
    start_block_id: StructuralId
    page: DocumentPageV3 | None = None


class DocumentPdfOptionsV3(RichArtifactModel):
    """Fail-closed accessible PDF controls."""

    tagged: Literal[True]
    pdfa: Literal['none', '2b', '3b']
    allow_actions: Literal[False]
    include_bookmarks: StrictBool


class DocumentBodyV3(RichArtifactModel):
    """Complete rich document body."""

    theme: DocumentThemeV3
    page: DocumentPageV3
    styles: tuple[DocumentStyleV3, ...] = Field(min_length=1, max_length=256)
    headers: tuple[DocumentRegionV3, ...] = Field(max_length=16)
    footers: tuple[DocumentRegionV3, ...] = Field(max_length=16)
    notes: tuple[DocumentNoteV3, ...] = Field(max_length=1_000)
    blocks: tuple[DocumentBlockV3, ...] = Field(min_length=1, max_length=10_000)
    sections: tuple[DocumentSectionV3, ...] = Field(default=(), max_length=64)
    accessibility: AccessibilityMetadata
    pdf: DocumentPdfOptionsV3 | None = None


class DocumentArtifactPlanV3(ArtifactPlanMetadataV3):
    """Closed rich ordinary DOCX or PDF plan."""

    kind: Literal['document']
    output_mime_type: Literal[
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/pdf',
    ]
    body: DocumentBodyV3

    @model_validator(mode='after')
    def _validate_document_output(self) -> DocumentArtifactPlanV3:
        is_pdf = self.output_mime_type == 'application/pdf'
        if is_pdf != (self.body.pdf is not None):
            raise RichArtifactInvariantError
        if self.resource_bounds.max_pages is None:
            raise RichArtifactInvariantError
        return self
