# pyright: strict
"""Contract tests for closed v2 render plans and exact rework patches."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

import maivn_contracts.artifacts as artifact_contracts
from maivn_contracts.artifacts import validate_artifact_patch, validate_artifact_plan


def _minimal_document_plan() -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': 'document',
        'logical_output_name': 'report',
        'custody_request': 'ordinary',
        'body': {
            'template_local_id': 'template_1',
            'page_settings': {
                'width_twips': 12240,
                'height_twips': 15840,
                'margin_top_twips': 1440,
                'margin_right_twips': 1440,
                'margin_bottom_twips': 1440,
                'margin_left_twips': 1440,
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
            'footnotes': [
                {
                    'footnote_id': 'footnote_1',
                    'blocks': [
                        {
                            'block_type': 'paragraph',
                            'block_id': 'footnote_paragraph_1',
                            'style_id': 'body_style',
                            'runs': [
                                {
                                    'run_id': 'footnote_run_1',
                                    'payload': {
                                        'fragments': [
                                            {
                                                'structural_id': 'footnote_fragment_1',
                                                'text': 'Footnote text.',
                                            },
                                        ],
                                    },
                                    'bold': False,
                                    'italic': False,
                                    'underline': False,
                                },
                            ],
                        },
                    ],
                },
            ],
            'blocks': [
                {
                    'block_type': 'paragraph',
                    'block_id': 'paragraph_1',
                    'style_id': 'body_style',
                    'runs': [
                        {
                            'run_id': 'run_1',
                            'payload': {
                                'fragments': [
                                    {
                                        'structural_id': 'fragment_1',
                                        'text': 'Hello {_{customer_name}_}.',
                                    },
                                ],
                            },
                            'bold': False,
                            'italic': False,
                            'underline': False,
                            'footnote_ids': ['footnote_1'],
                        },
                    ],
                },
            ],
        },
        'input_refs': [
            {
                'local_id': 'template_1',
                'ref_type': 'template',
                'template_id': 'template_report',
                'revision': 3,
            },
        ],
        'renderer_profile': 'document_renderer',
        'renderer_min_version': '2.0',
        'output_mime_type': 'application/pdf',
        'validation_profile': 'document_default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {'max_output_bytes': 1024, 'max_pages': 1},
    }


def _paragraph(block_id: str, run_id: str, fragment_id: str, text: str) -> dict[str, Any]:
    return {
        'block_type': 'paragraph',
        'block_id': block_id,
        'style_id': 'body_style',
        'runs': [
            {
                'run_id': run_id,
                'payload': {'fragments': [{'structural_id': fragment_id, 'text': text}]},
                'bold': False,
                'italic': False,
                'underline': False,
            },
        ],
    }


def _minimal_workbook_plan(value: dict[str, Any]) -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': 'spreadsheet',
        'logical_output_name': 'workbook',
        'custody_request': 'ordinary',
        'body': {
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
                        {
                            'cell_id': 'cell_1',
                            'row': 1,
                            'column': 1,
                            'style_id': 'body_style',
                            'value': value,
                        },
                    ],
                },
            ],
            'ranges': [],
            'named_ranges': [],
            'tables': [],
            'charts': [],
        },
        'input_refs': [],
        'renderer_profile': 'workbook_renderer',
        'renderer_min_version': '2.0',
        'output_mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'validation_profile': 'workbook_default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {'max_output_bytes': 1024, 'max_sheets': 1, 'max_cells': 1},
    }


def _minimal_image_plan() -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': 'image',
        'logical_output_name': 'image',
        'custody_request': 'ordinary',
        'body': {
            'canvas': {'width_pixels': 10, 'height_pixels': 10, 'color_space': 'srgb'},
            'layers': [
                {
                    'layer_type': 'input_raster',
                    'layer_id': 'layer_1',
                    'input_local_id': 'input_1',
                    'x_pixels': 0,
                    'y_pixels': 0,
                    'width_pixels': 10,
                    'height_pixels': 10,
                    'opacity_per_mille': 1000,
                },
            ],
            'operations': [
                {
                    'operation_type': 'encode',
                    'operation_id': 'encode_1',
                    'mime_type': 'image/png',
                    'quality': 100,
                },
            ],
        },
        'input_refs': [
            {
                'local_id': 'input_1',
                'ref_type': 'artifact',
                'artifact_id': 'artifact_1',
                'revision': 1,
            },
        ],
        'renderer_profile': 'image_renderer',
        'renderer_min_version': '2.0',
        'output_mime_type': 'image/png',
        'validation_profile': 'image_default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {
            'max_output_bytes': 1024,
            'max_pixels': 100,
            'max_total_decoded_pixels': 200,
        },
    }


def test_v2_document_plan_roundtrips_closed_stable_structure() -> None:
    """Removing v2 admission would reject the stable document structure."""
    payload = _minimal_document_plan()

    projected = validate_artifact_plan(payload)

    assert projected.model_dump(mode='json', exclude_none=True) == payload


def test_v2_document_plan_has_an_explicit_public_projection() -> None:
    """Omitting the v2 class would force consumers to infer a union branch."""
    projected = validate_artifact_plan(_minimal_document_plan())

    assert isinstance(projected, artifact_contracts.DocumentArtifactPlanV2)


def test_v2_document_patch_has_an_explicit_exact_revision_projection() -> None:
    """V2 rework must remain typed, structural, and bound to one base revision."""
    payload = {
        'schema_version': 'v2',
        'target_artifact_id': 'artifact_report',
        'base_revision': 2,
        'source_manifest_digest': '0' * 64,
        'expected_output_kind': 'document',
        'renderer_profile': 'document_renderer',
        'rationale': {
            'fragments': [{'structural_id': 'reason_1', 'text': 'Correct the total.'}],
        },
        'operations': [
            {
                'op': 'replace_block',
                'target_id': 'paragraph_1',
                'block': _paragraph('paragraph_2', 'run_2', 'fragment_2', 'New total'),
            },
        ],
    }

    projected = validate_artifact_patch(payload)

    assert isinstance(projected, artifact_contracts.DocumentArtifactPatchV2)
    assert projected.model_dump(mode='json', exclude_none=True) == payload


def test_v2_image_plan_roundtrips_closed_layers_and_operations() -> None:
    """Image rendering must use typed layers and operations, not a free-form graph."""
    payload = {
        'schema_version': 'v2',
        'kind': 'image',
        'logical_output_name': 'social_card',
        'custody_request': 'ordinary',
        'body': {
            'canvas': {'width_pixels': 1200, 'height_pixels': 630, 'color_space': 'srgb'},
            'layers': [
                {
                    'layer_type': 'input_raster',
                    'layer_id': 'background_layer',
                    'input_local_id': 'background_input',
                    'x_pixels': 0,
                    'y_pixels': 0,
                    'width_pixels': 1200,
                    'height_pixels': 630,
                    'opacity_per_mille': 1000,
                },
                {
                    'layer_type': 'text',
                    'layer_id': 'title_layer',
                    'x_pixels': 40,
                    'y_pixels': 40,
                    'max_width_pixels': 1120,
                    'font_family': 'Noto Sans',
                    'font_size_pixels': 64,
                    'color_rgb_hex': 'FFFFFF',
                    'payload': {
                        'fragments': [{'structural_id': 'title_fragment', 'text': 'Hello'}],
                    },
                },
                {
                    'layer_type': 'shape',
                    'layer_id': 'border_layer',
                    'shape': 'rectangle',
                    'x_pixels': 10,
                    'y_pixels': 10,
                    'width_pixels': 1180,
                    'height_pixels': 610,
                    'fill_rgb_hex': '000000',
                    'opacity_per_mille': 0,
                    'stroke_rgb_hex': 'FFFFFF',
                    'stroke_width_pixels': 2,
                },
            ],
            'operations': [
                {
                    'operation_type': 'composite',
                    'operation_id': 'composite_1',
                    'layer_ids': ['background_layer', 'title_layer', 'border_layer'],
                },
                {
                    'operation_type': 'color_convert',
                    'operation_id': 'color_1',
                    'color_space': 'srgb',
                },
                {
                    'operation_type': 'encode',
                    'operation_id': 'encode_1',
                    'mime_type': 'image/png',
                    'quality': 100,
                },
            ],
        },
        'input_refs': [
            {
                'local_id': 'background_input',
                'ref_type': 'artifact',
                'artifact_id': 'artifact_background',
                'revision': 1,
            },
        ],
        'renderer_profile': 'image_renderer',
        'renderer_min_version': '2.0',
        'output_mime_type': 'image/png',
        'validation_profile': 'image_default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {
            'max_output_bytes': 1048576,
            'max_pixels': 40000000,
            'max_total_decoded_pixels': 160000000,
        },
    }

    projected = validate_artifact_plan(payload)

    assert isinstance(projected, artifact_contracts.ImageArtifactPlanV2)
    assert projected.model_dump(mode='json', exclude_none=True) == payload


def test_v2_image_plan_allows_a_shape_only_blank_canvas_without_fake_input() -> None:
    """First-party blank-canvas generation must not invent an immutable source authority."""
    payload = _minimal_image_plan()
    payload['body']['layers'] = [
        {
            'layer_type': 'shape',
            'layer_id': 'background_layer',
            'shape': 'rectangle',
            'x_pixels': 0,
            'y_pixels': 0,
            'width_pixels': 10,
            'height_pixels': 10,
            'fill_rgb_hex': '112233',
            'opacity_per_mille': 1000,
            'stroke_rgb_hex': '112233',
            'stroke_width_pixels': 0,
        }
    ]
    payload['body']['operations'] = [
        {
            'operation_type': 'composite',
            'operation_id': 'composite_1',
            'layer_ids': ['background_layer'],
        },
        payload['body']['operations'][-1],
    ]
    payload['input_refs'] = []

    projected = validate_artifact_plan(payload)

    assert isinstance(projected, artifact_contracts.ImageArtifactPlanV2)
    assert projected.input_refs == ()


def test_v2_workbook_plan_roundtrips_typed_cells_ranges_tables_and_charts() -> None:
    """Workbook formulas and presentation must remain a closed reference graph."""
    payload = {
        'schema_version': 'v2',
        'kind': 'spreadsheet',
        'logical_output_name': 'summary_workbook',
        'custody_request': 'ordinary',
        'body': {
            'template_local_id': 'template_1',
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
                    'name': 'Summary',
                    'cells': [
                        {
                            'cell_id': 'cell_a1',
                            'row': 1,
                            'column': 1,
                            'style_id': 'body_style',
                            'value': {
                                'value_type': 'text',
                                'payload': {
                                    'fragments': [
                                        {'structural_id': 'cell_a1_text', 'text': 'Category'},
                                    ],
                                },
                            },
                        },
                        {
                            'cell_id': 'cell_a2',
                            'row': 2,
                            'column': 1,
                            'style_id': 'body_style',
                            'value': {'value_type': 'number', 'value': 10},
                        },
                        {
                            'cell_id': 'cell_b1',
                            'row': 1,
                            'column': 2,
                            'style_id': 'body_style',
                            'value': {
                                'value_type': 'date',
                                'value': '2026-08-10',
                            },
                        },
                        {
                            'cell_id': 'cell_b2',
                            'row': 2,
                            'column': 2,
                            'style_id': 'body_style',
                            'value': {
                                'value_type': 'formula',
                                'expression': {
                                    'node_type': 'function',
                                    'function': 'SUM',
                                    'arguments': [
                                        {'node_type': 'range_ref', 'range_id': 'value_range'},
                                    ],
                                },
                            },
                        },
                    ],
                },
            ],
            'ranges': [
                {
                    'range_id': 'table_range',
                    'sheet_id': 'sheet_1',
                    'start_row': 1,
                    'end_row': 2,
                    'start_column': 1,
                    'end_column': 2,
                },
                {
                    'range_id': 'category_range',
                    'sheet_id': 'sheet_1',
                    'start_row': 1,
                    'end_row': 1,
                    'start_column': 1,
                    'end_column': 1,
                },
                {
                    'range_id': 'value_range',
                    'sheet_id': 'sheet_1',
                    'start_row': 2,
                    'end_row': 2,
                    'start_column': 1,
                    'end_column': 1,
                },
            ],
            'named_ranges': [{'named_range_id': 'named_value', 'range_id': 'value_range'}],
            'tables': [
                {'table_id': 'table_1', 'range_id': 'table_range', 'table_style': 'medium_2'},
            ],
            'charts': [
                {
                    'chart_id': 'chart_1',
                    'sheet_id': 'sheet_1',
                    'chart_type': 'bar',
                    'anchor_row': 1,
                    'anchor_column': 4,
                    'width_cells': 8,
                    'height_cells': 12,
                    'series': [
                        {
                            'series_id': 'series_1',
                            'category_range_id': 'category_range',
                            'value_range_id': 'value_range',
                        },
                    ],
                },
            ],
        },
        'input_refs': [
            {
                'local_id': 'template_1',
                'ref_type': 'template',
                'template_id': 'template_workbook',
                'revision': 1,
            },
        ],
        'renderer_profile': 'workbook_renderer',
        'renderer_min_version': '2.0',
        'output_mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'validation_profile': 'workbook_default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {
            'max_output_bytes': 1048576,
            'max_sheets': 100,
            'max_cells': 1000000,
        },
    }

    projected = validate_artifact_plan(payload)

    assert isinstance(projected, artifact_contracts.WorkbookArtifactPlanV2)
    assert projected.model_dump(mode='json', exclude_none=True) == payload


def test_v2_workbook_rejects_formula_cycles() -> None:
    """A stable cell-reference cycle cannot be rendered deterministically."""
    payload = _minimal_workbook_plan(
        {
            'value_type': 'formula',
            'expression': {'node_type': 'cell_ref', 'cell_id': 'cell_1'},
        },
    )

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_workbook_rejects_raw_formula_strings() -> None:
    """Raw formulas could encode external links, DDE, or volatile functions."""
    payload = _minimal_workbook_plan({'value_type': 'formula', 'expression': '=WEBSERVICE(A1)'})

    with pytest.raises(JsonSchemaValidationError):
        validate_artifact_plan(payload)


def test_v2_image_rejects_unknown_composite_layer() -> None:
    """A composite operation may consume only declared stable layers."""
    payload = _minimal_image_plan()
    payload['body']['operations'].insert(
        0,
        {
            'operation_type': 'composite',
            'operation_id': 'composite_1',
            'layer_ids': ['missing_layer'],
        },
    )

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_image_rejects_resource_bound_below_canvas() -> None:
    """The renderer may not admit a canvas larger than its requested pixel cap."""
    payload = _minimal_image_plan()
    payload['resource_bounds']['max_pixels'] = 99

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_audio_plan_is_not_representable_in_this_phase() -> None:
    """Audio remains transcript/redaction-only and has no v2 renderer body."""
    payload = _minimal_image_plan()
    payload['kind'] = 'audio'
    payload['output_mime_type'] = 'audio/mpeg'

    with pytest.raises(JsonSchemaValidationError):
        validate_artifact_plan(payload)


@pytest.mark.parametrize(
    ('expected_type', 'payload'),
    [
        (
            artifact_contracts.WorkbookArtifactPatchV2,
            {
                'schema_version': 'v2',
                'target_artifact_id': 'artifact_workbook',
                'base_revision': 1,
                'source_manifest_digest': '1' * 64,
                'expected_output_kind': 'spreadsheet',
                'renderer_profile': 'workbook_renderer',
                'rationale': {
                    'fragments': [{'structural_id': 'reason_1', 'text': 'Remove row.'}],
                },
                'operations': [{'op': 'remove_cells', 'cell_ids': ['cell_1']}],
            },
        ),
        (
            artifact_contracts.ImageArtifactPatchV2,
            {
                'schema_version': 'v2',
                'target_artifact_id': 'artifact_image',
                'base_revision': 1,
                'source_manifest_digest': '2' * 64,
                'expected_output_kind': 'image',
                'renderer_profile': 'image_renderer',
                'rationale': {
                    'fragments': [{'structural_id': 'reason_1', 'text': 'Remove layer.'}],
                },
                'operations': [{'op': 'remove_layer', 'target_id': 'layer_1'}],
            },
        ),
    ],
)
def test_v2_kind_specific_patch_unions_roundtrip(
    expected_type: type[object],
    payload: dict[str, Any],
) -> None:
    """Each renderer accepts only its own closed structural patch operations."""
    projected = validate_artifact_patch(payload)

    assert isinstance(projected, expected_type)
    assert projected.model_dump(mode='json', exclude_none=True) == payload


def test_v2_document_plan_rejects_duplicate_structural_ids() -> None:
    """Allowing duplicate IDs would make an exact patch target ambiguous."""
    payload = _minimal_document_plan()
    duplicate = deepcopy(payload['body']['blocks'][0])
    payload['body']['blocks'].append(duplicate)

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_duplicate_input_local_ids() -> None:
    """Duplicate input names would let a renderer resolve one image ambiguously."""
    payload = _minimal_document_plan()
    payload['input_refs'].append(
        {
            'local_id': 'template_1',
            'ref_type': 'resource',
            'resource_id': 'resource_logo',
            'revision': 2,
        },
    )

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_requires_a_positive_printable_page_area() -> None:
    """Margins consuming the page would make native layout undefined."""
    payload = _minimal_document_plan()
    payload['body']['page_settings']['margin_left_twips'] = 6120
    payload['body']['page_settings']['margin_right_twips'] = 6120

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


@pytest.mark.parametrize('template_local_id', [None, 'missing_template'])
def test_v2_document_plan_requires_declared_inputs_to_equal_used_inputs(
    template_local_id: str | None,
) -> None:
    """Unknown or unused inputs would make source capture nondeterministic."""
    payload = _minimal_document_plan()
    if template_local_id is None:
        payload['body'].pop('template_local_id')
    else:
        payload['body']['template_local_id'] = template_local_id

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_template_reference_requires_a_template_input() -> None:
    """Treating a resource as a template would bypass source-type authority."""
    payload = _minimal_document_plan()
    payload['input_refs'] = [
        {
            'local_id': 'template_1',
            'ref_type': 'resource',
            'resource_id': 'resource_report',
            'revision': 3,
        },
    ]

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_an_unknown_style_target() -> None:
    """An unresolved style ID would make renderer fallback nondeterministic."""
    payload = _minimal_document_plan()
    payload['body']['blocks'][0]['style_id'] = 'missing_style'

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


@pytest.mark.parametrize('footnote_ids', [None, ['missing_footnote']])
def test_v2_document_plan_requires_declared_footnotes_to_equal_references(
    footnote_ids: list[str] | None,
) -> None:
    """Unknown or inert footnotes would break exact normalized structure."""
    payload = _minimal_document_plan()
    run = payload['body']['blocks'][0]['runs'][0]
    if footnote_ids is None:
        run.pop('footnote_ids')
    else:
        run['footnote_ids'] = footnote_ids

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_duplicate_footnote_references() -> None:
    """A footnote marker must identify one deterministic insertion point."""
    payload = _minimal_document_plan()
    payload['body']['blocks'][0]['runs'][0]['footnote_ids'] = ['footnote_1', 'footnote_1']

    with pytest.raises(JsonSchemaValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_unused_named_styles() -> None:
    """Declared styles must affect the normalized document rather than be inert."""
    payload = _minimal_document_plan()
    payload['body']['blocks'][0].pop('style_id')
    payload['body']['footnotes'][0]['blocks'][0].pop('style_id')

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_header_has_a_closed_rendering_slot() -> None:
    """A header without a slot cannot map deterministically to document pages."""
    payload = _minimal_document_plan()
    payload['body']['headers'] = [
        {
            'region_id': 'header_1',
            'slot': 'default',
            'blocks': [
                {
                    'block_type': 'paragraph',
                    'block_id': 'header_paragraph_1',
                    'style_id': 'body_style',
                    'runs': [
                        {
                            'run_id': 'header_run_1',
                            'payload': {
                                'fragments': [
                                    {'structural_id': 'header_fragment_1', 'text': 'Header'},
                                ],
                            },
                            'bold': False,
                            'italic': False,
                            'underline': False,
                        },
                    ],
                },
            ],
        },
    ]

    assert validate_artifact_plan(payload).model_dump(mode='json', exclude_none=True) == payload


def test_v2_document_image_reference_requires_artifact_or_resource_input() -> None:
    """Treating a renderer template as image bytes would bypass source typing."""
    payload = _minimal_document_plan()
    payload['input_refs'].append(
        {
            'local_id': 'image_1',
            'ref_type': 'template',
            'template_id': 'template_image',
            'revision': 1,
        },
    )
    payload['body']['blocks'].append(
        {
            'block_type': 'image',
            'block_id': 'image_block_1',
            'input_local_id': 'image_1',
            'width_twips': 1440,
            'height_twips': 1440,
            'alignment': 'left',
            'crop_left_per_mille': 0,
            'crop_top_per_mille': 0,
            'crop_right_per_mille': 0,
            'crop_bottom_per_mille': 0,
            'alt_text': {
                'fragments': [
                    {'structural_id': 'image_alt_fragment_1', 'text': 'Image'},
                ],
            },
        },
    )

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_uses_one_global_structural_id_namespace() -> None:
    """An input alias colliding with a block ID would make manifests ambiguous."""
    payload = _minimal_document_plan()
    payload['input_refs'][0]['local_id'] = 'paragraph_1'
    payload['body']['template_local_id'] = 'paragraph_1'

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_duplicate_immutable_authority_aliases() -> None:
    """Two aliases for one immutable input would make provenance ambiguous."""
    payload = _minimal_document_plan()
    image: dict[str, Any] = {
        'block_type': 'image',
        'block_id': 'image_block_1',
        'input_local_id': 'image_1',
        'width_twips': 1440,
        'height_twips': 1440,
        'alignment': 'left',
        'crop_left_per_mille': 0,
        'crop_top_per_mille': 0,
        'crop_right_per_mille': 0,
        'crop_bottom_per_mille': 0,
        'alt_text': {'fragments': [{'structural_id': 'image_alt_1', 'text': 'Image one'}]},
    }
    second_image: dict[str, Any] = deepcopy(image)
    second_image['block_id'] = 'image_block_2'
    second_image['input_local_id'] = 'image_2'
    second_image['alt_text']['fragments'][0] = {
        'structural_id': 'image_alt_2',
        'text': 'Image two',
    }
    payload['body']['blocks'].extend((image, second_image))
    payload['input_refs'].extend(
        (
            {
                'local_id': 'image_1',
                'ref_type': 'artifact',
                'artifact_id': 'artifact_source',
                'revision': 1,
            },
            {
                'local_id': 'image_2',
                'ref_type': 'artifact',
                'artifact_id': 'artifact_source',
                'revision': 1,
            },
        ),
    )

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_duplicate_header_slots() -> None:
    """Two default headers would make page assignment ambiguous."""
    payload = _minimal_document_plan()
    first: dict[str, Any] = {
        'region_id': 'header_1',
        'slot': 'default',
        'blocks': [],
    }
    second: dict[str, Any] = {
        'region_id': 'header_2',
        'slot': 'default',
        'blocks': [],
    }
    payload['body']['headers'] = [first, second]

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_more_than_four_mib_of_redacted_text() -> None:
    """Aggregate text must be bounded before normalization or native rendering."""
    payload = _minimal_document_plan()
    payload['body']['blocks'][0]['runs'][0]['payload']['fragments'] = [
        {'structural_id': f'fragment_{index}', 'text': 'x' * 16384} for index in range(257)
    ]

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_rejects_more_than_ten_thousand_runs() -> None:
    """Per-block bounds must not multiply into an unsafe aggregate plan."""
    payload = _minimal_document_plan()
    full_blocks = 10
    payload['body']['blocks'] = [
        {
            'block_type': 'paragraph',
            'block_id': f'paragraph_{block_index}',
            'style_id': 'body_style',
            'runs': [
                {
                    'run_id': f'run_{block_index}_{run_index}',
                    'payload': {
                        'fragments': [
                            {
                                'structural_id': f'fragment_{block_index}_{run_index}',
                                'text': 'x',
                            },
                        ],
                    },
                    'bold': False,
                    'italic': False,
                    'underline': False,
                    **(
                        {'footnote_ids': ['footnote_1']}
                        if block_index == 0 and run_index == 0
                        else {}
                    ),
                }
                for run_index in range(1000 if block_index < full_blocks else 1)
            ],
        }
        for block_index in range(11)
    ]

    with pytest.raises(PydanticValidationError):
        validate_artifact_plan(payload)


def test_v2_document_plan_roundtrips_every_closed_flow_block() -> None:
    """Dropping a block branch would make an approved document plan undecodable."""
    payload = _minimal_document_plan()
    payload['input_refs'].append(
        {
            'local_id': 'image_1',
            'ref_type': 'resource',
            'resource_id': 'resource_logo',
            'revision': 2,
        },
    )
    payload['body']['blocks'].extend(
        [
            {
                'block_type': 'heading',
                'block_id': 'heading_1',
                'level': 2,
                'style_id': 'body_style',
                'runs': [
                    {
                        'run_id': 'heading_run_1',
                        'payload': {
                            'fragments': [
                                {'structural_id': 'heading_fragment_1', 'text': 'Summary'},
                            ],
                        },
                        'bold': True,
                        'italic': False,
                        'underline': False,
                    },
                ],
            },
            {
                'block_type': 'ordered_list',
                'block_id': 'ordered_list_1',
                'start_at': 1,
                'items': [
                    {
                        'item_id': 'ordered_item_1',
                        'blocks': [
                            _paragraph(
                                'ordered_paragraph_1',
                                'ordered_run_1',
                                'ordered_fragment_1',
                                'First item',
                            ),
                        ],
                    },
                ],
            },
            {
                'block_type': 'unordered_list',
                'block_id': 'unordered_list_1',
                'marker': 'disc',
                'items': [
                    {
                        'item_id': 'unordered_item_1',
                        'blocks': [
                            _paragraph(
                                'unordered_paragraph_1',
                                'unordered_run_1',
                                'unordered_fragment_1',
                                'Bullet item',
                            ),
                        ],
                    },
                ],
            },
            {
                'block_type': 'table',
                'block_id': 'table_1',
                'column_count': 1,
                'rows': [
                    {
                        'row_id': 'table_row_1',
                        'is_header': False,
                        'cells': [
                            {
                                'cell_id': 'table_cell_1',
                                'blocks': [
                                    _paragraph(
                                        'table_paragraph_1',
                                        'table_run_1',
                                        'table_fragment_1',
                                        'Cell value',
                                    ),
                                ],
                            },
                        ],
                    },
                ],
            },
            {
                'block_type': 'image',
                'block_id': 'image_block_1',
                'input_local_id': 'image_1',
                'width_twips': 2880,
                'height_twips': 1440,
                'alignment': 'center',
                'crop_left_per_mille': 0,
                'crop_top_per_mille': 0,
                'crop_right_per_mille': 0,
                'crop_bottom_per_mille': 0,
                'alt_text': {
                    'fragments': [
                        {'structural_id': 'image_alt_fragment_1', 'text': 'Company logo'},
                    ],
                },
            },
            {'block_type': 'page_break', 'block_id': 'page_break_1'},
        ],
    )

    assert validate_artifact_plan(payload).model_dump(mode='json', exclude_none=True) == payload
