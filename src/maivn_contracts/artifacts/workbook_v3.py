"""Closed rich workbook artifact plan."""

from __future__ import annotations

import re
from datetime import date, datetime  # noqa: TC003 - Pydantic runtime types
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts.common_v3 import (
    ArtifactPlanMetadataV3,
    ChartSpec,
    HexColor,
    ImagePlacement,
    PositivePoints,
    RichArtifactInvariantError,
    RichArtifactModel,
    StructuralId,
)

_CELL_PATTERN = r'^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$'
_RANGE_PATTERN = (
    r'^(?:[A-Za-z][A-Za-z0-9_ ]{0,30}!)?\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}'
    r'(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?$'
)
_FORMULA_FUNCTION = re.compile(r'(?i)([A-Z][A-Z0-9_.]*)\s*\(')
_ALLOWED_FUNCTIONS = frozenset(
    {
        'ABS',
        'AND',
        'AVERAGE',
        'COUNT',
        'COUNTA',
        'DATE',
        'DAY',
        'IF',
        'IFS',
        'INDEX',
        'MATCH',
        'MAX',
        'MIN',
        'MONTH',
        'NOT',
        'OR',
        'ROUND',
        'SUM',
        'SUMIF',
        'SUMIFS',
        'TODAY',
        'YEAR',
    }
)
_UNSAFE_FORMULA_MARKERS = ('[', ']', '|', '://', '_xll', 'cmd', 'dde', '\x00')
_MAX_FORMULA_LENGTH = 8_192
_MAX_WORKBOOK_SHEETS = 100
_MAX_WORKBOOK_CELLS = 1_000_000


def _validate_formula_text(value: str) -> str:
    if (
        not value.startswith('=')
        or len(value) > _MAX_FORMULA_LENGTH
        or any(marker in value.casefold() for marker in _UNSAFE_FORMULA_MARKERS)
    ):
        raise RichArtifactInvariantError
    functions = {match.group(1).upper() for match in _FORMULA_FUNCTION.finditer(value)}
    if not functions.issubset(_ALLOWED_FUNCTIONS):
        raise RichArtifactInvariantError
    return value


class WorkbookThemeV3(RichArtifactModel):
    """Workbook brand theme."""

    primary: HexColor
    secondary: HexColor
    accent: HexColor
    font_family: Annotated[StrictStr, Field(min_length=1, max_length=128)]


class WorkbookCellStyleV3(RichArtifactModel):
    """Closed cell appearance."""

    fill: HexColor | None = None
    font_color: HexColor | None = None
    bold: StrictBool = False
    italic: StrictBool = False
    number_format: Annotated[StrictStr, Field(min_length=1, max_length=128)] = 'General'
    horizontal_alignment: Literal['general', 'left', 'center', 'right'] = 'general'
    vertical_alignment: Literal['top', 'center', 'bottom'] = 'bottom'
    wrap_text: StrictBool = False
    border_color: HexColor | None = None


class WorkbookTextValueV3(RichArtifactModel):
    """Text cell value."""

    value_type: Literal['text']
    text: Annotated[StrictStr, Field(max_length=32_767)]


class WorkbookNumberValueV3(RichArtifactModel):
    """Finite numeric cell value."""

    value_type: Literal['number']
    number: Annotated[StrictFloat | StrictInt, Field(ge=-1e15, le=1e15)]


class WorkbookBooleanValueV3(RichArtifactModel):
    """Boolean cell value."""

    value_type: Literal['boolean']
    boolean: StrictBool


class WorkbookDateValueV3(RichArtifactModel):
    """Date cell value."""

    value_type: Literal['date']
    date_value: date


class WorkbookDateTimeValueV3(RichArtifactModel):
    """Datetime cell value."""

    value_type: Literal['datetime']
    datetime_value: datetime


class WorkbookFormulaValueV3(RichArtifactModel):
    """Allowlisted workbook formula."""

    value_type: Literal['formula']
    formula: Annotated[StrictStr, Field(min_length=2, max_length=8_192)]

    _formula_is_safe = field_validator('formula')(_validate_formula_text)


WorkbookCellValueV3: TypeAlias = Annotated[
    WorkbookTextValueV3
    | WorkbookNumberValueV3
    | WorkbookBooleanValueV3
    | WorkbookDateValueV3
    | WorkbookDateTimeValueV3
    | WorkbookFormulaValueV3,
    Field(discriminator='value_type'),
]


class WorkbookCellV3(RichArtifactModel):
    """Typed cell with optional appearance and link/note metadata."""

    address: Annotated[StrictStr, Field(pattern=_CELL_PATTERN)]
    value: WorkbookCellValueV3
    style: WorkbookCellStyleV3 | None = None
    note: Annotated[StrictStr, Field(max_length=4_096)] | None = None
    https_link: Annotated[StrictStr, Field(pattern=r'^https://[^\s]{1,2039}$')] | None = None


class WorkbookDefinedNameV3(RichArtifactModel):
    """Workbook-scoped safe named reference."""

    name: Annotated[StrictStr, Field(pattern=r'^[A-Za-z_][A-Za-z0-9_.]{0,254}$')]
    formula: Annotated[StrictStr, Field(min_length=2, max_length=8_192)]

    _formula_is_safe = field_validator('formula')(_validate_formula_text)


class WorkbookColumnWidthV3(RichArtifactModel):
    """Column display width."""

    column: Annotated[StrictStr, Field(pattern=r'^[A-Z]{1,3}$')]
    width: Annotated[StrictFloat, Field(gt=0.0, le=255.0)]


class WorkbookRowHeightV3(RichArtifactModel):
    """Row display height."""

    row: Annotated[StrictInt, Field(ge=1, le=1_048_576)]
    height_points: PositivePoints


class WorkbookGroupV3(RichArtifactModel):
    """Row or column outline group."""

    axis: Literal['row', 'column']
    start: Annotated[StrictInt, Field(ge=1, le=1_048_576)]
    end: Annotated[StrictInt, Field(ge=1, le=1_048_576)]
    level: Annotated[StrictInt, Field(ge=1, le=8)]
    collapsed: StrictBool


class WorkbookTableV3(RichArtifactModel):
    """Native worksheet table."""

    table_id: StructuralId
    name: Annotated[StrictStr, Field(pattern=r'^[A-Za-z_][A-Za-z0-9_.]{0,254}$')]
    range: Annotated[StrictStr, Field(pattern=_RANGE_PATTERN)]
    style: Literal['light1', 'light9', 'medium2', 'medium4', 'medium9', 'dark2']
    show_totals: StrictBool


class WorkbookValidationV3(RichArtifactModel):
    """Safe cell validation rule."""

    validation_id: StructuralId
    range: Annotated[StrictStr, Field(pattern=_RANGE_PATTERN)]
    kind: Literal['list', 'whole', 'decimal', 'date', 'text_length']
    formula1: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    formula2: Annotated[StrictStr, Field(max_length=512)] | None = None
    allow_blank: StrictBool


class WorkbookConditionalFormatV3(RichArtifactModel):
    """Bounded native conditional formatting rule."""

    range: Annotated[StrictStr, Field(pattern=_RANGE_PATTERN)]
    kind: Literal['cell', 'color_scale', 'data_bar', 'icon_set']
    operator: Literal['greaterThan', 'lessThan', 'between', 'equal'] | None
    formula: Annotated[StrictStr, Field(max_length=512)] | None
    color: HexColor


class WorkbookChartV3(RichArtifactModel):
    """Editable worksheet chart placement."""

    chart: ChartSpec
    anchor: Annotated[StrictStr, Field(pattern=_CELL_PATTERN)]
    width_points: PositivePoints
    height_points: PositivePoints


class WorkbookImageV3(RichArtifactModel):
    """Verified worksheet image placement."""

    image: ImagePlacement
    anchor: Annotated[StrictStr, Field(pattern=_CELL_PATTERN)]


class WorkbookNoteV3(RichArtifactModel):
    """Explicit cell note."""

    address: Annotated[StrictStr, Field(pattern=_CELL_PATTERN)]
    text: Annotated[StrictStr, Field(min_length=1, max_length=4_096)]


class WorkbookPrintSetupV3(RichArtifactModel):
    """Print-ready worksheet settings."""

    orientation: Literal['portrait', 'landscape']
    paper_size: Literal['letter', 'legal', 'a4', 'a3']
    fit_to_width: Annotated[StrictInt, Field(ge=0, le=100)]
    fit_to_height: Annotated[StrictInt, Field(ge=0, le=100)]
    print_area: Annotated[StrictStr, Field(pattern=_RANGE_PATTERN)]
    repeat_rows: Annotated[StrictStr, Field(pattern=r'^\$?[1-9][0-9]*:\$?[1-9][0-9]*$')] | None


class WorkbookSheetV3(RichArtifactModel):
    """Complete worksheet surface."""

    sheet_id: StructuralId
    name: Annotated[StrictStr, Field(min_length=1, max_length=31)]
    visibility: Literal['visible', 'hidden']
    cells: tuple[WorkbookCellV3, ...] = Field(max_length=1_000_000)
    column_widths: tuple[WorkbookColumnWidthV3, ...] = Field(max_length=16_384)
    row_heights: tuple[WorkbookRowHeightV3, ...] = Field(max_length=100_000)
    merges: tuple[Annotated[StrictStr, Field(pattern=_RANGE_PATTERN)], ...] = Field(
        max_length=10_000
    )
    groups: tuple[WorkbookGroupV3, ...] = Field(max_length=10_000)
    freeze_panes: Annotated[StrictStr, Field(pattern=_CELL_PATTERN)] | None
    auto_filter: Annotated[StrictStr, Field(pattern=_RANGE_PATTERN)] | None
    tables: tuple[WorkbookTableV3, ...] = Field(max_length=1_000)
    validations: tuple[WorkbookValidationV3, ...] = Field(max_length=10_000)
    conditional_formats: tuple[WorkbookConditionalFormatV3, ...] = Field(max_length=10_000)
    charts: tuple[WorkbookChartV3, ...] = Field(max_length=256)
    images: tuple[WorkbookImageV3, ...] = Field(max_length=256)
    notes: tuple[WorkbookNoteV3, ...] = Field(max_length=10_000)
    print_setup: WorkbookPrintSetupV3

    @model_validator(mode='after')
    def _validate_unique_cells(self) -> WorkbookSheetV3:
        addresses = tuple(cell.address.replace('$', '') for cell in self.cells)
        if len(addresses) != len(set(addresses)):
            raise RichArtifactInvariantError
        return self


class WorkbookBodyV3(RichArtifactModel):
    """Rich workbook body."""

    theme: WorkbookThemeV3
    defined_names: tuple[WorkbookDefinedNameV3, ...] = Field(max_length=1_000)
    sheets: tuple[WorkbookSheetV3, ...] = Field(min_length=1, max_length=100)
    calculation_mode: Literal['auto']
    strip_metadata: Literal[True]


class WorkbookArtifactPlanV3(ArtifactPlanMetadataV3):
    """Closed rich ordinary XLSX plan."""

    kind: Literal['spreadsheet']
    output_mime_type: Literal['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
    body: WorkbookBodyV3

    @model_validator(mode='after')
    def _validate_workbook_bounds(self) -> WorkbookArtifactPlanV3:
        sheet_count = len(self.body.sheets)
        cell_count = sum(len(sheet.cells) for sheet in self.body.sheets)
        if (
            self.resource_bounds.max_sheets is None
            or self.resource_bounds.max_sheets < sheet_count
            or self.resource_bounds.max_sheets > _MAX_WORKBOOK_SHEETS
            or self.resource_bounds.max_cells is None
            or self.resource_bounds.max_cells < cell_count
            or self.resource_bounds.max_cells > _MAX_WORKBOOK_CELLS
        ):
            raise RichArtifactInvariantError
        return self
