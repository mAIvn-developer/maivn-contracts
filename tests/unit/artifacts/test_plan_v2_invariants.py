# pyright: strict
"""Plan-level invariants of the V2 image and workbook artifact plans."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.artifacts.plan_contracts import (
    DocumentArtifactPlanV2,
    ImageArtifactPlanV2,
    WorkbookArtifactPlanV2,
)

MAX_IMAGE_PIXELS = 40_000_000
MAX_TOTAL_DECODED_PIXELS = 160_000_000
MAX_WORKBOOK_SHEETS = 100
MAX_WORKBOOK_CELLS = 1_000_000


def _envelope(kind: str, mime: str, bounds: dict[str, int]) -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': kind,
        'logical_output_name': f'plan_{kind}',
        'custody_request': 'ordinary',
        'input_refs': [],
        'renderer_profile': 'renderer',
        'renderer_min_version': '2.0',
        'output_mime_type': mime,
        'validation_profile': 'default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {'max_output_bytes': 1_000_000, **bounds},
    }


def _image_plan(**overrides: object) -> dict[str, Any]:
    plan = _envelope(
        'image',
        'image/png',
        {'max_pixels': 10_000, 'max_total_decoded_pixels': 40_000},
    )
    plan['body'] = {
        'canvas': {'width_pixels': 100, 'height_pixels': 100, 'color_space': 'srgb'},
        'layers': [
            {
                'layer_type': 'input_raster',
                'layer_id': 'photo_layer',
                'input_local_id': 'photo',
                'x_pixels': 0,
                'y_pixels': 0,
                'width_pixels': 100,
                'height_pixels': 100,
                'opacity_per_mille': 1000,
            },
            {
                'layer_type': 'shape',
                'layer_id': 'frame',
                'shape': 'rectangle',
                'x_pixels': 0,
                'y_pixels': 0,
                'width_pixels': 100,
                'height_pixels': 100,
                'fill_rgb_hex': 'FFFFFF',
                'opacity_per_mille': 0,
                'stroke_rgb_hex': '000000',
                'stroke_width_pixels': 2,
            },
        ],
        'operations': [
            {
                'operation_type': 'composite',
                'operation_id': 'stack',
                'layer_ids': ['photo_layer', 'frame'],
            },
            {'operation_type': 'annotate', 'operation_id': 'note', 'layer_id': 'frame'},
            {
                'operation_type': 'encode',
                'operation_id': 'encode_1',
                'mime_type': 'image/png',
                'quality': 90,
            },
        ],
    }
    plan['input_refs'] = [
        {'local_id': 'photo', 'ref_type': 'artifact', 'artifact_id': 'art_0001', 'revision': 1},
    ]
    plan.update(overrides)
    return plan


def test_image_plan_with_composite_and_annotation_is_accepted() -> None:
    """Every layer and operation reference resolves; the last operation encodes."""
    plan = ImageArtifactPlanV2.model_validate(_image_plan())
    assert plan.body.structural_ids()[:2] == ('photo_layer', 'frame')


def _with_body(change: dict[str, Any]) -> dict[str, Any]:
    plan = _image_plan()
    plan['body'] = {**plan['body'], **change}
    return plan


def _operations(*operations: dict[str, Any]) -> dict[str, Any]:
    return _with_body({'operations': list(operations)})


ENCODE = {
    'operation_type': 'encode',
    'operation_id': 'encode_1',
    'mime_type': 'image/png',
    'quality': 90,
}
INVALID_IMAGE_PLANS: dict[str, dict[str, Any]] = {
    'duplicate-layer-and-operation-id': _operations(
        {'operation_type': 'rotate', 'operation_id': 'frame', 'degrees': 90},
        ENCODE,
    ),
    'composite-unknown-layer': _operations(
        {'operation_type': 'composite', 'operation_id': 'stack', 'layer_ids': ['missing']},
        ENCODE,
    ),
    'composite-repeated-layer': _operations(
        {'operation_type': 'composite', 'operation_id': 'stack', 'layer_ids': ['frame', 'frame']},
        ENCODE,
    ),
    'annotate-unknown-layer': _operations(
        {'operation_type': 'annotate', 'operation_id': 'note', 'layer_id': 'missing'},
        ENCODE,
    ),
    'last-operation-not-encode': _operations(
        ENCODE,
        {'operation_type': 'rotate', 'operation_id': 'turn', 'degrees': 180},
    ),
    'encode-mime-mismatch': _operations({**ENCODE, 'mime_type': 'image/jpeg'}),
    'canvas-over-platform-area': _with_body(
        {'canvas': {'width_pixels': 8000, 'height_pixels': 5001, 'color_space': 'srgb'}},
    ),
    'canvas-over-bound': _image_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_pixels': 9_999,
            'max_total_decoded_pixels': 40_000,
        },
    ),
    'pixel-bound-missing': _image_plan(
        resource_bounds={'max_output_bytes': 1, 'max_total_decoded_pixels': 40_000},
    ),
    'pixel-bound-over-platform': _image_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_pixels': MAX_IMAGE_PIXELS + 1,
            'max_total_decoded_pixels': 40_000,
        },
    ),
    'decoded-bound-missing': _image_plan(
        resource_bounds={'max_output_bytes': 1, 'max_pixels': 10_000},
    ),
    'decoded-bound-over-platform': _image_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_pixels': 10_000,
            'max_total_decoded_pixels': MAX_TOTAL_DECODED_PIXELS + 1,
        },
    ),
    'unused-input': _image_plan(
        input_refs=[
            {'local_id': 'photo', 'ref_type': 'artifact', 'artifact_id': 'art_0001', 'revision': 1},
            {'local_id': 'extra', 'ref_type': 'resource', 'resource_id': 'res_0001', 'revision': 1},
        ],
    ),
    'template-input': _image_plan(
        input_refs=[
            {'local_id': 'photo', 'ref_type': 'template', 'template_id': 'tpl_0001', 'revision': 1},
        ],
    ),
    'duplicate-input-authority': _image_plan(
        input_refs=[
            {'local_id': 'photo', 'ref_type': 'artifact', 'artifact_id': 'art_0001', 'revision': 1},
            {'local_id': 'photo', 'ref_type': 'artifact', 'artifact_id': 'art_0001', 'revision': 1},
        ],
    ),
    'input-id-collides-with-layer': _image_plan(
        input_refs=[
            {'local_id': 'frame', 'ref_type': 'artifact', 'artifact_id': 'art_0001', 'revision': 1},
        ],
    ),
}


@pytest.mark.parametrize('case', sorted(INVALID_IMAGE_PLANS))
def test_image_plan_refuses_broken_graphs_bounds_and_inputs(case: str) -> None:
    """References, the final encode, pixel bounds and input usage are all enforced."""
    with pytest.raises(ValidationError):
        ImageArtifactPlanV2.model_validate(INVALID_IMAGE_PLANS[case])


def test_image_plan_bounds_are_inclusive() -> None:
    """The canvas may fill its bound exactly; platform maxima are inclusive."""
    plan = _image_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_pixels': MAX_IMAGE_PIXELS,
            'max_total_decoded_pixels': MAX_TOTAL_DECODED_PIXELS,
        },
    )
    assert ImageArtifactPlanV2.model_validate(plan)
    exact = _image_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_pixels': 10_000,
            'max_total_decoded_pixels': 1,
        },
    )
    assert ImageArtifactPlanV2.model_validate(exact)


def _workbook_plan(**overrides: object) -> dict[str, Any]:
    plan = _envelope(
        'spreadsheet',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        {'max_sheets': 1, 'max_cells': 1},
    )
    plan['body'] = {
        'styles': [],
        'sheets': [
            {
                'sheet_id': 'sheet_1',
                'name': 'Sheet1',
                'cells': [
                    {
                        'cell_id': 'cell_1',
                        'row': 1,
                        'column': 1,
                        'value': {'value_type': 'boolean', 'value': True},
                    },
                ],
            },
        ],
        'ranges': [],
        'named_ranges': [],
        'tables': [],
        'charts': [],
    }
    plan.update(overrides)
    return plan


def _two_sheet_workbook() -> dict[str, Any]:
    plan = _workbook_plan()
    plan['body']['sheets'].append({'sheet_id': 'sheet_2', 'name': 'Sheet2', 'cells': []})
    return plan


def _template_workbook(input_refs: list[dict[str, Any]]) -> dict[str, Any]:
    plan = _workbook_plan(input_refs=input_refs)
    plan['body']['template_local_id'] = 'template_1'
    return plan


TEMPLATE = {'local_id': 'template_1', 'ref_type': 'template', 'template_id': 'tpl', 'revision': 1}


def test_workbook_plan_accepts_exact_bounds_and_an_optional_template() -> None:
    """Sheet and cell bounds may equal the body; a declared template is its only input."""
    assert WorkbookArtifactPlanV2.model_validate(_workbook_plan())
    assert WorkbookArtifactPlanV2.model_validate(_template_workbook([TEMPLATE]))


INVALID_WORKBOOK_PLANS: dict[str, dict[str, Any]] = {
    'sheets-bound-missing': _workbook_plan(resource_bounds={'max_output_bytes': 1, 'max_cells': 1}),
    'sheets-bound-over-platform': _workbook_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_sheets': MAX_WORKBOOK_SHEETS + 1,
            'max_cells': 1,
        },
    ),
    'sheets-under-body': _two_sheet_workbook(),
    'cells-bound-missing': _workbook_plan(resource_bounds={'max_output_bytes': 1, 'max_sheets': 1}),
    'cells-bound-over-platform': _workbook_plan(
        resource_bounds={
            'max_output_bytes': 1,
            'max_sheets': 1,
            'max_cells': MAX_WORKBOOK_CELLS + 1,
        },
    ),
    'cells-under-body': _workbook_plan(
        resource_bounds={'max_output_bytes': 1, 'max_sheets': 1, 'max_cells': 0},
    ),
    'input-without-template': _workbook_plan(input_refs=[TEMPLATE]),
    'template-without-input': _template_workbook([]),
    'template-is-an-artifact': _template_workbook(
        [{'local_id': 'template_1', 'ref_type': 'artifact', 'artifact_id': 'a', 'revision': 1}],
    ),
    'input-collides-with-structural-id': _template_workbook(
        [{**TEMPLATE, 'local_id': 'cell_1'}],
    ),
    'duplicate-input': _template_workbook([TEMPLATE, TEMPLATE]),
}


@pytest.mark.parametrize('case', sorted(INVALID_WORKBOOK_PLANS))
def test_workbook_plan_refuses_out_of_bound_bodies_and_stray_inputs(case: str) -> None:
    """Bounds are required and cover the body; the only input is the declared template."""
    with pytest.raises(ValidationError):
        WorkbookArtifactPlanV2.model_validate(INVALID_WORKBOOK_PLANS[case])


def test_document_plan_refuses_a_non_document_mime_type() -> None:
    """A document plan cannot declare an image output."""
    plan = _envelope('document', 'image/png', {'max_pages': 1})
    plan['body'] = {
        'page_settings': {
            'width_twips': 12_240,
            'height_twips': 15_840,
            'margin_top_twips': 1_440,
            'margin_right_twips': 1_440,
            'margin_bottom_twips': 1_440,
            'margin_left_twips': 1_440,
        },
        'styles': [
            {
                'style_id': 'body_style',
                'font_family': 'Noto Serif',
                'font_size_half_points': 22,
                'bold': False,
                'italic': False,
            },
        ],
        'headers': [],
        'footers': [],
        'footnotes': [],
        'blocks': [
            {
                'block_type': 'paragraph',
                'block_id': 'paragraph_1',
                'style_id': 'body_style',
                'runs': [
                    {
                        'run_id': 'run_1',
                        'payload': {'fragments': [{'structural_id': 'text_1', 'text': 'Hi.'}]},
                        'bold': False,
                        'italic': False,
                        'underline': False,
                    },
                ],
            },
        ],
    }
    with pytest.raises(ValidationError):
        DocumentArtifactPlanV2.model_validate(plan)
    plan['output_mime_type'] = 'application/pdf'
    assert DocumentArtifactPlanV2.model_validate(plan)
