# pyright: strict
"""Invariants of rich V3 presentation plans and document building blocks."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts.document_v3 import (
    DocumentPageV3,
    DocumentTableBlockV3,
    DocumentTocBlockV3,
)
from maivn_contracts.artifacts.presentation_v3 import (
    PresentationArtifactPlanV3,
    PresentationSlideSizeV3,
)

MAX_SLIDES = 500


def _rich_text(paragraph_id: str) -> dict[str, Any]:
    return {
        'paragraphs': [{'paragraph_id': paragraph_id, 'runs': [{'text': 'x'}], 'alignment': 'left'}]
    }


def _element(element_id: str) -> dict[str, Any]:
    return {
        'element_type': 'text',
        'element_id': element_id,
        'bounds': {'x': 0.0, 'y': 0.0, 'width': 100.0, 'height': 50.0},
        'content': _rich_text(f'{element_id}_p'),
        'rotation_degrees': 0.0,
        'opacity': 1.0,
        'alt_text': 'Text',
    }


def _slide(slide_id: str, **overrides: object) -> dict[str, Any]:
    slide: dict[str, Any] = {
        'slide_id': slide_id,
        'layout_id': 'hero',
        'section_id': 'intro',
        'title': 'Slide',
        'hidden': False,
        'elements': [_element(f'{slide_id}_title')],
        'speaker_notes': None,
        'show_slide_number': False,
        'footer': None,
        'transition': 'none',
    }
    slide.update(overrides)
    return slide


def _deck(
    *, slides: list[dict[str, Any]] | None = None, max_pages: int | None = 2
) -> dict[str, Any]:
    bounds: dict[str, int] = {'max_output_bytes': 1_000_000}
    if max_pages is not None:
        bounds['max_pages'] = max_pages
    return {
        'schema_version': 'v3',
        'kind': 'presentation',
        'logical_output_name': 'deck',
        'custody_request': 'ordinary',
        'input_refs': [],
        'renderer_profile': 'rich_presentation_v3',
        'renderer_min_version': '3.0.0',
        'output_mime_type': (
            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        ),
        'validation_profile': 'rich_presentation_v3',
        'disposition': 'final',
        'retention_request': {'retention_class': 'demo'},
        'resource_bounds': bounds,
        'body': {
            'theme': {
                'primary': '#17324D',
                'secondary': '#35C4B5',
                'accent': '#F4B942',
                'background': '#FFFFFF',
                'heading_font': 'Aptos Display',
                'body_font': 'Aptos',
            },
            'slide_size': {'preset': 'wide', 'width_points': None, 'height_points': None},
            'layouts': [{'layout_id': 'hero', 'name': 'Hero', 'background': '#17324D'}],
            'sections': [{'section_id': 'intro', 'title': 'Intro'}],
            'slides': slides
            if slides is not None
            else [_slide('one'), _slide('two', section_id=None)],
            'accessibility': {'title': 'Deck', 'description': 'A deck.', 'language': 'en'},
            'allow_animations': False,
            'allow_embedded_media': False,
            'allow_macros': False,
            'allow_ole': False,
        },
    }


def test_deck_accepts_exactly_bounded_slides_with_and_without_sections() -> None:
    """The page bound may equal the slide count; a slide may omit its section."""
    plan = PresentationArtifactPlanV3.model_validate(_deck())
    assert [slide.section_id for slide in plan.body.slides] == ['intro', None]


@pytest.mark.parametrize(
    'deck',
    [
        _deck(max_pages=None),
        _deck(max_pages=1),
        _deck(slides=[_slide('one')], max_pages=MAX_SLIDES + 1),
        _deck(slides=[_slide('one', layout_id='missing')]),
        _deck(slides=[_slide('one', section_id='missing')]),
        _deck(slides=[_slide('one', elements=[_element('dup'), _element('dup')])]),
    ],
    ids=['no-bound', 'under-bound', 'over-platform', 'layout', 'section', 'element-ids'],
)
def test_deck_refuses_bad_bounds_references_and_duplicate_elements(deck: dict[str, Any]) -> None:
    """Page bounds cover the slides; layouts and sections resolve; element ids are unique."""
    with pytest.raises(ValidationError):
        PresentationArtifactPlanV3.model_validate(deck)


@pytest.mark.parametrize(
    ('preset', 'width', 'height', 'valid'),
    [
        ('custom', 800.0, 600.0, True),
        ('wide', None, None, True),
        ('custom', 800.0, None, False),
        ('custom', None, None, False),
        ('standard', 800.0, 600.0, False),
    ],
)
def test_slide_size_custom_dimensions_exactly_when_custom(
    preset: str,
    width: float | None,
    height: float | None,
    valid: bool,  # noqa: FBT001 - parametrized expectation
) -> None:
    """Only a custom preset carries both dimensions."""
    payload = {'preset': preset, 'width_points': width, 'height_points': height}
    if valid:
        assert PresentationSlideSizeV3.model_validate(payload).preset == preset
    else:
        with pytest.raises(ValidationError):
            PresentationSlideSizeV3.model_validate(payload)


def _page(left: float, right: float, top: float, bottom: float) -> dict[str, Any]:
    return {
        'width_points': 600.0,
        'height_points': 800.0,
        'margins': {'top': top, 'right': right, 'bottom': bottom, 'left': left},
        'orientation': 'portrait',
        'columns': 1,
    }


def test_document_page_margins_leave_a_printable_area() -> None:
    """Opposite margins must leave positive width and height."""
    assert DocumentPageV3.model_validate(_page(299.0, 300.0, 399.0, 400.0))
    for margins in ((300.0, 300.0, 0.0, 0.0), (0.0, 0.0, 400.0, 400.0)):
        with pytest.raises(ValidationError):
            DocumentPageV3.model_validate(_page(*margins))


def test_document_toc_levels_are_ordered() -> None:
    """The lowest heading level cannot exceed the highest."""
    toc = {'block_type': 'toc', 'block_id': 'toc', 'title': 'Contents'}
    assert DocumentTocBlockV3.model_validate({**toc, 'min_level': 2, 'max_level': 2})
    with pytest.raises(ValidationError):
        DocumentTocBlockV3.model_validate({**toc, 'min_level': 3, 'max_level': 2})


def _cell(cell_id: str, span: int) -> dict[str, Any]:
    return {
        'cell_id': cell_id,
        'content': _rich_text(f'{cell_id}_p'),
        'column_span': span,
        'row_span': 1,
    }


def _table(header_rows: int, *spans: tuple[int, ...]) -> dict[str, Any]:
    return {
        'block_type': 'table',
        'block_id': 'table',
        'column_count': 2,
        'banded_rows': False,
        'header_rows': header_rows,
        'rows': [
            {
                'row_id': f'row_{index}',
                'header': index == 0,
                'repeat_header': False,
                'cells': [_cell(f'cell_{index}_{n}', span) for n, span in enumerate(row)],
            }
            for index, row in enumerate(spans)
        ],
    }


def test_document_table_rows_fill_the_columns_and_headers_fit() -> None:
    """Every row's spans sum to the column count; header rows cannot exceed the rows."""
    assert DocumentTableBlockV3.model_validate(_table(2, (1, 1), (2,)))
    for table in (_table(3, (1, 1), (2,)), _table(0, (1, 1), (1,)), _table(0, (2, 1))):
        with pytest.raises(ValidationError):
            DocumentTableBlockV3.model_validate(table)
