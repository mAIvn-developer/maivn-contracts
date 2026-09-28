"""Closed v2 document body blocks and the document plan body."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from maivn_contracts.artifacts.plan_inputs import (
    STRUCTURAL_ID_PATTERN,
    RedactedArtifactPayload,
)
from maivn_contracts.artifacts.primitives import (
    CROP_PER_MILLE_SCALE,
    MAX_DOCUMENT_BLOCKS,
    MAX_DOCUMENT_FRAGMENTS,
    MAX_DOCUMENT_REDACTED_UTF8_BYTES,
    MAX_DOCUMENT_RUNS,
    MAX_DOCUMENT_STRUCTURAL_IDS,
    ArtifactRefInvariantError,
    ClosedModel,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = [
    'CropPerMille',
    'DocumentFlowBlockV2',
    'DocumentFootnoteV2',
    'DocumentHeadingBlockV2',
    'DocumentImageBlockV2',
    'DocumentListItemV2',
    'DocumentMarginTwips',
    'DocumentNamedStyleV2',
    'DocumentNestedBlockV2',
    'DocumentOrderedListBlockV2',
    'DocumentPageBreakBlockV2',
    'DocumentPageSettingsV2',
    'DocumentParagraphBlockV2',
    'DocumentPlanBodyV2',
    'DocumentRegionV2',
    'DocumentTableBlockV2',
    'DocumentTableCellV2',
    'DocumentTableRowV2',
    'DocumentTextRunV2',
    'DocumentTwips',
    'DocumentUnorderedListBlockV2',
    '_document_container_ids',
    '_document_runs',
    '_walk_document_blocks',
]

DocumentTwips: TypeAlias = Annotated[StrictInt, Field(ge=1, le=31680)]
DocumentMarginTwips: TypeAlias = Annotated[StrictInt, Field(ge=0, le=14400)]


class DocumentPageSettingsV2(ClosedModel):
    """Bounded deterministic page geometry in twentieths of a point."""

    width_twips: DocumentTwips
    height_twips: DocumentTwips
    margin_top_twips: DocumentMarginTwips
    margin_right_twips: DocumentMarginTwips
    margin_bottom_twips: DocumentMarginTwips
    margin_left_twips: DocumentMarginTwips

    @model_validator(mode='after')
    def _validate_printable_area(self) -> DocumentPageSettingsV2:
        if (
            self.margin_left_twips + self.margin_right_twips >= self.width_twips
            or self.margin_top_twips + self.margin_bottom_twips >= self.height_twips
        ):
            raise ArtifactRefInvariantError
        return self


class DocumentNamedStyleV2(ClosedModel):
    """Closed named paragraph style referenced by stable ID."""

    style_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    font_family: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    font_size_half_points: Annotated[StrictInt, Field(ge=2, le=192)]
    bold: StrictBool
    italic: StrictBool


class DocumentTextRunV2(ClosedModel):
    """Structurally addressed redacted text plus closed character styling."""

    run_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    payload: RedactedArtifactPayload
    bold: StrictBool
    italic: StrictBool
    underline: StrictBool
    footnote_ids: tuple[Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)], ...] | None = (
        Field(default=None, max_length=32)
    )


class DocumentParagraphBlockV2(ClosedModel):
    """One stable paragraph containing bounded redacted runs."""

    block_type: Literal['paragraph']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    style_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)] | None = None
    runs: tuple[DocumentTextRunV2, ...] = Field(min_length=1, max_length=1000)


class DocumentHeadingBlockV2(ClosedModel):
    """One stable heading with a closed outline level."""

    block_type: Literal['heading']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    level: Annotated[StrictInt, Field(ge=1, le=9)]
    style_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)] | None = None
    runs: tuple[DocumentTextRunV2, ...] = Field(min_length=1, max_length=1000)


class DocumentListItemV2(ClosedModel):
    """Stable list item containing only approved nested flow blocks."""

    item_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    blocks: tuple[DocumentNestedBlockV2, ...] = Field(min_length=1, max_length=100)


class DocumentOrderedListBlockV2(ClosedModel):
    """Stable bounded ordered list."""

    block_type: Literal['ordered_list']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    start_at: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    items: tuple[DocumentListItemV2, ...] = Field(min_length=1, max_length=1000)


class DocumentUnorderedListBlockV2(ClosedModel):
    """Stable bounded unordered list."""

    block_type: Literal['unordered_list']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    marker: Literal['disc', 'circle', 'square']
    items: tuple[DocumentListItemV2, ...] = Field(min_length=1, max_length=1000)


DocumentNestedBlockV2: TypeAlias = Annotated[
    DocumentParagraphBlockV2 | DocumentOrderedListBlockV2 | DocumentUnorderedListBlockV2,
    Field(discriminator='block_type'),
]


class DocumentTableCellV2(ClosedModel):
    """Stable table cell without spans or merges."""

    cell_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    blocks: tuple[DocumentNestedBlockV2, ...] = Field(min_length=1, max_length=100)


class DocumentTableRowV2(ClosedModel):
    """Stable fixed-width table row."""

    row_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    is_header: StrictBool
    cells: tuple[DocumentTableCellV2, ...] = Field(min_length=1, max_length=100)


class DocumentTableBlockV2(ClosedModel):
    """Stable rectangular table with no merged cells."""

    block_type: Literal['table']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    column_count: Annotated[StrictInt, Field(ge=1, le=100)]
    rows: tuple[DocumentTableRowV2, ...] = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def _validate_rectangular_rows(self) -> DocumentTableBlockV2:
        if any(len(row.cells) != self.column_count for row in self.rows):
            raise ArtifactRefInvariantError
        return self


CropPerMille: TypeAlias = Annotated[StrictInt, Field(ge=0, le=999)]


class DocumentImageBlockV2(ClosedModel):
    """Stable inline image referencing one declared ordinary input."""

    block_type: Literal['image']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    input_local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    width_twips: DocumentTwips
    height_twips: DocumentTwips
    alignment: Literal['left', 'center', 'right']
    crop_left_per_mille: CropPerMille
    crop_top_per_mille: CropPerMille
    crop_right_per_mille: CropPerMille
    crop_bottom_per_mille: CropPerMille
    alt_text: RedactedArtifactPayload

    @model_validator(mode='after')
    def _validate_crop(self) -> DocumentImageBlockV2:
        if (
            self.crop_left_per_mille + self.crop_right_per_mille >= CROP_PER_MILLE_SCALE
            or self.crop_top_per_mille + self.crop_bottom_per_mille >= CROP_PER_MILLE_SCALE
        ):
            raise ArtifactRefInvariantError
        return self


class DocumentPageBreakBlockV2(ClosedModel):
    """Stable root-flow page break."""

    block_type: Literal['page_break']
    block_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


DocumentFlowBlockV2: TypeAlias = Annotated[
    DocumentParagraphBlockV2
    | DocumentHeadingBlockV2
    | DocumentOrderedListBlockV2
    | DocumentUnorderedListBlockV2
    | DocumentTableBlockV2
    | DocumentImageBlockV2
    | DocumentPageBreakBlockV2,
    Field(discriminator='block_type'),
]


DocumentListItemV2.model_rebuild()


def _walk_document_blocks(
    blocks: Iterable[DocumentFlowBlockV2 | DocumentNestedBlockV2],
) -> Iterator[DocumentFlowBlockV2 | DocumentNestedBlockV2]:
    for block in blocks:
        yield block
        if isinstance(block, (DocumentOrderedListBlockV2, DocumentUnorderedListBlockV2)):
            for item in block.items:
                yield from _walk_document_blocks(item.blocks)
        elif isinstance(block, DocumentTableBlockV2):
            for row in block.rows:
                for cell in row.cells:
                    yield from _walk_document_blocks(cell.blocks)


def _document_container_ids(
    blocks: Iterable[DocumentFlowBlockV2 | DocumentNestedBlockV2],
) -> Iterator[str]:
    for block in blocks:
        if isinstance(block, (DocumentOrderedListBlockV2, DocumentUnorderedListBlockV2)):
            yield from (item.item_id for item in block.items)
        elif isinstance(block, DocumentTableBlockV2):
            for row in block.rows:
                yield row.row_id
                yield from (cell.cell_id for cell in row.cells)


def _document_runs(
    blocks: Iterable[DocumentFlowBlockV2 | DocumentNestedBlockV2],
) -> Iterator[DocumentTextRunV2]:
    for block in blocks:
        if isinstance(block, (DocumentParagraphBlockV2, DocumentHeadingBlockV2)):
            yield from block.runs


class DocumentRegionV2(ClosedModel):
    """Stable header or footer region containing approved nested blocks."""

    region_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    slot: Literal['default', 'first', 'even']
    blocks: tuple[DocumentNestedBlockV2, ...] = Field(max_length=100)


class DocumentFootnoteV2(ClosedModel):
    """Stable footnote content referenced by document runs."""

    footnote_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    blocks: tuple[DocumentNestedBlockV2, ...] = Field(min_length=1, max_length=100)


class DocumentPlanBodyV2(ClosedModel):
    """Closed normalized document structure for deterministic rendering."""

    template_local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)] | None = None
    page_settings: DocumentPageSettingsV2
    styles: tuple[DocumentNamedStyleV2, ...] = Field(max_length=256)
    headers: tuple[DocumentRegionV2, ...] = Field(max_length=16)
    footers: tuple[DocumentRegionV2, ...] = Field(max_length=16)
    footnotes: tuple[DocumentFootnoteV2, ...] = Field(max_length=1000)
    blocks: tuple[DocumentFlowBlockV2, ...] = Field(min_length=1, max_length=10000)

    def _all_blocks(self) -> tuple[DocumentFlowBlockV2 | DocumentNestedBlockV2, ...]:
        root_blocks: list[DocumentFlowBlockV2 | DocumentNestedBlockV2] = list(self.blocks)
        for region in (*self.headers, *self.footers):
            root_blocks.extend(region.blocks)
        for footnote in self.footnotes:
            root_blocks.extend(footnote.blocks)
        return tuple(_walk_document_blocks(root_blocks))

    def structural_ids(self) -> tuple[str, ...]:
        """Return every plan-local structural identifier in the body."""
        blocks = self._all_blocks()
        runs = tuple(_document_runs(blocks))
        image_payloads = tuple(
            block.alt_text for block in blocks if isinstance(block, DocumentImageBlockV2)
        )
        identifiers = [style.style_id for style in self.styles]
        identifiers.extend(region.region_id for region in (*self.headers, *self.footers))
        identifiers.extend(footnote.footnote_id for footnote in self.footnotes)
        identifiers.extend(block.block_id for block in blocks)
        identifiers.extend(_document_container_ids(blocks))
        identifiers.extend(run.run_id for run in runs)
        identifiers.extend(
            fragment.structural_id for run in runs for fragment in run.payload.fragments
        )
        identifiers.extend(
            fragment.structural_id for payload in image_payloads for fragment in payload.fragments
        )
        return tuple(identifiers)

    @model_validator(mode='after')
    def _validate_unique_structural_ids(self) -> DocumentPlanBodyV2:
        blocks = self._all_blocks()
        runs = tuple(_document_runs(blocks))
        image_payloads = tuple(
            block.alt_text for block in blocks if isinstance(block, DocumentImageBlockV2)
        )
        identifiers = self.structural_ids()
        if len(identifiers) != len(set(identifiers)):
            raise ArtifactRefInvariantError
        fragment_count = sum(len(run.payload.fragments) for run in runs) + sum(
            len(payload.fragments) for payload in image_payloads
        )
        if (
            len(blocks) > MAX_DOCUMENT_BLOCKS
            or len(runs) > MAX_DOCUMENT_RUNS
            or fragment_count > MAX_DOCUMENT_FRAGMENTS
            or len(identifiers) > MAX_DOCUMENT_STRUCTURAL_IDS
        ):
            raise ArtifactRefInvariantError
        referenced_style_ids = {
            block.style_id
            for block in blocks
            if isinstance(block, (DocumentParagraphBlockV2, DocumentHeadingBlockV2))
            and block.style_id is not None
        }
        if referenced_style_ids != {style.style_id for style in self.styles}:
            raise ArtifactRefInvariantError
        referenced_footnote_ids = {
            footnote_id for run in runs for footnote_id in (run.footnote_ids or ())
        }
        if set(referenced_footnote_ids) != {footnote.footnote_id for footnote in self.footnotes}:
            raise ArtifactRefInvariantError
        header_slots = tuple(region.slot for region in self.headers)
        footer_slots = tuple(region.slot for region in self.footers)
        if len(header_slots) != len(set(header_slots)) or len(footer_slots) != len(
            set(footer_slots),
        ):
            raise ArtifactRefInvariantError
        redacted_utf8_bytes = sum(
            len(fragment.text.encode('utf-8')) for run in runs for fragment in run.payload.fragments
        ) + sum(
            len(fragment.text.encode('utf-8'))
            for payload in image_payloads
            for fragment in payload.fragments
        )
        if redacted_utf8_bytes > MAX_DOCUMENT_REDACTED_UTF8_BYTES:
            raise ArtifactRefInvariantError
        return self

    def used_image_input_local_ids(self) -> frozenset[str]:
        """Return image inputs structurally consumed by this body."""
        return frozenset(
            block.input_local_id
            for block in self._all_blocks()
            if isinstance(block, DocumentImageBlockV2)
        )
