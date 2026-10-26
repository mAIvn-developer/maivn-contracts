# pyright: strict
"""Graph invariants of the closed V2 workbook plan body."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts.primitives import MAX_FORMULA_DEPTH
from maivn_contracts.artifacts.workbook_v2 import (
    WorkbookDateValueV2,
    WorkbookNumberValueV2,
    WorkbookPlanBodyV2,
    WorkbookRangeV2,
    WorkbookSheetV2,
)

if TYPE_CHECKING:
    from collections.abc import Callable

Body = dict[str, Any]


def _text_cell(cell_id: str, row: int, column: int, structural_id: str) -> dict[str, Any]:
    return {
        'cell_id': cell_id,
        'row': row,
        'column': column,
        'style_id': 'body_style',
        'value': {
            'value_type': 'text',
            'payload': {'fragments': [{'structural_id': structural_id, 'text': 'Label'}]},
        },
    }


def _formula_cell(cell_id: str, row: int, expression: dict[str, Any]) -> dict[str, Any]:
    return {
        'cell_id': cell_id,
        'row': row,
        'column': 3,
        'value': {'value_type': 'formula', 'expression': expression},
    }


def _range(range_id: str, start_row: int, end_row: int, column: int) -> dict[str, Any]:
    return {
        'range_id': range_id,
        'sheet_id': 'sheet_1',
        'start_row': start_row,
        'end_row': end_row,
        'start_column': column,
        'end_column': column,
    }


def _body() -> Body:
    return {
        'styles': [
            {
                'style_id': 'body_style',
                'font_family': 'Noto Sans',
                'font_size_half_points': 22,
                'bold': False,
                'italic': False,
                'underline': False,
                'horizontal_alignment': 'left',
                'wrap_text': False,
                'number_format_id': 'general',
            },
        ],
        'sheets': [
            {
                'sheet_id': 'sheet_1',
                'name': 'Sheet1',
                'cells': [
                    _text_cell('label_1', 1, 1, 'label_text_1'),
                    _text_cell('label_2', 2, 1, 'label_text_2'),
                    {
                        'cell_id': 'value_1',
                        'row': 1,
                        'column': 2,
                        'value': {'value_type': 'number', 'value': 2},
                    },
                    {
                        'cell_id': 'value_2',
                        'row': 2,
                        'column': 2,
                        'value': {'value_type': 'number', 'value': 3.5},
                    },
                    _formula_cell(
                        'total',
                        1,
                        {
                            'node_type': 'function',
                            'function': 'SUM',
                            'arguments': [
                                {'node_type': 'range_ref', 'range_id': 'values'},
                                {'node_type': 'named_range_ref', 'named_range_id': 'named_values'},
                                {
                                    'node_type': 'unary',
                                    'operator': '-',
                                    'operand': {'node_type': 'cell_ref', 'cell_id': 'value_1'},
                                },
                            ],
                        },
                    ),
                    _formula_cell(
                        'double',
                        2,
                        {
                            'node_type': 'binary',
                            'operator': '*',
                            'left': {'node_type': 'cell_ref', 'cell_id': 'total'},
                            'right': {'node_type': 'number', 'value': 2},
                        },
                    ),
                ],
            },
        ],
        'ranges': [_range('labels', 1, 2, 1), _range('values', 1, 2, 2)],
        'named_ranges': [{'named_range_id': 'named_values', 'range_id': 'values'}],
        'tables': [{'table_id': 'table_1', 'range_id': 'values', 'table_style': 'light_1'}],
        'charts': [
            {
                'chart_id': 'chart_1',
                'sheet_id': 'sheet_1',
                'chart_type': 'bar',
                'anchor_row': 5,
                'anchor_column': 1,
                'width_cells': 4,
                'height_cells': 4,
                'series': [
                    {
                        'series_id': 'series_1',
                        'category_range_id': 'labels',
                        'value_range_id': 'values',
                    },
                ],
            },
        ],
    }


def _cells(body: Body) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = body['sheets'][0]['cells']
    return cells


def test_complete_workbook_graph_is_accepted_with_every_structural_id() -> None:
    """A graph using every reference kind validates and lists ids in declaration order."""
    body = WorkbookPlanBodyV2.model_validate(_body())
    assert body.structural_ids() == (
        'body_style',
        'sheet_1',
        'label_1',
        'label_2',
        'value_1',
        'value_2',
        'total',
        'double',
        'labels',
        'values',
        'named_values',
        'table_1',
        'chart_1',
        'series_1',
        'label_text_1',
        'label_text_2',
    )


def _set(path: tuple[Any, ...], value: object) -> Callable[[Body], None]:
    def apply(body: Body) -> None:
        target: Any = body
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return apply


def _append_cell(cell: dict[str, Any]) -> Callable[[Body], None]:
    return lambda body: _cells(body).append(cell)


def _add_sheet(name: str) -> Callable[[Body], None]:
    return lambda body: body['sheets'].append({'sheet_id': 'sheet_2', 'name': name, 'cells': []})


def _cycle(body: Body) -> None:
    _cells(body)[4]['value']['expression']['arguments'][2]['operand']['cell_id'] = 'double'


def _two_dimensional_category(body: Body) -> None:
    body['ranges'][0] = {**_range('labels', 1, 2, 1), 'end_column': 2}
    body['ranges'][1] = _range('values', 1, 4, 2)


INVALID_GRAPHS: dict[str, Callable[[Body], None]] = {
    'duplicate-id-across-kinds': _set(('tables', 0, 'table_id'), 'chart_1'),
    'duplicate-fragment-id': _set(
        ('sheets', 0, 'cells', 1, 'value', 'payload', 'fragments', 0, 'structural_id'),
        'label_text_1',
    ),
    'duplicate-sheet-name-casefold': _add_sheet('SHEET1'),
    'duplicate-coordinate': _append_cell(_text_cell('label_3', 1, 1, 'label_text_3')),
    'unknown-style': _set(('sheets', 0, 'cells', 0, 'style_id'), 'other_style'),
    'unused-style': _set(
        ('styles',),
        [*_body()['styles'], {**_body()['styles'][0], 'style_id': 'unused_style'}],
    ),
    'range-on-unknown-sheet': _set(('ranges', 0, 'sheet_id'), 'sheet_9'),
    'named-range-to-unknown-range': _set(('named_ranges', 0, 'range_id'), 'missing'),
    'table-on-unknown-range': _set(('tables', 0, 'range_id'), 'missing'),
    'chart-on-unknown-sheet': _set(('charts', 0, 'sheet_id'), 'sheet_9'),
    'series-unknown-category': _set(('charts', 0, 'series', 0, 'category_range_id'), 'x'),
    'series-unknown-value': _set(('charts', 0, 'series', 0, 'value_range_id'), 'x'),
    'series-size-mismatch': _set(('ranges', 0, 'end_row'), 3),
    'series-two-dimensional-category': _two_dimensional_category,
    'formula-unknown-cell': _set(
        ('sheets', 0, 'cells', 5, 'value', 'expression', 'left', 'cell_id'),
        'missing',
    ),
    'formula-unknown-range': _set(
        ('sheets', 0, 'cells', 4, 'value', 'expression', 'arguments', 0, 'range_id'),
        'missing',
    ),
    'formula-unknown-named-range': _set(
        ('sheets', 0, 'cells', 4, 'value', 'expression', 'arguments', 1, 'named_range_id'),
        'missing',
    ),
    'formula-cycle': _cycle,
    'formula-self-reference': _set(
        ('sheets', 0, 'cells', 5, 'value', 'expression', 'left', 'cell_id'),
        'double',
    ),
}


@pytest.mark.parametrize('case', sorted(INVALID_GRAPHS))
def test_workbook_graph_refuses_broken_references_and_cycles(case: str) -> None:
    """Every identifier, reference, coordinate, style and formula rule is enforced."""
    body = _body()
    INVALID_GRAPHS[case](body)
    with pytest.raises(ValidationError):
        WorkbookPlanBodyV2.model_validate(body)


def test_formula_cells_may_share_dependencies_without_forming_a_cycle() -> None:
    """A diamond of formula references is not a cycle."""
    body = _body()
    _cells(body).append(
        _formula_cell(
            'diamond',
            3,
            {
                'node_type': 'binary',
                'operator': '+',
                'left': {'node_type': 'cell_ref', 'cell_id': 'total'},
                'right': {'node_type': 'cell_ref', 'cell_id': 'double'},
            },
        ),
    )
    assert WorkbookPlanBodyV2.model_validate(body)


def _nested_unary(depth: int) -> dict[str, Any]:
    node: dict[str, Any] = {'node_type': 'number', 'value': 1}
    for _ in range(depth - 1):
        node = {'node_type': 'unary', 'operator': '-', 'operand': node}
    return node


def test_formula_depth_is_bounded_inclusively() -> None:
    """An expression exactly MAX_FORMULA_DEPTH deep is accepted; one deeper is refused."""
    body = _body()
    _cells(body).append(_formula_cell('deep', 3, _nested_unary(MAX_FORMULA_DEPTH)))
    assert WorkbookPlanBodyV2.model_validate(body)

    body = _body()
    _cells(body).append(_formula_cell('deep', 3, _nested_unary(MAX_FORMULA_DEPTH + 1)))
    with pytest.raises(ValidationError):
        WorkbookPlanBodyV2.model_validate(body)


@pytest.mark.parametrize('value', ['2024-02-29', '2023-12-31', '1900-03-01'])
def test_dates_accept_canonical_gregorian_days(value: str) -> None:
    """Canonical ISO dates validate unchanged."""
    assert WorkbookDateValueV2(value_type='date', value=value).value == value


@pytest.mark.parametrize('value', ['2023-02-29', '1900-02-29', '2024-2-01', '20240201', 'today'])
def test_dates_refuse_non_canonical_or_impossible_days(value: str) -> None:
    """Impossible days, the spreadsheet 1900 leap-year bug and non-canonical text fail."""
    with pytest.raises(ValidationError):
        WorkbookDateValueV2(value_type='date', value=value)


@pytest.mark.parametrize('value', [float('inf'), float('-inf'), float('nan')])
def test_numbers_refuse_non_finite_floats(value: float) -> None:
    """Infinity and NaN never reach a workbook."""
    with pytest.raises(ValidationError):
        WorkbookNumberValueV2(value_type='number', value=value)


@pytest.mark.parametrize(
    'name', [' Sheet', 'Sheet ', 'A:B', 'A/B', 'A\\B', 'A[1]', 'A?', 'A*', 'A\x07']
)
def test_sheet_names_refuse_padding_and_excel_reserved_characters(name: str) -> None:
    """Padded names and the characters spreadsheet applications reserve are refused."""
    with pytest.raises(ValidationError):
        WorkbookSheetV2(sheet_id='sheet_1', name=name, cells=())


def test_ranges_must_be_ordered_rectangles() -> None:
    """Start may equal end; start after end on either axis is refused."""
    assert WorkbookRangeV2.model_validate(_range('one', 2, 2, 2)).cell_count() == 1
    for start_row, end_row, start_column, end_column in ((3, 2, 1, 1), (1, 1, 3, 2)):
        with pytest.raises(ValidationError):
            WorkbookRangeV2.model_validate(
                {
                    **_range('bad', start_row, end_row, 1),
                    'start_column': start_column,
                    'end_column': end_column,
                },
            )
