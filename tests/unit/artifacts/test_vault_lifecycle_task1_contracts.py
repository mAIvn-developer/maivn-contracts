"""Release 2 six-format Vault create and full-replacement rework contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter, ValidationError
from referencing import Registry, Resource

from maivn_contracts import artifacts

_DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
_PDF = 'application/pdf'
_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
_PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
_FORMAT = {
    'docx': ('document', _DOCX),
    'pdf': ('document', _PDF),
    'xlsx': ('spreadsheet', _XLSX),
    'pptx': ('presentation', _PPTX),
    'png': ('image', 'image/png'),
    'jpeg': ('image', 'image/jpeg'),
}
_PROFILE = {
    ('v2', 'docx'): ('document-v1', '1.0.0', 'document-validator-v1'),
    ('v2', 'pdf'): ('document-pdf-v1', '1.0.0', 'document-pdf-validator-v1'),
    ('v2', 'xlsx'): ('workbook-v1', '1.0.0', 'workbook-validator-v1'),
    ('v2', 'png'): ('image-v1', '1.0.0', 'image-validator-v1'),
    ('v2', 'jpeg'): ('image-v1', '1.0.0', 'image-validator-v1'),
    ('v3', 'docx'): ('rich_document_v3', '3.0.0', 'rich_document_validator_v3'),
    ('v3', 'pdf'): ('rich_document_pdf_v3', '3.0.0', 'rich_document_pdf_validator_v3'),
    ('v3', 'xlsx'): ('rich_workbook_v3', '3.0.0', 'rich_workbook_validator_v3'),
    ('v3', 'pptx'): ('rich_presentation_v3', '3.0.0', 'rich_presentation_validator_v3'),
    ('v3', 'png'): ('rich_image_v3', '3.0.0', 'rich_image_validator_v3'),
    ('v3', 'jpeg'): ('rich_image_v3', '3.0.0', 'rich_image_validator_v3'),
}
_PLAN_CASES = tuple(_PROFILE)


def _value_map_handle() -> dict[str, str]:
    return {
        'record_handle': 'value_map_record_0001',
        'generation_handle': 'value_map_generation_0001',
    }


def _bounds(source_format: str) -> dict[str, int]:
    if source_format in {'docx', 'pdf', 'pptx'}:
        return {'max_output_bytes': 1_000_000, 'max_pages': 10}
    if source_format == 'xlsx':
        return {'max_output_bytes': 1_000_000, 'max_sheets': 2, 'max_cells': 100}
    return {
        'max_output_bytes': 1_000_000,
        'max_pixels': 10_000,
        'max_total_decoded_pixels': 40_000,
    }


def _v2_document_body() -> dict[str, Any]:
    return {
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
                        'payload': {
                            'fragments': [{'structural_id': 'fragment_1', 'text': 'Safe text.'}],
                        },
                        'bold': False,
                        'italic': False,
                        'underline': False,
                    },
                ],
            },
        ],
    }


def _v2_workbook_body() -> dict[str, Any]:
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
                    {
                        'cell_id': 'cell_1',
                        'row': 1,
                        'column': 1,
                        'style_id': 'body_style',
                        'value': {
                            'value_type': 'text',
                            'payload': {
                                'fragments': [
                                    {'structural_id': 'cell_text_1', 'text': 'Safe text.'},
                                ],
                            },
                        },
                    },
                ],
            },
        ],
        'ranges': [],
        'named_ranges': [],
        'tables': [],
        'charts': [],
    }


def _v2_image_body(source_format: str) -> dict[str, Any]:
    return {
        'canvas': {'width_pixels': 100, 'height_pixels': 100, 'color_space': 'srgb'},
        'layers': [
            {
                'layer_type': 'shape',
                'layer_id': 'background_1',
                'shape': 'rectangle',
                'x_pixels': 0,
                'y_pixels': 0,
                'width_pixels': 100,
                'height_pixels': 100,
                'fill_rgb_hex': 'FFFFFF',
                'opacity_per_mille': 1000,
                'stroke_rgb_hex': '000000',
                'stroke_width_pixels': 0,
            },
        ],
        'operations': [
            {
                'operation_type': 'encode',
                'operation_id': 'encode_1',
                'mime_type': _FORMAT[source_format][1],
                'quality': 90,
            },
        ],
    }


def _rich_text() -> dict[str, Any]:
    return {
        'paragraphs': [
            {
                'paragraph_id': 'paragraph_1',
                'runs': [{'text': 'Safe text.'}],
                'alignment': 'left',
            },
        ],
    }


def _v3_document_body(source_format: str) -> dict[str, Any]:
    return {
        'theme': {
            'primary': '#17324D',
            'secondary': '#35C4B5',
            'accent': '#F4B942',
            'background': '#FFFFFF',
            'heading_font': 'Aptos',
            'body_font': 'Aptos',
        },
        'page': {
            'width_points': 612.0,
            'height_points': 792.0,
            'margins': {'top': 54.0, 'right': 54.0, 'bottom': 54.0, 'left': 54.0},
            'orientation': 'portrait',
            'columns': 1,
        },
        'styles': [
            {
                'style_id': 'body_style',
                'font': {
                    'family': 'Aptos',
                    'size_points': 11.0,
                    'weight': 400,
                    'italic': False,
                    'color': '#17324D',
                },
                'alignment': 'left',
                'space_before_points': 0.0,
                'space_after_points': 0.0,
                'line_spacing': 1.0,
            },
        ],
        'headers': [],
        'footers': [],
        'notes': [],
        'blocks': [
            {
                'block_type': 'text',
                'block_id': 'body_1',
                'content': _rich_text(),
            },
        ],
        'sections': [],
        'accessibility': {
            'title': 'Safe document',
            'description': 'Safe document description.',
            'language': 'en-US',
        },
        'pdf': (
            {
                'tagged': True,
                'pdfa': '2b',
                'allow_actions': False,
                'include_bookmarks': True,
            }
            if source_format == 'pdf'
            else None
        ),
    }


def _v3_workbook_body() -> dict[str, Any]:
    return {
        'theme': {
            'primary': '#17324D',
            'secondary': '#35C4B5',
            'accent': '#F4B942',
            'font_family': 'Aptos',
        },
        'defined_names': [],
        'sheets': [
            {
                'sheet_id': 'sheet_1',
                'name': 'Sheet1',
                'visibility': 'visible',
                'cells': [],
                'column_widths': [],
                'row_heights': [],
                'merges': [],
                'groups': [],
                'freeze_panes': None,
                'auto_filter': None,
                'tables': [],
                'validations': [],
                'conditional_formats': [],
                'charts': [],
                'images': [],
                'notes': [],
                'print_setup': {
                    'orientation': 'portrait',
                    'paper_size': 'letter',
                    'fit_to_width': 1,
                    'fit_to_height': 1,
                    'print_area': 'A1:A1',
                    'repeat_rows': None,
                },
            },
        ],
        'calculation_mode': 'auto',
        'strip_metadata': True,
    }


def _v3_presentation_body() -> dict[str, Any]:
    return {
        'theme': {
            'primary': '#17324D',
            'secondary': '#35C4B5',
            'accent': '#F4B942',
            'background': '#FFFFFF',
            'heading_font': 'Aptos',
            'body_font': 'Aptos',
        },
        'slide_size': {'preset': 'wide', 'width_points': None, 'height_points': None},
        'layouts': [{'layout_id': 'content', 'name': 'Content', 'background': '#FFFFFF'}],
        'sections': [],
        'slides': [
            {
                'slide_id': 'slide_1',
                'layout_id': 'content',
                'section_id': None,
                'title': 'Safe slide',
                'hidden': False,
                'elements': [],
                'speaker_notes': None,
                'show_slide_number': True,
                'footer': None,
                'transition': 'none',
            },
        ],
        'accessibility': {
            'title': 'Safe deck',
            'description': 'Safe deck description.',
            'language': 'en-US',
        },
        'allow_animations': False,
        'allow_embedded_media': False,
        'allow_macros': False,
        'allow_ole': False,
    }


def _v3_image_body(source_format: str) -> dict[str, Any]:
    is_png = source_format == 'png'
    return {
        'canvas': {
            'width_pixels': 100,
            'height_pixels': 100,
            'background': '#FFFFFF',
            'color_space': 'srgb',
        },
        'layers': [
            {
                'layer_id': 'background_1',
                'opacity': 1.0,
                'blend_mode': 'normal',
                'mask_input_local_id': None,
                'layer_type': 'shape',
                'shape': 'rectangle',
                'x': 0,
                'y': 0,
                'width': 100,
                'height': 100,
                'fill': '#FFFFFF',
                'stroke': '#000000',
                'stroke_width': 0,
                'points': [],
            },
        ],
        'output': {
            'format': source_format,
            'transparent': is_png,
            'jpeg_quality': None if is_png else 90,
            'jpeg_progressive': None if is_png else True,
            'jpeg_subsampling': None if is_png else '4:4:4',
            'background': None if is_png else '#FFFFFF',
            'strip_metadata': True,
        },
    }


def _plan(version: str, source_format: str) -> dict[str, Any]:
    kind, mime = _FORMAT[source_format]
    renderer, renderer_version, validator = _PROFILE[(version, source_format)]
    if version == 'v2':
        if kind == 'document':
            body = _v2_document_body()
        elif kind == 'spreadsheet':
            body = _v2_workbook_body()
        else:
            body = _v2_image_body(source_format)
    elif kind == 'document':
        body = _v3_document_body(source_format)
    elif kind == 'spreadsheet':
        body = _v3_workbook_body()
    elif kind == 'presentation':
        body = _v3_presentation_body()
    else:
        body = _v3_image_body(source_format)

    return {
        'schema_version': version,
        'kind': kind,
        'logical_output_name': f'private_{source_format}',
        'custody_request': 'vault_private',
        'body': body,
        'input_refs': [],
        'renderer_profile': renderer,
        'renderer_min_version': renderer_version,
        'output_mime_type': mime,
        'validation_profile': validator,
        'disposition': 'final',
        'retention_request': {'retention_class': 'vault_private_30d'},
        'resource_bounds': _bounds(source_format),
    }


def _request(operation: str) -> dict[str, Any]:
    return {
        'schema_version': 'vault-work-v1',
        'intent_id': 'intent_0001',
        'idempotency_key': 'idempotency_0001',
        'operation': operation,
        'scope': {'organization_id': 'organization_0001', 'project_id': 'project_0001'},
        'surface': {
            'root_invocation_id': 'invocation_0001',
            'session_id': 'session_0001',
            'checkpoint_id': 'checkpoint_0001',
            'caller_id': 'caller_0001',
        },
        'input_handles': [],
        'bounds': {'max_output_bytes': 1},
        'retention_policy_id': 'retention_policy_0001',
        'expires_at': '2026-08-14T12:00:00Z',
    }


def _create(version: str, source_format: str) -> dict[str, Any]:
    request = _request('create')
    request['value_map_handle'] = _value_map_handle()
    request['plan'] = _plan(version, source_format)
    request['bounds'] = _bounds(source_format)
    return request


def _rework(version: str, source_format: str) -> dict[str, Any]:
    request = _request('rework')
    request['value_map_handle'] = _value_map_handle()
    request['input_handles'] = [
        {
            'local_id': 'source_1',
            'record_handle': 'record_0001',
            'generation_handle': 'generation_0007',
            'role': 'source_artifact',
        },
    ]
    replacement = _plan(version, source_format)
    kind, mime = _FORMAT[source_format]
    request['patch'] = {
        'source_format': source_format,
        'source_generation_handle': 'generation_0007',
        'base_revision': 2,
        'source_manifest_digest': 'b' * 64,
        'source_kind': kind,
        'source_mime_type': mime,
        'source_resource_bounds': _bounds(source_format),
        'replacement_plan': replacement,
    }
    request['bounds'] = _bounds(source_format)
    return request


def _assert_request_refused(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        artifacts.VaultWorkRequest.model_validate(payload)
    with pytest.raises((ValidationError, JsonSchemaValidationError)):
        artifacts.validate_vault_work_request(payload)


def _assert_stored_full_replacement_schema_refused(patch: dict[str, Any]) -> None:
    schemas = (
        artifacts.load_artifact_patch_schema(),
        artifacts.load_artifact_plan_schema(),
        artifacts.load_artifact_plan_v3_schema(),
        artifacts.load_redacted_artifact_payload_schema(),
    )
    registry = Registry[Any]().with_resources(
        (cast('str', schema['$id']), Resource[Any].from_contents(schema)) for schema in schemas
    )
    schema = {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$ref': (
            'https://schemas.maivn.dev/artifacts/artifact_patch.schema.json'
            '#/$defs/vaultFullReplacementArtifactPatch'
        ),
    }
    with pytest.raises(JsonSchemaValidationError):
        cast('Any', Draft202012Validator(schema, registry=registry)).validate(patch)


def _validate_stored_vault_work_schema(payload: dict[str, Any]) -> None:
    schemas = (
        artifacts.load_vault_work_request_schema(),
        artifacts.load_vault_value_map_handle_schema(),
        artifacts.load_artifact_patch_schema(),
        artifacts.load_artifact_plan_schema(),
        artifacts.load_artifact_plan_v3_schema(),
        artifacts.load_redacted_artifact_payload_schema(),
    )
    registry = Registry[Any]().with_resources(
        (cast('str', schema['$id']), Resource[Any].from_contents(schema)) for schema in schemas
    )
    cast('Any', Draft202012Validator(schemas[0], registry=registry)).validate(payload)


def test_vault_value_map_handle_is_closed_public_and_distinct() -> None:
    """Removing either identity or distinctness makes value-map resolution ambiguous."""
    payload = _value_map_handle()

    direct = artifacts.VaultValueMapHandle.model_validate(payload)
    loaded = artifacts.validate_vault_value_map_handle(payload)
    schema = artifacts.load_vault_value_map_handle_schema()

    assert loaded == direct
    assert schema['$id'] == 'https://schemas.maivn.dev/artifacts/vault_value_map_handle.schema.json'
    assert set(schema['required']) == {'record_handle', 'generation_handle'}
    assert schema['additionalProperties'] is False

    for invalid in (
        {'record_handle': 'same_handle', 'generation_handle': 'same_handle'},
        {'record_handle': 'value_map_record_0001'},
        {**payload, 'record_namespace': 'legacy'},
        {**payload, 'capability': 'secret'},
    ):
        with pytest.raises(ValidationError):
            artifacts.VaultValueMapHandle.model_validate(invalid)
        with pytest.raises((ValidationError, JsonSchemaValidationError)):
            artifacts.validate_vault_value_map_handle(invalid)


@pytest.mark.parametrize('operation', ['create', 'rework'])
def test_vault_writes_require_one_value_map_handle(operation: str) -> None:
    """Omitting or multiplying value-map authority must refuse a Vault write."""
    payload = _create('v2', 'docx') if operation == 'create' else _rework('v2', 'docx')
    _validate_stored_vault_work_schema(payload)

    missing = deepcopy(payload)
    missing.pop('value_map_handle')
    _assert_request_refused(missing)
    with pytest.raises(JsonSchemaValidationError):
        _validate_stored_vault_work_schema(missing)

    multiple = deepcopy(payload)
    multiple['value_map_handle'] = [_value_map_handle(), _value_map_handle()]
    _assert_request_refused(multiple)


@pytest.mark.parametrize('operation', ['retrieve_session', 'redacted_export', 'delete'])
def test_nonwrite_vault_operations_forbid_value_map_handle(operation: str) -> None:
    """Read/export/delete operations cannot acquire write-only value-map authority."""
    payload = _request(operation)
    payload['input_handles'] = [
        {
            'local_id': 'source_1',
            'record_handle': 'record_0001',
            'generation_handle': 'generation_0007',
            'role': 'source_artifact',
        },
    ]
    if operation == 'retrieve_session':
        payload['client_proof_digest'] = 'a' * 64
    elif operation == 'redacted_export':
        payload['export_filename'] = 'safe-export.pdf'
    else:
        payload['deletion_scope'] = {'mode': 'include_redacted_exports'}
    assert artifacts.validate_vault_work_request(payload).operation == operation

    payload['value_map_handle'] = _value_map_handle()
    _assert_request_refused(payload)
    with pytest.raises(JsonSchemaValidationError):
        _validate_stored_vault_work_schema(payload)


@pytest.mark.parametrize(
    ('value_map_field', 'input_field'),
    [
        ('record_handle', 'local_id'),
        ('record_handle', 'record_handle'),
        ('record_handle', 'generation_handle'),
        ('generation_handle', 'local_id'),
        ('generation_handle', 'record_handle'),
        ('generation_handle', 'generation_handle'),
    ],
)
def test_value_map_handles_cannot_alias_any_input_handle_identity(
    value_map_field: str,
    input_field: str,
) -> None:
    """An input handle can never be mistaken for the separate value-map generation."""
    payload = _rework('v3', 'docx')
    value_map = cast('dict[str, str]', payload['value_map_handle'])
    input_handle = cast('list[dict[str, str]]', payload['input_handles'])[0]
    value_map[value_map_field] = input_handle[input_field]

    _assert_request_refused(payload)


@pytest.mark.parametrize(('version', 'source_format'), _PLAN_CASES)
def test_vault_create_accepts_every_established_v2_v3_format(
    version: str,
    source_format: str,
) -> None:
    """Removing a format branch makes its canonical create request fail."""
    payload = _create(version, source_format)

    direct = artifacts.VaultWorkRequest.model_validate(payload)
    loaded = artifacts.validate_vault_work_request(payload)

    assert direct.plan is not None
    assert loaded.plan is not None
    assert direct.plan.output_mime_type == _FORMAT[source_format][1]
    assert loaded.model_dump(mode='json', exclude_none=True) == direct.model_dump(
        mode='json', exclude_none=True
    )


@pytest.mark.parametrize(('version', 'source_format'), _PLAN_CASES)
def test_vault_rework_accepts_every_established_full_replacement(
    version: str,
    source_format: str,
) -> None:
    """Replacing full-replacement semantics with legacy operations breaks rework."""
    payload = _rework(version, source_format)

    direct = artifacts.VaultWorkRequest.model_validate(payload)
    loaded = artifacts.validate_vault_work_request(payload)

    assert direct.patch is not None
    assert direct.patch.source_format == source_format
    assert loaded.model_dump(mode='json', exclude_none=True) == direct.model_dump(
        mode='json', exclude_none=True
    )


@pytest.mark.parametrize(
    ('source_version', 'source_format', 'replacement_version', 'replacement_format'),
    [
        ('v2', 'docx', 'v2', 'pdf'),
        ('v3', 'pdf', 'v3', 'docx'),
        ('v2', 'xlsx', 'v2', 'docx'),
        ('v3', 'pptx', 'v3', 'xlsx'),
        ('v2', 'png', 'v2', 'jpeg'),
        ('v3', 'jpeg', 'v3', 'png'),
    ],
)
def test_stored_full_replacement_schema_refuses_every_format_conversion(
    source_version: str,
    source_format: str,
    replacement_version: str,
    replacement_format: str,
) -> None:
    """Stored cross-language authority must narrow every patch to one exact MIME."""
    payload = _rework(source_version, source_format)
    patch = cast('dict[str, Any]', payload['patch'])
    patch['replacement_plan'] = _plan(replacement_version, replacement_format)

    _assert_stored_full_replacement_schema_refused(patch)


@pytest.mark.parametrize(('version', 'source_format'), _PLAN_CASES)
def test_stored_vault_work_schema_closes_every_format_profile_branch(
    version: str,
    source_format: str,
) -> None:
    """Every stored plan branch accepts only its real renderer/validator tuple."""
    payload = _create(version, source_format)
    _validate_stored_vault_work_schema(payload)

    for field, value in (
        ('renderer_profile', 'unknown-renderer'),
        ('renderer_min_version', '99.0.0'),
        ('validation_profile', 'unknown-validator'),
    ):
        invalid = deepcopy(payload)
        cast('dict[str, Any]', invalid['plan'])[field] = value
        with pytest.raises(JsonSchemaValidationError):
            _validate_stored_vault_work_schema(invalid)


@pytest.mark.parametrize(
    ('source_format', 'wrong_mime'),
    [('png', 'image/jpeg'), ('jpeg', 'image/png')],
)
def test_stored_v2_image_plan_closes_final_encoder_mime(
    source_format: str,
    wrong_mime: str,
) -> None:
    """A V2 Vault image branch cannot encode the other image format."""
    payload = _create('v2', source_format)
    plan = cast('dict[str, Any]', payload['plan'])
    body = cast('dict[str, Any]', plan['body'])
    operations = cast('list[dict[str, Any]]', body['operations'])
    operations[-1]['mime_type'] = wrong_mime

    with pytest.raises(JsonSchemaValidationError):
        _validate_stored_vault_work_schema(payload)


@pytest.mark.parametrize(
    ('source_format', 'wrong_format'),
    [('png', 'jpeg'), ('jpeg', 'png')],
)
def test_stored_v3_image_plan_closes_body_output_format(
    source_format: str,
    wrong_format: str,
) -> None:
    """A V3 Vault image branch cannot select the other image body format."""
    payload = _create('v3', source_format)
    plan = cast('dict[str, Any]', payload['plan'])
    body = cast('dict[str, Any]', plan['body'])
    output = cast('dict[str, Any]', body['output'])
    output['format'] = wrong_format

    with pytest.raises(JsonSchemaValidationError):
        _validate_stored_vault_work_schema(payload)


def test_stored_v3_schema_is_public_and_matches_pydantic_authority() -> None:
    """A stale or synthesized-at-load V3 schema fails deterministic parity."""
    expected = {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': 'https://schemas.maivn.dev/artifacts/artifact_plan_v3.schema.json',
        **TypeAdapter(artifacts.ArtifactPlanV3).json_schema(mode='validation'),
    }

    assert artifacts.load_artifact_plan_v3_schema() == expected
    assert 'VaultArtifactPlan' in artifacts.__all__
    assert 'VaultFullReplacementArtifactPatch' in artifacts.__all__


def test_v3_custody_is_expressive_but_ordinary_loader_remains_ordinary() -> None:
    """Widening metadata must not let private plans through ordinary admission."""
    private = _plan('v3', 'pptx')
    assert (
        artifacts.PresentationArtifactPlanV3.model_validate(private).custody_request
        == 'vault_private'
    )
    with pytest.raises(ValidationError):
        artifacts.validate_artifact_plan(private)


def test_legacy_v1_plan_has_only_a_narrow_read_migration_loader() -> None:
    """A legacy V1 plan cannot re-enter current create admission."""
    legacy: dict[str, Any] = {
        'schema_version': 'v1',
        'kind': 'document',
        'logical_output_name': 'legacy_document',
        'custody_request': 'ordinary',
        'content': {'fragments': [{'structural_id': 'body_1', 'text': 'Legacy text.'}]},
        'input_refs': [],
        'renderer_profile': 'document-v1',
        'renderer_min_version': '1.0.0',
        'output_mime_type': _DOCX,
        'validation_profile': 'document-validator-v1',
        'disposition': 'final',
        'retention_request': {'retention_class': 'legacy_read'},
        'resource_bounds': {'max_output_bytes': 1_000_000, 'max_pages': 10},
    }

    with pytest.raises(ValidationError):
        artifacts.validate_artifact_plan(legacy)
    validator = artifacts.validate_legacy_artifact_plan_v1_for_read_migration
    assert validator(legacy).schema_version == 'v1'


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('renderer_profile', 'unknown-renderer'),
        ('renderer_min_version', '99.0.0'),
        ('validation_profile', 'unknown-validator'),
    ],
)
def test_vault_refuses_unknown_or_mismatched_profiles(field: str, value: str) -> None:
    """Any profile tuple outside the runtime registry refuses admission."""
    payload = _create('v3', 'pptx')
    cast('dict[str, Any]', payload['plan'])[field] = value
    _assert_request_refused(payload)


def test_vault_refuses_audio_and_legacy_or_namespace_create_payloads() -> None:
    """Old/audio authority cannot be smuggled into the retained work envelope."""
    audio = _create('v2', 'docx')
    audio_plan = cast('dict[str, Any]', audio['plan'])
    audio_plan.update(
        {
            'schema_version': 'v1',
            'kind': 'audio',
            'content': {'fragments': [{'structural_id': 'body_1', 'text': 'Audio.'}]},
            'output_mime_type': 'audio/wav',
        },
    )
    audio_plan.pop('body')
    _assert_request_refused(audio)

    namespaced = _create('v2', 'docx')
    namespaced['record_namespace'] = 'legacy'
    _assert_request_refused(namespaced)


@pytest.mark.parametrize(
    'mutation',
    [
        'record_generation_cross_alias',
        'source_generation_mismatch',
        'zero_revision',
        'bad_manifest_digest',
        'wrong_source_kind',
        'wrong_source_mime',
        'wrong_source_bounds_shape',
        'replacement_bounds_mismatch',
        'implicit_conversion',
        'presentation_conversion',
    ],
)
def test_vault_rework_refuses_inexact_source_or_replacement(mutation: str) -> None:
    """Removing one exact-source check admits stale or converted output."""
    payload = _rework('v3', 'pptx' if mutation == 'presentation_conversion' else 'docx')
    patch = cast('dict[str, Any]', payload['patch'])
    replacement = cast('dict[str, Any]', patch['replacement_plan'])
    handles = cast('list[dict[str, Any]]', payload['input_handles'])
    if mutation == 'record_generation_cross_alias':
        handles[0]['record_handle'] = handles[0]['generation_handle']
    elif mutation == 'source_generation_mismatch':
        patch['source_generation_handle'] = 'generation_9999'
    elif mutation == 'zero_revision':
        patch['base_revision'] = 0
    elif mutation == 'bad_manifest_digest':
        patch['source_manifest_digest'] = 'not-a-digest'
    elif mutation == 'wrong_source_kind':
        patch['source_kind'] = 'image'
    elif mutation == 'wrong_source_mime':
        patch['source_mime_type'] = 'application/pdf'
    elif mutation == 'wrong_source_bounds_shape':
        cast('dict[str, Any]', patch['source_resource_bounds'])['max_cells'] = 1
    elif mutation == 'replacement_bounds_mismatch':
        cast('dict[str, Any]', payload['bounds'])['max_pages'] = 9
    elif mutation == 'implicit_conversion':
        replacement['output_mime_type'] = _PDF
    else:
        patch['source_format'] = 'docx'
    _assert_request_refused(payload)


@pytest.mark.parametrize('input_kind', ['template', 'source_image'])
def test_v2_rework_allows_one_lineage_source_plus_closed_plan_inputs(
    input_kind: str,
) -> None:
    """A replacement may use admitted inputs in addition to its lineage source."""
    source_format = 'docx' if input_kind == 'template' else 'png'
    payload = _rework('v2', source_format)
    patch = cast('dict[str, Any]', payload['patch'])
    replacement = cast('dict[str, Any]', patch['replacement_plan'])
    input_refs = cast('list[dict[str, Any]]', replacement['input_refs'])
    handles = cast('list[dict[str, Any]]', payload['input_handles'])
    body = cast('dict[str, Any]', replacement['body'])
    if input_kind == 'template':
        body['template_local_id'] = 'template_1'
        input_refs.append(
            {
                'local_id': 'template_1',
                'ref_type': 'template',
                'template_id': 'template_report',
                'revision': 1,
            }
        )
        handles.append(
            {
                'local_id': 'template_1',
                'record_handle': 'record_template_1',
                'generation_handle': 'generation_template_1',
                'role': 'template',
            }
        )
    else:
        cast('list[dict[str, Any]]', body['layers']).insert(
            0,
            {
                'layer_type': 'input_raster',
                'layer_id': 'source_layer_1',
                'input_local_id': 'source_image_1',
                'x_pixels': 0,
                'y_pixels': 0,
                'width_pixels': 10,
                'height_pixels': 10,
                'opacity_per_mille': 1000,
            },
        )
        input_refs.append(
            {
                'local_id': 'source_image_1',
                'ref_type': 'artifact',
                'artifact_id': 'artifact_image_input_1',
                'revision': 1,
            }
        )
        handles.append(
            {
                'local_id': 'source_image_1',
                'record_handle': 'record_image_input_1',
                'generation_handle': 'generation_image_input_1',
                'role': 'source_image',
            }
        )

    assert artifacts.VaultWorkRequest.model_validate(payload).operation == 'rework'
    assert artifacts.validate_vault_work_request(payload).operation == 'rework'

    missing_handle = deepcopy(payload)
    cast('list[dict[str, Any]]', missing_handle['input_handles']).pop()
    _assert_request_refused(missing_handle)

    extra_handle = deepcopy(payload)
    cast('list[dict[str, Any]]', extra_handle['input_handles']).append(
        {
            'local_id': 'unused_input_1',
            'record_handle': 'record_unused_1',
            'generation_handle': 'generation_unused_1',
            'role': 'source_file',
        }
    )
    _assert_request_refused(extra_handle)

    duplicate_lineage_source = deepcopy(payload)
    cast('list[dict[str, Any]]', duplicate_lineage_source['input_handles']).append(
        {
            'local_id': 'source_2',
            'record_handle': 'record_0002',
            'generation_handle': 'generation_0008',
            'role': 'source_artifact',
        }
    )
    _assert_request_refused(duplicate_lineage_source)


@pytest.mark.parametrize(
    ('operation', 'extra_field'),
    [
        ('create', 'client_proof_digest'),
        ('rework', 'export_filename'),
        ('retrieve_session', 'deletion_scope'),
        ('delete', 'export_filename'),
        ('redacted_export', 'client_proof_digest'),
    ],
)
def test_operation_only_authorization_fields_remain_closed(
    operation: str,
    extra_field: str,
) -> None:
    """A field owned by another effect cannot alter this operation."""
    if operation == 'create':
        payload = _create('v2', 'docx')
    elif operation == 'rework':
        payload = _rework('v2', 'docx')
    else:
        payload = _request(operation)
        payload['input_handles'] = [
            {
                'local_id': 'source_1',
                'record_handle': 'record_0001',
                'generation_handle': 'generation_0007',
                'role': 'source_artifact',
            },
        ]
        if operation == 'retrieve_session':
            payload['client_proof_digest'] = 'a' * 64
        elif operation == 'delete':
            payload['deletion_scope'] = {'mode': 'include_redacted_exports'}
        else:
            payload['export_filename'] = 'safe-export.pdf'
    extras: dict[str, Any] = {
        'client_proof_digest': 'b' * 64,
        'export_filename': 'other-export.pdf',
        'deletion_scope': {'mode': 'private_only'},
    }
    payload[extra_field] = extras[extra_field]
    _assert_request_refused(payload)


def test_legacy_structural_patch_is_not_a_vault_rework_payload() -> None:
    """Existing V2 operations remain readable but cannot authorize new Vault rework."""
    payload = _rework('v2', 'docx')
    payload['patch'] = {
        'schema_version': 'v2',
        'target_artifact_id': 'generation_0007',
        'base_revision': 2,
        'source_manifest_digest': 'b' * 64,
        'expected_output_kind': 'document',
        'renderer_profile': 'document-v1',
        'rationale': {'fragments': [{'structural_id': 'reason_1', 'text': 'Legacy.'}]},
        'operations': [{'op': 'remove_block', 'target_id': 'body_1'}],
    }
    _assert_request_refused(deepcopy(payload))


def test_vault_effect_accepted_is_a_closed_value_free_queue_response() -> None:
    """The queue response must separate its server intent from client correlation."""
    payload = {
        'server_intent_id': 'server_intent_0001',
        'operation_id': 'operation_0001',
        'operation': 'rework',
        'state': 'queued',
    }
    model = artifacts.VaultEffectAccepted
    validator = artifacts.validate_vault_effect_accepted
    schema_loader = artifacts.load_vault_effect_accepted_schema

    assert model.model_validate(payload).model_dump(mode='json') == payload
    assert validator(payload).model_dump(mode='json') == payload
    assert schema_loader()['$id'].endswith('/vault_effect_accepted.schema.json')
    assert 'VaultEffectAccepted' in artifacts.__all__

    work = _create('v2', 'docx')
    status = artifacts.PrivateWorkIntentStatus.model_validate(
        {
            'intent_id': payload['server_intent_id'],
            'operation': payload['operation'],
            'correlation_id': work['intent_id'],
            'idempotency_key': work['idempotency_key'],
            'expires_at': work['expires_at'],
            'state': 'executing_in_vault',
        }
    )
    assert status.intent_id == payload['server_intent_id']
    assert status.correlation_id == work['intent_id']

    for invalid in (
        {**payload, 'operation_id': payload['server_intent_id']},
        {**payload, 'state': 'accepted'},
        {**payload, 'operation': 'retrieve_session'},
        {**payload, 'client_intent_id': 'intent_0001'},
        {key: value for key, value in payload.items() if key != 'server_intent_id'},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(invalid)
        with pytest.raises((ValidationError, JsonSchemaValidationError)):
            validator(invalid)


def test_private_work_status_rejects_client_intent_as_server_poll_handle() -> None:
    """The client correlation ID cannot substitute for the server poll handle."""
    with pytest.raises(ValidationError):
        artifacts.PrivateWorkIntentStatus.model_validate(
            {
                'intent_id': 'client_intent_0001',
                'operation': 'create',
                'correlation_id': 'client_intent_0001',
                'idempotency_key': 'idempotency_0001',
                'expires_at': '2026-08-14T12:00:00Z',
                'state': 'executing_in_vault',
            }
        )


def test_vault_effect_status_binding_keeps_three_identities_separate() -> None:
    """Request correlation, server poll, and operation IDs cannot be interchanged."""
    work_payload = _rework('v2', 'docx')
    accepted_payload = {
        'server_intent_id': 'server_intent_0001',
        'operation_id': 'operation_0001',
        'operation': 'rework',
        'state': 'queued',
    }
    status_payload = {
        'intent_id': accepted_payload['server_intent_id'],
        'operation': accepted_payload['operation'],
        'correlation_id': work_payload['intent_id'],
        'idempotency_key': work_payload['idempotency_key'],
        'expires_at': work_payload['expires_at'],
        'state': 'executing_in_vault',
    }
    work = artifacts.VaultWorkRequest.model_validate(work_payload)
    accepted = artifacts.VaultEffectAccepted.model_validate(accepted_payload)
    status = artifacts.PrivateWorkIntentStatus.model_validate(status_payload)

    assert artifacts.validate_vault_effect_status_binding(work, accepted, status) is None

    invalid_bindings = (
        (
            work,
            artifacts.VaultEffectAccepted.model_validate(
                {**accepted_payload, 'operation_id': work_payload['intent_id']}
            ),
            status,
        ),
        (
            work,
            artifacts.VaultEffectAccepted.model_validate(
                {**accepted_payload, 'server_intent_id': 'server_intent_9999'}
            ),
            status,
        ),
        (
            work,
            accepted,
            artifacts.PrivateWorkIntentStatus.model_validate(
                {**status_payload, 'correlation_id': 'client_intent_9999'}
            ),
        ),
    )
    for invalid in invalid_bindings:
        with pytest.raises(ValueError, match='vault effect/status identity binding mismatch'):
            artifacts.validate_vault_effect_status_binding(*invalid)


def _refused_by_model(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        artifacts.VaultWorkRequest.model_validate(payload)


def test_rework_replacement_must_keep_the_source_format_identity() -> None:
    """A DOCX source cannot be replaced by a PDF plan, even though both are documents."""
    payload = _rework('v2', 'docx')
    patch = cast('dict[str, Any]', payload['patch'])
    patch['replacement_plan'] = _plan('v2', 'pdf')
    _refused_by_model(payload)


def test_rework_source_bounds_must_match_the_source_kind() -> None:
    """Source evidence carries exactly its kind's resource bounds."""
    payload = _rework('v3', 'docx')
    patch = cast('dict[str, Any]', payload['patch'])
    patch['source_resource_bounds'] = _bounds('xlsx')
    _refused_by_model(payload)


def test_rework_placeholders_cannot_name_an_admitted_vault_handle() -> None:
    """A private placeholder spelled like a record or generation handle is refused."""
    for handle in ('record_0001', 'generation_0007'):
        payload = _rework('v2', 'docx')
        patch = cast('dict[str, Any]', payload['patch'])
        replacement = cast('dict[str, Any]', patch['replacement_plan'])
        blocks = cast('list[dict[str, Any]]', replacement['body']['blocks'])
        runs = cast('list[dict[str, Any]]', blocks[0]['runs'])
        runs[0]['payload']['fragments'][0]['text'] = f'Hello {{_{{{handle}}}_}}.'
        _refused_by_model(payload)

    payload = _rework('v2', 'docx')
    patch = cast('dict[str, Any]', payload['patch'])
    replacement = cast('dict[str, Any]', patch['replacement_plan'])
    blocks = cast('list[dict[str, Any]]', replacement['body']['blocks'])
    runs = cast('list[dict[str, Any]]', blocks[0]['runs'])
    runs[0]['payload']['fragments'][0]['text'] = 'Hello {_{customer_name}_}.'
    assert artifacts.VaultWorkRequest.model_validate(payload).patch is not None


def test_create_requires_exactly_a_plan_its_bounds_and_its_inputs() -> None:
    """Create carries a plan (never a patch), the plan's bounds and exactly its inputs."""
    without_plan = _create('v2', 'docx')
    del without_plan['plan']
    with_patch = _create('v2', 'docx')
    with_patch['patch'] = cast('dict[str, Any]', _rework('v2', 'docx')['patch'])
    other_bounds = _create('v2', 'docx')
    other_bounds['bounds'] = {'max_output_bytes': 999_999, 'max_pages': 10}
    extra_handle = _create('v2', 'docx')
    extra_handle['input_handles'] = [
        {
            'local_id': 'template_1',
            'record_handle': 'record_0001',
            'generation_handle': 'generation_0001',
            'role': 'template',
        },
    ]
    for payload in (without_plan, with_patch, other_bounds, extra_handle):
        _refused_by_model(payload)


def _private_base_ref() -> dict[str, Any]:
    refs = json.loads(
        (Path(__file__).resolve().parents[2] / 'fixtures' / 'valid_artifact_refs.json').read_text(
            encoding='utf-8',
        ),
    )
    private = [ref for ref in cast('list[dict[str, Any]]', refs) if ref['custody'] != 'ordinary']
    return private[0]


def _ingest(*, base: bool) -> dict[str, Any]:
    request = _request('ingest_file')
    request['client_proof_digest'] = 'a' * 64
    intake: dict[str, Any] = {
        'kind': 'image',
        'mime_type': 'image/png',
        'output_commitment': 'b' * 64,
        'source_commitment': 'c' * 64,
        'max_source_bytes': 1024,
    }
    request['file_intake'] = intake
    if base:
        intake['expected_base_ref'] = _private_base_ref()
        request['input_handles'] = [
            {
                'local_id': 'source_1',
                'record_handle': 'out_image_0001',
                'generation_handle': 'art_private_0001',
                'role': 'source_artifact',
            },
        ]
    return request


def test_ingest_binds_its_single_source_handle_to_the_expected_base() -> None:
    """A based intake names exactly one source handle equal to the base identity."""
    assert artifacts.VaultWorkRequest.model_validate(_ingest(base=True)).file_intake
    assert artifacts.VaultWorkRequest.model_validate(_ingest(base=False)).file_intake

    unbased_with_handle = _ingest(base=False)
    unbased_with_handle['input_handles'] = _ingest(base=True)['input_handles']
    with_plan = _ingest(base=False)
    with_plan['plan'] = _plan('v2', 'pdf')
    invalid = [unbased_with_handle, with_plan]
    for field, value in (
        ('role', 'template'),
        ('generation_handle', 'art_private_9999'),
        ('record_handle', 'out_image_9999'),
    ):
        mismatched = _ingest(base=True)
        mismatched['input_handles'][0][field] = value
        invalid.append(mismatched)
    two_handles = _ingest(base=True)
    two_handles['input_handles'].append(
        {
            'local_id': 'template_1',
            'record_handle': 'record_0002',
            'generation_handle': 'generation_0002',
            'role': 'template',
        },
    )
    invalid.append(two_handles)
    for payload in invalid:
        _refused_by_model(payload)


def _single_source(operation: str) -> dict[str, Any]:
    request = _request(operation)
    request['input_handles'] = [
        {
            'local_id': 'source_1',
            'record_handle': 'record_0001',
            'generation_handle': 'generation_0001',
            'role': 'source_artifact',
        },
    ]
    if operation == 'delete':
        request['deletion_scope'] = {'mode': 'private_only'}
    if operation == 'retrieve_session':
        request['client_proof_digest'] = 'a' * 64
    if operation == 'redacted_export':
        request['export_filename'] = 'report.pdf'
    return request


@pytest.mark.parametrize('operation', ['delete', 'retrieve_session', 'redacted_export'])
def test_source_operations_take_exactly_one_source_and_no_plan(operation: str) -> None:
    """Delete, retrieval and export address one source artifact and carry no plan or patch."""
    assert artifacts.VaultWorkRequest.model_validate(_single_source(operation))
    with_plan = _single_source(operation)
    with_plan['plan'] = _plan('v2', 'pdf')
    with_patch = _single_source(operation)
    with_patch['patch'] = cast('dict[str, Any]', _rework('v2', 'pdf')['patch'])
    no_source = _single_source(operation)
    no_source['input_handles'] = []
    template = _single_source(operation)
    template['input_handles'][0]['role'] = 'template'
    two = _single_source(operation)
    two['input_handles'].append(
        {
            'local_id': 'source_2',
            'record_handle': 'record_0002',
            'generation_handle': 'generation_0002',
            'role': 'source_artifact',
        },
    )
    retrieval_part = _single_source(operation)
    retrieval_part['retrieval_part'] = 'editable_source'
    cases = [with_plan, with_patch, no_source, template, two]
    if operation != 'retrieve_session':
        cases.append(retrieval_part)
    for payload in cases:
        _refused_by_model(payload)


def test_effect_accepted_server_and_operation_ids_must_differ() -> None:
    """The queue handle never reuses the client operation id as the server id."""
    with pytest.raises(ValidationError):
        artifacts.VaultEffectAccepted.model_validate(
            {
                'server_intent_id': 'same_0001',
                'operation_id': 'same_0001',
                'operation': 'create',
                'state': 'queued',
            },
        )


def _template_rework(template_handle: dict[str, str]) -> dict[str, Any]:
    payload = _rework('v2', 'docx')
    patch = cast('dict[str, Any]', payload['patch'])
    replacement = cast('dict[str, Any]', patch['replacement_plan'])
    local_id = template_handle['local_id']
    cast('dict[str, Any]', replacement['body'])['template_local_id'] = local_id
    cast('list[dict[str, Any]]', replacement['input_refs']).append(
        {'local_id': local_id, 'ref_type': 'template', 'template_id': 'tpl', 'revision': 1},
    )
    cast('list[dict[str, Any]]', payload['input_handles']).append(
        {**template_handle, 'role': 'template'},
    )
    return payload


def test_input_handles_are_unique_per_local_id_record_and_generation() -> None:
    """Two admitted handles never share a local id, record handle or generation handle."""
    distinct = {
        'local_id': 'template_1',
        'record_handle': 'record_template_1',
        'generation_handle': 'generation_template_1',
    }
    assert artifacts.VaultWorkRequest.model_validate(_template_rework(distinct))
    for field, value in (
        ('local_id', 'source_1'),
        ('record_handle', 'record_0001'),
        ('generation_handle', 'generation_0007'),
    ):
        _refused_by_model(_template_rework({**distinct, field: value}))


def test_rework_without_a_lineage_source_is_refused() -> None:
    """A rework whose only handle is not the source artifact is a validation error."""
    payload = _rework('v2', 'docx')
    cast('list[dict[str, Any]]', payload['input_handles'])[0]['role'] = 'template'
    _refused_by_model(payload)


@pytest.mark.parametrize('version', ['v2', 'v3'])
def test_vault_plans_must_request_vault_custody(version: str) -> None:
    """An ordinary-custody plan never enters the vault, as a create or as a replacement."""
    create = _create(version, 'docx')
    cast('dict[str, Any]', create['plan'])['custody_request'] = 'ordinary'
    rework = _rework(version, 'docx')
    patch = cast('dict[str, Any]', rework['patch'])
    cast('dict[str, Any]', patch['replacement_plan'])['custody_request'] = 'ordinary'
    for payload in (create, rework):
        _refused_by_model(payload)


@pytest.mark.parametrize(
    'bounds',
    [
        {'max_output_bytes': 1_000_000},
        {'max_output_bytes': 1_000_000, 'max_pages': 10, 'max_sheets': 2},
        {'max_output_bytes': 1_000_000, 'max_pages': 10, 'max_pixels': 10},
    ],
)
def test_vault_plan_bounds_are_exactly_the_kinds_bounds(bounds: dict[str, int]) -> None:
    """A vault document plan carries max_pages and no other kind's bounds."""
    create = _create('v2', 'docx')
    cast('dict[str, Any]', create['plan'])['resource_bounds'] = bounds
    create['bounds'] = bounds
    source = _rework('v2', 'docx')
    cast('dict[str, Any]', source['patch'])['source_resource_bounds'] = bounds
    for payload in (create, source):
        _refused_by_model(payload)
