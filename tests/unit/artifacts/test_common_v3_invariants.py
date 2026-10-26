# pyright: strict
"""Invariants of the shared rich V3 content models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts.common_v3 import (
    ChartSpec,
    HttpsLinkTarget,
    ImagePlacement,
    Paragraph,
)


@pytest.mark.parametrize(
    'uri',
    [
        'http://example.com/a',
        'https:///path-only',
        'https://user@example.com/a',
        'https://user:secret@example.com/a',
        'https://example.com/a\tb',
        'https://example.com/a\x7fb',
    ],
)
def test_https_links_refuse_other_schemes_userinfo_and_control_characters(uri: str) -> None:
    """Links are https with a host, no credentials and no control characters."""
    with pytest.raises(ValidationError):
        HttpsLinkTarget(uri=uri)


def test_https_links_accept_query_and_fragment() -> None:
    """Ordinary absolute https links are kept verbatim."""
    uri = 'https://example.com/report?q=1#section'
    assert HttpsLinkTarget(uri=uri).uri == uri


def _paragraph(**overrides: object) -> dict[str, Any]:
    paragraph: dict[str, Any] = {
        'paragraph_id': 'body',
        'runs': [{'text': 'Hello'}],
        'alignment': 'left',
    }
    paragraph.update(overrides)
    return paragraph


def test_paragraph_list_id_and_level_come_together() -> None:
    """A list item names both its list and its level, or neither."""
    assert Paragraph.model_validate(_paragraph(list_id='steps', list_level=0)).list_level == 0
    assert Paragraph.model_validate(_paragraph()).list_id is None
    for overrides in ({'list_id': 'steps'}, {'list_level': 1}):
        with pytest.raises(ValidationError):
            Paragraph.model_validate(_paragraph(**overrides))


def _placement(**overrides: object) -> dict[str, Any]:
    placement: dict[str, Any] = {
        'input_local_id': 'logo',
        'width_points': 72.0,
        'height_points': 72.0,
        'crop_left': 0.0,
        'crop_top': 0.0,
        'crop_right': 0.0,
        'crop_bottom': 0.0,
        'rotation_degrees': 0.0,
        'opacity': 1.0,
        'alt_text': 'Company logo',
    }
    placement.update(overrides)
    return placement


def test_image_placement_crop_must_leave_visible_pixels() -> None:
    """Opposite crops must sum below one on each axis."""
    assert ImagePlacement.model_validate(_placement(crop_left=0.4, crop_right=0.5))
    for overrides in ({'crop_left': 0.5, 'crop_right': 0.5}, {'crop_top': 0.9, 'crop_bottom': 0.1}):
        with pytest.raises(ValidationError):
            ImagePlacement.model_validate(_placement(**overrides))


def _chart(*series_lengths: int) -> dict[str, Any]:
    return {
        'chart_id': 'revenue',
        'chart_type': 'bar',
        'title': 'Revenue',
        'categories': ['Q1', 'Q2'],
        'series': [
            {'name': f'series {index}', 'values': [1.0] * length, 'color': '#112233FF'}
            for index, length in enumerate(series_lengths)
        ],
        'show_legend': True,
        'show_data_labels': False,
        'alt_text': 'Quarterly revenue',
    }


def test_chart_series_match_the_category_count() -> None:
    """Every series has exactly one value per category."""
    assert ChartSpec.model_validate(_chart(2, 2))
    for lengths in ((1,), (2, 3)):
        with pytest.raises(ValidationError):
            ChartSpec.model_validate(_chart(*lengths))
