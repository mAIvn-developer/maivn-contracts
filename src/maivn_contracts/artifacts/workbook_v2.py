"""Closed v2 workbook cells, formulas, ranges and the workbook plan body."""

from __future__ import annotations

import re
from datetime import date
from math import isfinite
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts.plan_inputs import (
    STRUCTURAL_ID_PATTERN,
    RedactedArtifactPayload,
)
from maivn_contracts.artifacts.primitives import (
    MAX_FORMULA_DEPTH,
    MAX_FORMULA_NODES,
    MAX_WORKBOOK_CELLS,
    ArtifactRefInvariantError,
    ClosedModel,
    JcsSafeNumber,
    Rfc3339Timestamp,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    'WorkbookBooleanValueV2',
    'WorkbookCellV2',
    'WorkbookCellValueV2',
    'WorkbookChartSeriesV2',
    'WorkbookChartV2',
    'WorkbookColumn',
    'WorkbookDateTimeValueV2',
    'WorkbookDateValueV2',
    'WorkbookFormulaBinaryV2',
    'WorkbookFormulaBooleanV2',
    'WorkbookFormulaCellRefV2',
    'WorkbookFormulaFunctionV2',
    'WorkbookFormulaNamedRangeRefV2',
    'WorkbookFormulaNodeV2',
    'WorkbookFormulaNumberV2',
    'WorkbookFormulaRangeRefV2',
    'WorkbookFormulaUnaryV2',
    'WorkbookFormulaValueV2',
    'WorkbookNamedRangeV2',
    'WorkbookNumberValueV2',
    'WorkbookPlanBodyV2',
    'WorkbookRangeV2',
    'WorkbookRow',
    'WorkbookSheetV2',
    'WorkbookStyleV2',
    'WorkbookTableV2',
    'WorkbookTextValueV2',
    '_walk_workbook_formula',
]

WorkbookRow: TypeAlias = Annotated[StrictInt, Field(ge=1, le=1_048_576)]
WorkbookColumn: TypeAlias = Annotated[StrictInt, Field(ge=1, le=16_384)]


class WorkbookStyleV2(ClosedModel):
    """Closed cell style resolved against the attested font profile."""

    style_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    font_family: Literal['Noto Sans', 'Noto Serif', 'Noto Sans Mono']
    font_size_half_points: Annotated[StrictInt, Field(ge=2, le=192)]
    bold: StrictBool
    italic: StrictBool
    underline: StrictBool
    horizontal_alignment: Literal['left', 'center', 'right']
    wrap_text: StrictBool
    number_format_id: Literal[
        'general',
        'integer',
        'decimal_2',
        'percent_0',
        'percent_2',
        'currency_usd',
        'date_iso',
        'datetime_utc',
        'text',
    ]


class WorkbookTextValueV2(ClosedModel):
    """Redacted workbook text value."""

    value_type: Literal['text']
    payload: RedactedArtifactPayload


class WorkbookNumberValueV2(ClosedModel):
    """Finite workbook numeric value."""

    value_type: Literal['number']
    value: JcsSafeNumber

    @field_validator('value')
    @classmethod
    def _validate_finite_number(cls, value: float) -> float:
        if isinstance(value, float) and not isfinite(value):
            raise ArtifactRefInvariantError
        return value


class WorkbookBooleanValueV2(ClosedModel):
    """Strict workbook boolean value."""

    value_type: Literal['boolean']
    value: StrictBool


class WorkbookDateValueV2(ClosedModel):
    """Canonical Gregorian workbook date."""

    value_type: Literal['date']
    value: StrictStr

    @field_validator('value')
    @classmethod
    def _validate_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ArtifactRefInvariantError from None
        if parsed.strftime('%Y-%m-%d') != value or value == '1900-02-29':
            raise ArtifactRefInvariantError
        return value


class WorkbookDateTimeValueV2(ClosedModel):
    """Canonical aware UTC workbook date-time."""

    value_type: Literal['datetime']
    value: Rfc3339Timestamp


class WorkbookFormulaNumberV2(ClosedModel):
    """Finite numeric formula literal."""

    node_type: Literal['number']
    value: JcsSafeNumber

    @field_validator('value')
    @classmethod
    def _validate_finite_number(cls, value: float) -> float:
        if isinstance(value, float) and not isfinite(value):
            raise ArtifactRefInvariantError
        return value


class WorkbookFormulaBooleanV2(ClosedModel):
    """Boolean formula literal."""

    node_type: Literal['boolean']
    value: StrictBool


class WorkbookFormulaCellRefV2(ClosedModel):
    """Stable-ID cell reference without A1 text parsing."""

    node_type: Literal['cell_ref']
    cell_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookFormulaRangeRefV2(ClosedModel):
    """Stable-ID rectangular range reference."""

    node_type: Literal['range_ref']
    range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookFormulaNamedRangeRefV2(ClosedModel):
    """Stable-ID named range reference."""

    node_type: Literal['named_range_ref']
    named_range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookFormulaUnaryV2(ClosedModel):
    """Closed unary formula expression."""

    node_type: Literal['unary']
    operator: Literal['+', '-']
    operand: WorkbookFormulaNodeV2


class WorkbookFormulaBinaryV2(ClosedModel):
    """Closed binary formula expression."""

    node_type: Literal['binary']
    operator: Literal['+', '-', '*', '/', '^', '&', '=', '<>', '<', '<=', '>', '>=']
    left: WorkbookFormulaNodeV2
    right: WorkbookFormulaNodeV2


class WorkbookFormulaFunctionV2(ClosedModel):
    """Allowlisted workbook function call."""

    node_type: Literal['function']
    function: Literal['SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT', 'IF', 'AND', 'OR', 'NOT', 'ROUND']
    arguments: tuple[WorkbookFormulaNodeV2, ...] = Field(min_length=1, max_length=255)


WorkbookFormulaNodeV2: TypeAlias = Annotated[
    WorkbookFormulaNumberV2
    | WorkbookFormulaBooleanV2
    | WorkbookFormulaCellRefV2
    | WorkbookFormulaRangeRefV2
    | WorkbookFormulaNamedRangeRefV2
    | WorkbookFormulaUnaryV2
    | WorkbookFormulaBinaryV2
    | WorkbookFormulaFunctionV2,
    Field(discriminator='node_type'),
]


class WorkbookFormulaValueV2(ClosedModel):
    """Formula cell value represented only by a closed AST."""

    value_type: Literal['formula']
    expression: WorkbookFormulaNodeV2


WorkbookCellValueV2: TypeAlias = Annotated[
    WorkbookTextValueV2
    | WorkbookNumberValueV2
    | WorkbookBooleanValueV2
    | WorkbookDateValueV2
    | WorkbookDateTimeValueV2
    | WorkbookFormulaValueV2,
    Field(discriminator='value_type'),
]


class WorkbookCellV2(ClosedModel):
    """One populated typed cell at an exact coordinate."""

    cell_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    row: WorkbookRow
    column: WorkbookColumn
    style_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)] | None = None
    value: WorkbookCellValueV2


class WorkbookSheetV2(ClosedModel):
    """One bounded stable-ID worksheet."""

    sheet_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    name: Annotated[StrictStr, Field(min_length=1, max_length=31)]
    cells: tuple[WorkbookCellV2, ...] = Field(max_length=1_000_000)

    @field_validator('name')
    @classmethod
    def _validate_sheet_name(cls, value: str) -> str:
        if value != value.strip() or re.search(r'[\x00-\x1f\x7f\[\]:*?/\\]', value):
            raise ArtifactRefInvariantError
        return value


class WorkbookRangeV2(ClosedModel):
    """One bounded rectangular worksheet range."""

    range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    sheet_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    start_row: WorkbookRow
    end_row: WorkbookRow
    start_column: WorkbookColumn
    end_column: WorkbookColumn

    @model_validator(mode='after')
    def _validate_rectangle(self) -> WorkbookRangeV2:
        if self.start_row > self.end_row or self.start_column > self.end_column:
            raise ArtifactRefInvariantError
        if self.cell_count() > MAX_WORKBOOK_CELLS:
            raise ArtifactRefInvariantError
        return self

    def cell_count(self) -> int:
        """Return the rectangular range area."""
        return (self.end_row - self.start_row + 1) * (self.end_column - self.start_column + 1)


class WorkbookNamedRangeV2(ClosedModel):
    """Stable public alias for one declared range."""

    named_range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookTableV2(ClosedModel):
    """Closed table projection over one declared range."""

    table_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    table_style: Literal['none', 'light_1', 'medium_2', 'dark_1']


class WorkbookChartSeriesV2(ClosedModel):
    """One chart series bound to declared one-dimensional ranges."""

    series_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    category_range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    value_range_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookChartV2(ClosedModel):
    """Closed chart projection without external data connections."""

    chart_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    sheet_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    chart_type: Literal['bar', 'line', 'pie']
    anchor_row: WorkbookRow
    anchor_column: WorkbookColumn
    width_cells: Annotated[StrictInt, Field(ge=1, le=100)]
    height_cells: Annotated[StrictInt, Field(ge=1, le=100)]
    series: tuple[WorkbookChartSeriesV2, ...] = Field(min_length=1, max_length=64)


def _walk_workbook_formula(
    node: WorkbookFormulaNodeV2,
    *,
    depth: int = 1,
) -> Iterator[WorkbookFormulaNodeV2]:
    if depth > MAX_FORMULA_DEPTH:
        raise ArtifactRefInvariantError
    yield node
    if isinstance(node, WorkbookFormulaUnaryV2):
        yield from _walk_workbook_formula(node.operand, depth=depth + 1)
    elif isinstance(node, WorkbookFormulaBinaryV2):
        yield from _walk_workbook_formula(node.left, depth=depth + 1)
        yield from _walk_workbook_formula(node.right, depth=depth + 1)
    elif isinstance(node, WorkbookFormulaFunctionV2):
        for argument in node.arguments:
            yield from _walk_workbook_formula(argument, depth=depth + 1)


class WorkbookPlanBodyV2(ClosedModel):
    """Closed bounded workbook graph without raw formulas or external links."""

    template_local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)] | None = None
    styles: tuple[WorkbookStyleV2, ...] = Field(max_length=256)
    sheets: tuple[WorkbookSheetV2, ...] = Field(min_length=1, max_length=100)
    ranges: tuple[WorkbookRangeV2, ...] = Field(max_length=10_000)
    named_ranges: tuple[WorkbookNamedRangeV2, ...] = Field(max_length=10_000)
    tables: tuple[WorkbookTableV2, ...] = Field(max_length=1000)
    charts: tuple[WorkbookChartV2, ...] = Field(max_length=1000)

    @model_validator(mode='after')
    def _validate_graph(self) -> WorkbookPlanBodyV2:
        cells = tuple(cell for sheet in self.sheets for cell in sheet.cells)
        series = tuple(item for chart in self.charts for item in chart.series)
        text_fragments = tuple(
            fragment
            for cell in cells
            if isinstance(cell.value, WorkbookTextValueV2)
            for fragment in cell.value.payload.fragments
        )
        identifiers = self.structural_ids()
        if len(identifiers) != len(set(identifiers)) or len(cells) > MAX_WORKBOOK_CELLS:
            raise ArtifactRefInvariantError
        if len({sheet.name.casefold() for sheet in self.sheets}) != len(self.sheets):
            raise ArtifactRefInvariantError
        if any(
            len({(cell.row, cell.column) for cell in sheet.cells}) != len(sheet.cells)
            for sheet in self.sheets
        ):
            raise ArtifactRefInvariantError
        style_ids = {style.style_id for style in self.styles}
        referenced_style_ids = {cell.style_id for cell in cells if cell.style_id is not None}
        if referenced_style_ids != style_ids:
            raise ArtifactRefInvariantError
        self._validate_references(cells, series)
        if sum(len(fragment.text.encode('utf-8')) for fragment in text_fragments) > 4 * 1024 * 1024:
            raise ArtifactRefInvariantError
        return self

    def _validate_references(
        self,
        cells: tuple[WorkbookCellV2, ...],
        series: tuple[WorkbookChartSeriesV2, ...],
    ) -> None:
        sheet_ids = {sheet.sheet_id for sheet in self.sheets}
        cell_ids = {cell.cell_id for cell in cells}
        ranges = {item.range_id: item for item in self.ranges}
        named_range_ids = {item.named_range_id for item in self.named_ranges}
        if any(item.sheet_id not in sheet_ids for item in self.ranges):
            raise ArtifactRefInvariantError
        if any(item.range_id not in ranges for item in (*self.named_ranges, *self.tables)):
            raise ArtifactRefInvariantError
        if any(chart.sheet_id not in sheet_ids for chart in self.charts):
            raise ArtifactRefInvariantError
        if any(
            item.category_range_id not in ranges or item.value_range_id not in ranges
            for item in series
        ):
            raise ArtifactRefInvariantError
        for item in series:
            category = ranges[item.category_range_id]
            value = ranges[item.value_range_id]
            if category.cell_count() != value.cell_count() or not (
                category.start_row == category.end_row
                or category.start_column == category.end_column
            ):
                raise ArtifactRefInvariantError
        self._validate_formulas(cells, cell_ids, set(ranges), named_range_ids)

    def _validate_formulas(
        self,
        cells: tuple[WorkbookCellV2, ...],
        cell_ids: set[str],
        range_ids: set[str],
        named_range_ids: set[str],
    ) -> None:
        dependencies: dict[str, set[str]] = {}
        for cell in cells:
            if not isinstance(cell.value, WorkbookFormulaValueV2):
                continue
            nodes = tuple(_walk_workbook_formula(cell.value.expression))
            if len(nodes) > MAX_FORMULA_NODES:
                raise ArtifactRefInvariantError
            refs = {node.cell_id for node in nodes if isinstance(node, WorkbookFormulaCellRefV2)}
            if not refs.issubset(cell_ids):
                raise ArtifactRefInvariantError
            if any(
                node.range_id not in range_ids
                for node in nodes
                if isinstance(node, WorkbookFormulaRangeRefV2)
            ) or any(
                node.named_range_id not in named_range_ids
                for node in nodes
                if isinstance(node, WorkbookFormulaNamedRangeRefV2)
            ):
                raise ArtifactRefInvariantError
            dependencies[cell.cell_id] = refs
        self._reject_formula_cycles(dependencies)

    @staticmethod
    def _reject_formula_cycles(dependencies: dict[str, set[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(cell_id: str) -> None:
            if cell_id in visiting:
                raise ArtifactRefInvariantError
            if cell_id in visited:
                return
            visiting.add(cell_id)
            for dependency in dependencies.get(cell_id, set()):
                visit(dependency)
            visiting.remove(cell_id)
            visited.add(cell_id)

        for cell_id in dependencies:
            visit(cell_id)

    def structural_ids(self) -> tuple[str, ...]:
        """Return every workbook structural identifier."""
        return (
            *(style.style_id for style in self.styles),
            *(sheet.sheet_id for sheet in self.sheets),
            *(cell.cell_id for sheet in self.sheets for cell in sheet.cells),
            *(item.range_id for item in self.ranges),
            *(item.named_range_id for item in self.named_ranges),
            *(item.table_id for item in self.tables),
            *(item.chart_id for item in self.charts),
            *(item.series_id for chart in self.charts for item in chart.series),
            *(
                fragment.structural_id
                for sheet in self.sheets
                for cell in sheet.cells
                if isinstance(cell.value, WorkbookTextValueV2)
                for fragment in cell.value.payload.fragments
            ),
        )


WorkbookFormulaUnaryV2.model_rebuild()
WorkbookFormulaBinaryV2.model_rebuild()
WorkbookFormulaFunctionV2.model_rebuild()
