"""Closed value-free contracts for private vault artifact work."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import TypeAdapter, ValidationError

from maivn_contracts.artifacts import (
    BROWSER_TICKET_REQUEST_HEADERS,
    CLIENT_PROOF_HEADER,
    EXPORT_FILENAME_HEADER,
    GRANT_CREDENTIAL_HEADER,
    OPERATION_ID_HEADER,
    RETRIEVAL_SESSION_CREDENTIAL_HEADER,
    RETRIEVAL_SESSION_ID_HEADER,
    SENDER_ASSERTION_HEADER,
    SENDER_SIGNATURE_HEADER,
    ArtifactSurfaceIdentity,
    ArtifactTenantScope,
    ClientCapabilityHeader,
    OrdinaryArtifactRef,
    PrivateArtifactLifecycleReceipt,
    PrivateArtifactRef,
    PrivateWorkIntentStatus,
    RedactedExportReceipt,
    VaultActionTicket,
    VaultDeletionScope,
    VaultGrantCredentialDelivery,
    VaultIntentStatusRequest,
    VaultIssuerKeyPolicy,
    VaultOperation,
    VaultSenderAssertion,
    VaultWorkRequest,
    canonical_http_request_bytes,
    decode_vault_sender_assertion,
    decode_vault_sender_signature,
    load_artifact_patch_schema,
    load_artifact_plan_schema,
    load_private_artifact_lifecycle_receipt_schema,
    load_vault_intent_status_request_schema,
    load_vault_work_request_schema,
    validate_private_artifact_lifecycle_receipt,
    validate_vault_intent_status_request,
    validate_vault_work_request,
    vault_admission_fingerprint,
    vault_grant_header_digest,
    vault_intent_status_request_json_bytes,
    vault_surface_identity_digest,
    vault_tenant_claim,
    vault_work_request_json_bytes,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
JCS_SAFE_INTEGER_MAX = (2**53) - 1
JCS_SAFE_INTEGER_MIN = -JCS_SAFE_INTEGER_MAX
SHA256_HEX_LENGTH = 64


def _artifact_refs() -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / 'valid_artifact_refs.json').read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def _vault_protocol_vectors() -> dict[str, Any]:
    loaded = json.loads(
        (FIXTURES_DIR / 'vault_protocol_golden_vectors.json').read_text(encoding='utf-8'),
    )
    assert isinstance(loaded, dict)
    return cast('dict[str, Any]', loaded)


def _ticket_transport() -> dict[str, str]:
    transport = _vault_protocol_vectors()['ticket_transport']
    assert isinstance(transport, dict)
    return cast('dict[str, str]', transport)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _action_ticket() -> dict[str, Any]:
    vectors = _vault_protocol_vectors()
    request = cast('dict[str, Any]', vectors['http_request'])
    transport = _ticket_transport()
    return {
        'method': 'POST',
        'path': request['path'],
        'url': f'https://vault.example{request["path"]}',
        'public_headers': request['public_headers'],
        'client_header_digests': request['client_header_digests'],
        'sender_assertion_base64url': transport['sender_assertion_base64url'],
        'sender_signature_base64url': transport['sender_signature_base64url'],
        'body_base64url': transport['body_base64url'],
        'expires_at': '2026-08-11T12:00:00Z',
    }


def _source_free_private_image_plan() -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': 'image',
        'logical_output_name': 'private_image',
        'custody_request': 'vault_private',
        'body': {
            'canvas': {'width_pixels': 10, 'height_pixels': 10, 'color_space': 'srgb'},
            'layers': [
                {
                    'layer_type': 'shape',
                    'layer_id': 'background_1',
                    'shape': 'rectangle',
                    'x_pixels': 0,
                    'y_pixels': 0,
                    'width_pixels': 10,
                    'height_pixels': 10,
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
                    'mime_type': 'image/png',
                    'quality': 100,
                },
            ],
        },
        'input_refs': [],
        'renderer_profile': 'image-v1',
        'renderer_min_version': '1.0.0',
        'output_mime_type': 'image/png',
        'validation_profile': 'image-validator-v1',
        'disposition': 'final',
        'retention_request': {'retention_class': 'vault_private_30d'},
        'resource_bounds': {
            'max_output_bytes': 1024,
            'max_pixels': 100,
            'max_total_decoded_pixels': 100,
        },
    }


def _create_request() -> dict[str, Any]:
    return {
        'schema_version': 'vault-work-v1',
        'intent_id': 'intent_0001',
        'idempotency_key': 'idempotency_0001',
        'operation': 'create',
        'scope': {'organization_id': 'organization_0001', 'project_id': 'project_0001'},
        'surface': {
            'root_invocation_id': 'invocation_0001',
            'session_id': 'session_0001',
            'checkpoint_id': 'checkpoint_0001',
            'caller_id': 'caller_0001',
        },
        'input_handles': [],
        'value_map_handle': {
            'record_handle': 'value_map_record_0001',
            'generation_handle': 'value_map_generation_0001',
        },
        'plan': _source_free_private_image_plan(),
        'bounds': {
            'max_output_bytes': 1024,
            'max_pixels': 100,
            'max_total_decoded_pixels': 100,
        },
        'retention_policy_id': 'retention_policy_0001',
        'expires_at': '2026-08-11T12:00:00Z',
    }


def _image_rework_patch() -> dict[str, Any]:
    return {
        'source_format': 'png',
        'source_generation_handle': 'artifact_image',
        'base_revision': 1,
        'source_manifest_digest': '2' * 64,
        'source_kind': 'image',
        'source_mime_type': 'image/png',
        'source_resource_bounds': {
            'max_output_bytes': 1024,
            'max_pixels': 100,
            'max_total_decoded_pixels': 100,
        },
        'replacement_plan': _source_free_private_image_plan(),
    }


def _document_private_plan() -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': 'document',
        'logical_output_name': 'private_document',
        'custody_request': 'vault_private',
        'body': {
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
                }
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
                                'fragments': [{'structural_id': 'fragment_1', 'text': 'Safe text.'}]
                            },
                            'bold': False,
                            'italic': False,
                            'underline': False,
                        }
                    ],
                }
            ],
        },
        'input_refs': [],
        'renderer_profile': 'document-pdf-v1',
        'renderer_min_version': '1.0.0',
        'output_mime_type': 'application/pdf',
        'validation_profile': 'document-pdf-validator-v1',
        'disposition': 'final',
        'retention_request': {'retention_class': 'vault_private_30d'},
        'resource_bounds': {'max_output_bytes': 1024, 'max_pages': 1},
    }


def _workbook_private_plan(value: dict[str, Any]) -> dict[str, Any]:
    return {
        'schema_version': 'v2',
        'kind': 'spreadsheet',
        'logical_output_name': 'private_workbook',
        'custody_request': 'vault_private',
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
        'renderer_profile': 'workbook-v1',
        'renderer_min_version': '1.0.0',
        'output_mime_type': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        'validation_profile': 'workbook-validator-v1',
        'disposition': 'final',
        'retention_request': {'retention_class': 'vault_private_30d'},
        'resource_bounds': {'max_output_bytes': 1024, 'max_sheets': 1, 'max_cells': 1},
    }


def _workbook_create_request(value: dict[str, Any]) -> dict[str, Any]:
    request = _create_request()
    request['plan'] = _workbook_private_plan(value)
    request['bounds'] = {'max_output_bytes': 1024, 'max_sheets': 1, 'max_cells': 1}
    return request


def _nested_formula_number(value: float) -> dict[str, Any]:
    return {
        'value_type': 'formula',
        'expression': {
            'node_type': 'function',
            'function': 'SUM',
            'arguments': [
                {
                    'node_type': 'unary',
                    'operator': '-',
                    'operand': {
                        'node_type': 'binary',
                        'operator': '+',
                        'left': {'node_type': 'number', 'value': value},
                        'right': {'node_type': 'number', 'value': 1},
                    },
                },
            ],
        },
    }


def _copy_workbook_cell_value(
    work: VaultWorkRequest,
    cell_value: Any,
) -> VaultWorkRequest:
    plan = cast('Any', work.plan)
    body = plan.body
    sheet = body.sheets[0]
    cell = sheet.cells[0]
    changed_cell = cell.model_copy(update={'value': cell_value})
    changed_sheet = sheet.model_copy(update={'cells': (changed_cell,)})
    changed_body = body.model_copy(update={'sheets': (changed_sheet,)})
    changed_plan = plan.model_copy(update={'body': changed_body})
    return work.model_copy(update={'plan': changed_plan})


def _work_with_unchecked_direct_number(value: float) -> VaultWorkRequest:
    work = VaultWorkRequest.model_validate(
        _workbook_create_request({'value_type': 'number', 'value': 1.5}),
    )
    plan = cast('Any', work.plan)
    number_value = plan.body.sheets[0].cells[0].value
    return _copy_workbook_cell_value(
        work,
        number_value.model_copy(update={'value': value}),
    )


def _work_with_unchecked_recursive_formula_number(value: float) -> VaultWorkRequest:
    work = VaultWorkRequest.model_validate(
        _workbook_create_request(_nested_formula_number(1.5)),
    )
    plan = cast('Any', work.plan)
    formula_value = plan.body.sheets[0].cells[0].value
    function = formula_value.expression
    unary = function.arguments[0]
    binary = unary.operand
    number = binary.left
    number_payload = cast('dict[str, Any]', number.model_dump(mode='python'))
    number_payload['value'] = value
    unchecked_number = number.__class__.model_construct(**number_payload)
    changed_binary = binary.model_copy(update={'left': unchecked_number})
    changed_unary = unary.model_copy(update={'operand': changed_binary})
    changed_function = function.model_copy(update={'arguments': (changed_unary,)})
    changed_formula_value = formula_value.model_copy(update={'expression': changed_function})
    return _copy_workbook_cell_value(work, changed_formula_value)


def _workbook_revision_request(revision: int) -> dict[str, Any]:
    request = _workbook_create_request({'value_type': 'number', 'value': 1})
    plan = cast('dict[str, Any]', request['plan'])
    body = cast('dict[str, Any]', plan['body'])
    body['template_local_id'] = 'template_1'
    plan['input_refs'] = [
        {
            'local_id': 'template_1',
            'ref_type': 'template',
            'template_id': 'template_workbook',
            'revision': revision,
        },
    ]
    request['input_handles'] = [
        {
            'local_id': 'template_1',
            'record_handle': 'record_template_1',
            'generation_handle': 'generation_template_1',
            'role': 'template',
        },
    ]
    return request


def _image_revision_request(ref_type: str, revision: int) -> dict[str, Any]:
    request = _create_request()
    plan = cast('dict[str, Any]', request['plan'])
    body = cast('dict[str, Any]', plan['body'])
    layers = cast('list[dict[str, Any]]', body['layers'])
    layers.insert(
        0,
        {
            'layer_type': 'input_raster',
            'layer_id': 'source_layer',
            'input_local_id': 'source_input',
            'x_pixels': 0,
            'y_pixels': 0,
            'width_pixels': 10,
            'height_pixels': 10,
            'opacity_per_mille': 1000,
        },
    )
    authority_name = 'artifact_id' if ref_type == 'artifact' else 'resource_id'
    plan['input_refs'] = [
        {
            'local_id': 'source_input',
            'ref_type': ref_type,
            authority_name: f'{ref_type}_0001',
            'revision': revision,
        },
    ]
    request['input_handles'] = [
        {
            'local_id': 'source_input',
            'record_handle': 'record_source_1',
            'generation_handle': 'generation_source_1',
            'role': 'source_image',
        },
    ]
    return request


def _retrieve_bounds_request(bound_name: str, value: int) -> dict[str, Any]:
    request = _create_request()
    request['operation'] = 'retrieve_session'
    request['input_handles'] = [
        {
            'local_id': 'source_1',
            'record_handle': 'record_0001',
            'generation_handle': 'generation_0001',
            'role': 'source_artifact',
        },
    ]
    request.pop('plan')
    request.pop('value_map_handle')
    request['bounds'] = {'max_output_bytes': 1, bound_name: value}
    request['client_proof_digest'] = 'd' * 64
    return request


def _typed_rework_request(kind: str, base_revision: int) -> dict[str, Any]:
    request = _create_request()
    request['operation'] = 'rework'
    request['input_handles'] = [
        {
            'local_id': 'source_1',
            'record_handle': 'record_0001',
            'generation_handle': 'artifact_image',
            'role': 'source_artifact',
        },
    ]
    request.pop('plan')
    replacement_plan = {
        'document': _document_private_plan(),
        'spreadsheet': _workbook_private_plan({'value_type': 'number', 'value': 1}),
        'image': _source_free_private_image_plan(),
    }[kind]
    source_format, source_mime_type = {
        'document': ('pdf', 'application/pdf'),
        'spreadsheet': (
            'xlsx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        ),
        'image': ('png', 'image/png'),
    }[kind]
    patch = {
        'source_format': source_format,
        'source_generation_handle': 'artifact_image',
        'base_revision': base_revision,
        'source_manifest_digest': '2' * 64,
        'source_kind': kind,
        'source_mime_type': source_mime_type,
        'source_resource_bounds': deepcopy(replacement_plan['resource_bounds']),
        'replacement_plan': replacement_plan,
    }
    request['patch'] = patch
    request['bounds'] = deepcopy(replacement_plan['resource_bounds'])
    return request


def _sender_assertion() -> dict[str, str]:
    return {
        'issuer': 'data_plane',
        'key_id': 'key_0001',
        'audience': 'vault_plane',
        'actor': 'actor_0001',
        'tenant_id': 'tenant_0001',
        'surface': 'surface_0001',
        'surface_digest': 'a' * 64,
        'actual_request_digest': 'b' * 64,
        'issued_at': '2026-08-11T11:59:00Z',
        'nonce': 'nonce_0001',
        'expires_at': '2026-08-11T12:00:00Z',
    }


def test_vault_protocol_models_close_operations_identity_and_ticket_shape() -> None:
    """A widened operation or ticket field could authorize a call the issuer never admitted."""
    assertion = _sender_assertion()
    transport = _ticket_transport()
    ticket = _action_ticket()

    assert TypeAdapter(VaultOperation).validate_python('rework') == 'rework'
    assert VaultSenderAssertion.model_validate(assertion).model_dump(mode='json') == assertion
    validated_ticket = VaultActionTicket.model_validate(ticket)
    grant_headers: frozenset[ClientCapabilityHeader] = frozenset(
        {
            GRANT_CREDENTIAL_HEADER,
            CLIENT_PROOF_HEADER,
            RETRIEVAL_SESSION_CREDENTIAL_HEADER,
        },
    )
    validated_ticket.require_client_header_digests(grant_headers)
    wrong_profiles: tuple[frozenset[ClientCapabilityHeader], ...] = (
        frozenset(),
        frozenset({GRANT_CREDENTIAL_HEADER, RETRIEVAL_SESSION_CREDENTIAL_HEADER}),
    )
    for wrong_profile in wrong_profiles:
        with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
            validated_ticket.require_client_header_digests(cast('Any', wrong_profile))
    assert validated_ticket.public_headers == {
        'content-type': 'application/json',
        OPERATION_ID_HEADER: 'operation_0001',
        RETRIEVAL_SESSION_ID_HEADER: 'session_0001',
    }
    assert validated_ticket.declared_request_header_names() == frozenset(
        {
            'content-type',
            OPERATION_ID_HEADER,
            RETRIEVAL_SESSION_ID_HEADER,
            GRANT_CREDENTIAL_HEADER,
            CLIENT_PROOF_HEADER,
            RETRIEVAL_SESSION_CREDENTIAL_HEADER,
            SENDER_ASSERTION_HEADER,
            SENDER_SIGNATURE_HEADER,
        },
    )
    assert validated_ticket.declared_request_header_names() <= BROWSER_TICKET_REQUEST_HEADERS
    serialized_ticket = validated_ticket.model_dump_json()
    for raw_capability in (
        'grant-secret-0001',
        'proof-secret-0001',
        'session-secret-0001',
    ):
        assert raw_capability not in serialized_ticket
    with pytest.raises(ValidationError):
        TypeAdapter(VaultOperation).validate_python('open_retrieval')
    with pytest.raises(ValidationError):
        VaultSenderAssertion.model_validate({**assertion, 'credential': 'never-durable'})
    without_issued_at = dict(assertion)
    without_issued_at.pop('issued_at')
    with pytest.raises(ValidationError):
        VaultSenderAssertion.model_validate(without_issued_at)
    with pytest.raises(ValidationError):
        VaultSenderAssertion.model_validate(
            {**assertion, 'expires_at': assertion['issued_at']},
        )
    with pytest.raises(ValidationError):
        VaultActionTicket.model_validate({**ticket, 'path': 'v1/vault/artifacts'})
    for invalid_url in (
        'ftp://vault.example/ticket',
        'https://vault.example/v1/vault/artifacts/artifact_0002/deletion',
        'https://vault.example/v1/vault/artifacts/artifact_0001/deletion#',
        'https://user:secret@vault.example/v1/vault/artifacts/artifact_0001/deletion',
    ):
        with pytest.raises(ValidationError):
            VaultActionTicket.model_validate({**ticket, 'url': invalid_url})
    assert validated_ticket.body_base64url is not None
    encoded_body = validated_ticket.body_base64url
    encoded_body += '=' * (-len(encoded_body) % 4)
    assert base64.urlsafe_b64decode(encoded_body) == bytes.fromhex(transport['body_hex'])
    for invalid_body in ('', 'A', 'AB', 'abc=', '***'):
        with pytest.raises(ValidationError):
            VaultActionTicket.model_validate({**ticket, 'body_base64url': invalid_body})
    for unsafe_public_headers in (
        {'authorization': 'Bearer secret'},
        {'cookie': 'session=secret'},
        {'host': 'vault.example'},
        {'content-type': 'application/json\r\nx-evil: yes'},
        {GRANT_CREDENTIAL_HEADER: 'grant-secret-0001'},
        {RETRIEVAL_SESSION_CREDENTIAL_HEADER: 'session-secret-0001'},
        {'x-maivn-export-filename': 'CON.txt'},
    ):
        with pytest.raises(ValidationError):
            VaultActionTicket.model_validate(
                {**ticket, 'public_headers': unsafe_public_headers},
            )
    for unsafe_client_header_digests in (
        {RETRIEVAL_SESSION_ID_HEADER: 'd' * 64},
        {'x-maivn-unknown': 'd' * 64},
        {GRANT_CREDENTIAL_HEADER: 'grant-secret-0001'},
    ):
        with pytest.raises(ValidationError):
            VaultActionTicket.model_validate(
                {**ticket, 'client_header_digests': unsafe_client_header_digests},
            )


def test_task4_identity_and_body_helpers_match_the_protocol_golden_vectors() -> None:
    """Both planes derive the same opaque tenant, surface digest, and exact work bytes."""
    vectors = _vault_protocol_vectors()
    work_payload = cast('dict[str, Any]', vectors['work'])
    work = VaultWorkRequest.model_validate(work_payload)
    scope = ArtifactTenantScope.model_validate(work_payload['scope'])
    surface = ArtifactSurfaceIdentity.model_validate(work_payload['surface'])
    derived = cast('dict[str, str]', vectors['derived_identity'])

    assert vault_tenant_claim(scope) == derived['tenant_claim']
    assert vault_surface_identity_digest(surface) == derived['surface_identity_digest']
    assert vault_work_request_json_bytes(work) == derived['work_json_utf8'].encode('utf-8')


def test_task4_status_request_is_closed_schema_validated_and_canonical() -> None:
    """Status uses one fixed body so server identifiers never enter a URL."""
    vector = cast('dict[str, Any]', _vault_protocol_vectors()['status_request'])
    payload = cast('dict[str, str]', vector['payload'])
    request = VaultIntentStatusRequest.model_validate(payload)

    assert validate_vault_intent_status_request(payload) == request
    assert vault_intent_status_request_json_bytes(request) == cast(
        'str', vector['canonical_utf8']
    ).encode('utf-8')
    schema = load_vault_intent_status_request_schema()
    assert schema['additionalProperties'] is False
    assert schema['required'] == ['schema_version', 'server_intent_id']
    with pytest.raises(ValidationError):
        VaultIntentStatusRequest.model_validate({**payload, 'operation_id': 'operation_0001'})
    with pytest.raises(JsonSchemaValidationError):
        validate_vault_intent_status_request({**payload, 'operation_id': 'operation_0001'})


def test_task4_grant_credential_delivery_is_one_shot_and_non_disclosing_on_replay() -> None:
    """Only a first approval response may contain the raw grant credential."""
    grant_credential = 'Z3JhbnQtc2VjcmV0LTAwMDE'
    common = {
        'intent_id': 'intent_0001',
        'state': 'executing_in_vault',
        'grant_credential_digest': vault_grant_header_digest(grant_credential),
        'expires_at': '2026-08-11T12:00:00Z',
    }
    delivered = VaultGrantCredentialDelivery.model_validate(
        {
            **common,
            'credential_delivery': 'delivered',
            'grant_credential': grant_credential,
        }
    )
    replay = VaultGrantCredentialDelivery.model_validate(
        {**common, 'credential_delivery': 'not_replayable'}
    )

    assert delivered.grant_credential is not None
    assert replay.grant_credential is None
    assert grant_credential not in repr(delivered)
    with pytest.raises(ValidationError):
        VaultGrantCredentialDelivery.model_validate({**common, 'credential_delivery': 'delivered'})
    with pytest.raises(ValidationError):
        VaultGrantCredentialDelivery.model_validate(
            {
                **common,
                'credential_delivery': 'not_replayable',
                'grant_credential': grant_credential,
            }
        )


def test_action_ticket_requires_canonical_assertion_json_and_ed25519_signature() -> None:
    """Transport aliases or non-Ed25519-sized signatures must not reach verification."""
    ticket = _action_ticket()
    for invalid_signature in (_base64url(bytes(63)), _base64url(bytes(65))):
        with pytest.raises(
            ValidationError,
            match='vault_action_ticket_invalid_sender_signature',
        ):
            VaultActionTicket.model_validate(
                {**ticket, 'sender_signature_base64url': invalid_signature},
            )

    noncanonical_assertion = _base64url(json.dumps(_sender_assertion()).encode())
    for invalid_assertion in (
        _base64url(b'{}'),
        noncanonical_assertion,
        _base64url(b'{"actor":"actor_0001","unexpected":true}'),
        _base64url(b'\xff'),
    ):
        with pytest.raises(
            ValidationError,
            match='vault_action_ticket_invalid_sender_assertion',
        ):
            VaultActionTicket.model_validate(
                {**ticket, 'sender_assertion_base64url': invalid_assertion},
            )


def test_sender_transport_decoders_enforce_one_canonical_http_boundary() -> None:
    """HTTP auth must not reimplement assertion or signature transport parsing."""
    vectors = _vault_protocol_vectors()
    transport = _ticket_transport()
    assertion = VaultSenderAssertion.model_validate(vectors['assertion'])
    assert decode_vault_sender_assertion(transport['sender_assertion_base64url']) == assertion
    assert decode_vault_sender_signature(transport['sender_signature_base64url']) == bytes(
        range(64),
    )

    assertion_json = cast('str', vectors['assertion_json_utf8'])
    duplicate_assertion = _base64url(
        assertion_json.replace(
            '"actor":"actor_0001"',
            '"actor":"actor_0001","actor":"actor_0001"',
            1,
        ).encode(),
    )
    noncanonical_assertion = _base64url(json.dumps(vectors['assertion']).encode())
    for invalid_assertion in (
        '',
        'A',
        f'{transport["sender_assertion_base64url"]}=',
        duplicate_assertion,
        noncanonical_assertion,
        _base64url(b'{"actor":"actor_0001","unexpected":true}'),
        _base64url(b'\xff'),
    ):
        with pytest.raises(
            ValueError,
            match=r'^vault_action_ticket_invalid_sender_assertion$',
        ):
            decode_vault_sender_assertion(cast('Any', invalid_assertion))

    for invalid_signature in (
        '',
        'A',
        f'{transport["sender_signature_base64url"]}=',
        _base64url(bytes(63)),
        _base64url(bytes(65)),
    ):
        with pytest.raises(
            ValueError,
            match=r'^vault_action_ticket_invalid_sender_signature$',
        ):
            decode_vault_sender_signature(cast('Any', invalid_signature))


def test_public_protocol_errors_do_not_chain_sensitive_transport_values() -> None:
    """Fixed boundary errors must not retain raw input in an exception chain."""
    caught_errors: list[ValueError] = []
    with pytest.raises(
        ValueError,
        match=r'^vault_action_ticket_invalid_sender_assertion$',
    ) as malformed_assertion:
        decode_vault_sender_assertion(cast('Any', _base64url(b'\xff')))
    caught_errors.append(malformed_assertion.value)

    with pytest.raises(
        ValueError,
        match=r'^vault_action_ticket_invalid_sender_signature$',
    ) as malformed_signature:
        decode_vault_sender_signature(cast('Any', _base64url(bytes(63))))
    caught_errors.append(malformed_signature.value)

    with pytest.raises(ValueError, match=r'^vault_protocol_invalid_target$') as invalid_target:
        canonical_http_request_bytes(
            'POST',
            '/café',
            b'',
            {},
            {},
            expected_client_headers=frozenset(),
        )
    caught_errors.append(invalid_target.value)

    with pytest.raises(ValueError, match=r'^vault_protocol_unsafe_header$') as unsafe_header:
        canonical_http_request_bytes(
            'POST',
            '/',
            b'',
            {EXPORT_FILENAME_HEADER: 'CON.txt'},
            {},
            expected_client_headers=frozenset(),
        )
    caught_errors.append(unsafe_header.value)

    for error in caught_errors:
        assert error.__cause__ is None
        assert error.__context__ is None


def test_action_ticket_refuses_a_canonical_but_unrelated_assertion() -> None:
    """A valid assertion envelope may authorize only the exact ticket call and expiry."""
    ticket = _action_ticket()
    assertion = cast('dict[str, str]', _vault_protocol_vectors()['assertion'])
    unrelated_assertion = {
        **assertion,
        'actual_request_digest': 'c' * 64,
    }
    unrelated_assertion_base64url = _base64url(
        json.dumps(
            unrelated_assertion,
            ensure_ascii=False,
            separators=(',', ':'),
            sort_keys=True,
        ).encode(),
    )
    mismatches = (
        {**ticket, 'method': 'GET'},
        {
            **ticket,
            'path': '/v1/vault/work-intents?b=2&a=2',
            'url': 'https://vault.example/v1/vault/work-intents?b=2&a=2',
        },
        {**ticket, 'body_base64url': 'AAH_'},
        {**ticket, 'public_headers': {**ticket['public_headers'], 'range': 'bytes=0-1'}},
        {
            **ticket,
            'client_header_digests': {
                **ticket['client_header_digests'],
                GRANT_CREDENTIAL_HEADER: 'd' * 64,
            },
        },
        {**ticket, 'expires_at': '2026-08-11T12:01:00Z'},
        {**ticket, 'sender_assertion_base64url': unrelated_assertion_base64url},
    )
    for mismatch in mismatches:
        with pytest.raises(
            ValidationError,
            match='vault_action_ticket_assertion_mismatch',
        ):
            VaultActionTicket.model_validate(mismatch)


def test_issuer_key_policy_and_deletion_scope_are_closed_and_operation_bound() -> None:
    """A broad issuer policy or optional deletion mode could widen a tenant/surface effect."""
    policy = {
        'issuer': 'data_plane',
        'key_id': 'key_0001',
        'audience': 'vault_plane',
        'allowed_tenant_ids': ['tenant_0001'],
        'allowed_surfaces': ['surface_0001'],
    }
    delete = {
        **_create_request(),
        'operation': 'delete',
        'input_handles': [
            {
                'local_id': 'source_1',
                'record_handle': 'record_0001',
                'generation_handle': 'artifact_image',
                'role': 'source_artifact',
            },
        ],
        'plan': None,
        'deletion_scope': {'mode': 'include_redacted_exports'},
    }
    delete.pop('plan')
    delete.pop('value_map_handle')

    assert VaultIssuerKeyPolicy.model_validate(policy).allowed_tenant_ids == ('tenant_0001',)
    assert VaultDeletionScope.model_validate({'mode': 'private_only'}).mode == 'private_only'
    assert VaultWorkRequest.model_validate(delete).deletion_scope == VaultDeletionScope(
        mode='include_redacted_exports',
    )
    assert validate_vault_work_request(delete).deletion_scope == VaultDeletionScope(
        mode='include_redacted_exports',
    )
    with pytest.raises(ValidationError):
        VaultIssuerKeyPolicy.model_validate({**policy, 'unbounded': True})
    for invalid_policy in (
        {**policy, 'allowed_tenant_ids': []},
        {**policy, 'allowed_surfaces': []},
        {**policy, 'allowed_tenant_ids': ['tenant_0001', 'tenant_0001']},
        {**policy, 'allowed_surfaces': ['surface_0001', 'surface_0001']},
    ):
        with pytest.raises(ValidationError):
            VaultIssuerKeyPolicy.model_validate(invalid_policy)
    with pytest.raises(ValidationError):
        VaultDeletionScope.model_validate({'mode': 'all_artifacts'})
    invalid_requests = (
        {key: value for key, value in delete.items() if key != 'deletion_scope'},
        {**delete, 'deletion_scope': {'mode': 'include_exports'}},
        {**_create_request(), 'deletion_scope': {'mode': 'private_only'}},
    )
    for invalid in invalid_requests:
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(invalid)
        with pytest.raises(JsonSchemaValidationError):
            validate_vault_work_request(invalid)

    schema = load_vault_work_request_schema()
    assert schema['$defs']['deletionScope']['properties']['mode'] == {
        'enum': ['private_only', 'include_redacted_exports'],
    }
    assert 'deletion_scope' in schema['$defs']['deleteRequest']['required']
    for variant in (
        'createRequest',
        'reworkRequest',
        'retrieveSessionRequest',
        'redactedExportRequest',
    ):
        assert 'deletion_scope' not in schema['$defs'][variant]['properties']


def test_operation_specific_request_bindings_are_closed_and_loader_aligned() -> None:
    """Proof and export metadata must be admitted on their operation, never added at execution."""
    source = {
        **_create_request(),
        'input_handles': [
            {
                'local_id': 'source_1',
                'record_handle': 'record_0001',
                'generation_handle': 'artifact_image',
                'role': 'source_artifact',
            },
        ],
        'plan': None,
        'bounds': {'max_output_bytes': 1024},
    }
    source.pop('plan')
    source.pop('value_map_handle')
    retrieval = {**source, 'operation': 'retrieve_session', 'client_proof_digest': 'd' * 64}
    export = {
        **source,
        'operation': 'redacted_export',
        'export_filename': 'Approved report (1).docx',
    }

    assert validate_vault_work_request(retrieval).client_proof_digest == 'd' * 64
    assert validate_vault_work_request(export).export_filename == 'Approved report (1).docx'
    for invalid in (
        {key: value for key, value in retrieval.items() if key != 'client_proof_digest'},
        {key: value for key, value in export.items() if key != 'export_filename'},
        {**_create_request(), 'client_proof_digest': 'd' * 64},
        {**_create_request(), 'export_filename': 'approved.docx'},
    ):
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(invalid)
        with pytest.raises(JsonSchemaValidationError):
            validate_vault_work_request(invalid)

    for unsafe_filename in (
        '.',
        '..',
        'CON',
        'con.docx',
        'CON .txt',
        'PRN.pdf',
        'AUX',
        'nul.txt',
        'COM1.txt',
        'com9.TXT',
        'LPT9',
        'lpt1.pdf',
        'trailing.',
        'trailing ',
        'a/b',
        'a\\b',
        'a\x00b',
        'a\u202eb',
        'café.txt',
        '_leading.txt',
    ):
        invalid_export = {**export, 'export_filename': unsafe_filename}
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(invalid_export)
        with pytest.raises(JsonSchemaValidationError):
            validate_vault_work_request(invalid_export)


def test_create_request_accepts_only_a_closed_vault_plan() -> None:
    """Removing custody/profile closure would admit ordinary or unknown rendering."""
    request = _create_request()

    assert VaultWorkRequest.model_validate(request).model_dump(
        mode='json', exclude_none=True
    ) == deepcopy(request)

    for forbidden in (
        {'private_filename': 'private-name.png'},
        {'signed_url': 'https://vault.example/private'},
        {'capability': 'bearer-secret'},
        {'sha256': '0' * 64},
    ):
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate({**request, **forbidden})


def test_vault_request_requires_an_opaque_idempotency_key() -> None:
    """Response-loss retries cannot converge without a caller-bound immutable identity."""
    request = _create_request()
    del request['idempotency_key']
    with pytest.raises(ValidationError):
        VaultWorkRequest.model_validate(request)
    with pytest.raises(JsonSchemaValidationError):
        validate_vault_work_request(request)


@pytest.mark.parametrize(
    ('kind', 'operations'),
    [
        ('document', [{'op': 'remove_block', 'target_id': 'paragraph_1'}]),
        ('spreadsheet', [{'op': 'remove_cells', 'cell_ids': ['cell_1']}]),
        ('image', [{'op': 'remove_layer', 'target_id': 'layer_1'}]),
    ],
)
def test_rework_requires_kind_complete_resource_bounds(
    kind: str,
    operations: list[dict[str, Any]],
) -> None:
    """A rework must declare every renderer bound before the vault accepts it."""
    patch = {
        **_image_rework_patch(),
        'expected_output_kind': kind,
        'operations': operations,
    }
    request = {
        **_create_request(),
        'operation': 'rework',
        'input_handles': [
            {
                'local_id': 'source_1',
                'record_handle': 'record_0001',
                'generation_handle': 'artifact_image',
                'role': 'source_artifact',
            },
        ],
        'plan': None,
        'patch': patch,
        'bounds': {'max_output_bytes': 1024},
    }
    with pytest.raises(ValidationError):
        VaultWorkRequest.model_validate(request)
    with pytest.raises(JsonSchemaValidationError):
        validate_vault_work_request(request)


def test_vault_work_request_jcs_safe_integer_boundaries_are_end_to_end() -> None:
    """Every integer family admitted to JCS must stay exactly representable."""
    bounds_boundary = _create_request()
    bounds_boundary['bounds']['max_output_bytes'] = JCS_SAFE_INTEGER_MAX
    bounds_boundary['plan']['resource_bounds']['max_output_bytes'] = JCS_SAFE_INTEGER_MAX
    bounds_names = (
        'max_output_bytes',
        'max_pages',
        'max_sheets',
        'max_cells',
        'max_pixels',
        'max_total_decoded_pixels',
        'max_duration_seconds',
    )
    valid_payloads = (
        bounds_boundary,
        *(
            _retrieve_bounds_request(bound_name, JCS_SAFE_INTEGER_MAX)
            for bound_name in bounds_names
        ),
        _image_revision_request('artifact', JCS_SAFE_INTEGER_MAX),
        _image_revision_request('resource', JCS_SAFE_INTEGER_MAX),
        _workbook_revision_request(JCS_SAFE_INTEGER_MAX),
        *(
            _typed_rework_request(kind, JCS_SAFE_INTEGER_MAX)
            for kind in ('document', 'spreadsheet', 'image')
        ),
        _workbook_create_request(
            {'value_type': 'number', 'value': JCS_SAFE_INTEGER_MAX},
        ),
        _workbook_create_request(
            {'value_type': 'number', 'value': JCS_SAFE_INTEGER_MIN},
        ),
        _workbook_create_request(
            {
                'value_type': 'formula',
                'expression': {'node_type': 'number', 'value': JCS_SAFE_INTEGER_MAX},
            },
        ),
        _workbook_create_request(
            {
                'value_type': 'formula',
                'expression': {'node_type': 'number', 'value': JCS_SAFE_INTEGER_MIN},
            },
        ),
        _workbook_create_request(_nested_formula_number(JCS_SAFE_INTEGER_MAX)),
        _workbook_create_request(_nested_formula_number(JCS_SAFE_INTEGER_MIN)),
    )
    for payload in valid_payloads:
        work = VaultWorkRequest.model_validate(payload)
        assert validate_vault_work_request(payload) == work
        assert (
            len(
                vault_admission_fingerprint(
                    work,
                    issuer='data_plane',
                    actor='actor_0001',
                    tenant_id='tenant_0001',
                    surface='surface_0001',
                ),
            )
            == SHA256_HEX_LENGTH
        )

    unsafe_bounds = deepcopy(bounds_boundary)
    unsafe_bounds['bounds']['max_output_bytes'] = JCS_SAFE_INTEGER_MAX + 1
    unsafe_bounds['plan']['resource_bounds']['max_output_bytes'] = JCS_SAFE_INTEGER_MAX + 1
    invalid_payloads = (
        unsafe_bounds,
        *(
            _retrieve_bounds_request(bound_name, JCS_SAFE_INTEGER_MAX + 1)
            for bound_name in bounds_names
        ),
        _image_revision_request('artifact', JCS_SAFE_INTEGER_MAX + 1),
        _image_revision_request('resource', JCS_SAFE_INTEGER_MAX + 1),
        _workbook_revision_request(JCS_SAFE_INTEGER_MAX + 1),
        *(
            _typed_rework_request(kind, JCS_SAFE_INTEGER_MAX + 1)
            for kind in ('document', 'spreadsheet', 'image')
        ),
        _workbook_create_request(
            {'value_type': 'number', 'value': JCS_SAFE_INTEGER_MAX + 1},
        ),
        _workbook_create_request(
            {'value_type': 'number', 'value': JCS_SAFE_INTEGER_MIN - 1},
        ),
        _workbook_create_request(
            {
                'value_type': 'formula',
                'expression': {'node_type': 'number', 'value': JCS_SAFE_INTEGER_MAX + 1},
            },
        ),
        _workbook_create_request(
            {
                'value_type': 'formula',
                'expression': {'node_type': 'number', 'value': JCS_SAFE_INTEGER_MIN - 1},
            },
        ),
        _workbook_create_request(_nested_formula_number(JCS_SAFE_INTEGER_MAX + 1)),
        _workbook_create_request(_nested_formula_number(JCS_SAFE_INTEGER_MIN - 1)),
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(payload)
        with pytest.raises(JsonSchemaValidationError):
            validate_vault_work_request(payload)

    valid_work = VaultWorkRequest.model_validate(bounds_boundary)
    unsafe_work = valid_work.model_copy(
        update={
            'bounds': valid_work.bounds.model_copy(
                update={'max_output_bytes': JCS_SAFE_INTEGER_MAX + 1},
            ),
        },
    )
    with pytest.raises(ValueError, match=r'^vault_work_request_unsafe_jcs_integer$'):
        vault_admission_fingerprint(
            unsafe_work,
            issuer='data_plane',
            actor='actor_0001',
            tenant_id='tenant_0001',
            surface='surface_0001',
        )


def test_vault_work_request_workbook_numbers_preserve_finite_fraction_validation() -> None:
    """Safe finite fractions remain canonical while nonfinite or oversized numbers refuse."""
    for value in (123.5, -123.5):
        payload = _workbook_create_request({'value_type': 'number', 'value': value})
        assert VaultWorkRequest.model_validate(payload)
        assert validate_vault_work_request(payload)
    for value in (float('nan'), float('inf'), float('-inf'), 1e308):
        payload = _workbook_create_request({'value_type': 'number', 'value': value})
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(payload)
        with pytest.raises((JsonSchemaValidationError, ValidationError)):
            validate_vault_work_request(payload)


def test_admission_fingerprint_rejects_unchecked_workbook_float_domains() -> None:
    """Nonvalidating copies must not bypass JCS number-domain admission checks."""
    identity = {
        'issuer': 'data_plane',
        'actor': 'actor_0001',
        'tenant_id': 'tenant_0001',
        'surface': 'surface_0001',
    }
    safe_work = (
        VaultWorkRequest.model_validate(
            _workbook_create_request({'value_type': 'number', 'value': 123.5}),
        ),
        VaultWorkRequest.model_validate(
            _workbook_create_request(_nested_formula_number(-123.5)),
        ),
    )
    for work in safe_work:
        assert len(vault_admission_fingerprint(work, **identity)) == SHA256_HEX_LENGTH

    for unsafe_float in (
        float(JCS_SAFE_INTEGER_MAX + 1),
        float('nan'),
        float('inf'),
        float('-inf'),
    ):
        unchecked_work = (
            _work_with_unchecked_direct_number(unsafe_float),
            _work_with_unchecked_recursive_formula_number(unsafe_float),
        )
        for work in unchecked_work:
            with pytest.raises(
                ValueError,
                match=r'^vault_work_request_unsafe_jcs_integer$',
            ):
                vault_admission_fingerprint(work, **identity)


def test_jcs_safe_integer_bounds_are_pinned_in_every_owning_schema() -> None:
    """Hand-authored plan, patch, and Vault schemas must match the model boundary."""
    plan_schema = load_artifact_plan_schema()
    for ref_name in ('artifactRefV2', 'resourceRefV2', 'templateRefV2'):
        assert plan_schema['$defs'][ref_name]['properties']['revision']['maximum'] == (
            JCS_SAFE_INTEGER_MAX
        )
    for plan_name in (
        'artifactPlanV2',
        'vaultDocumentArtifactPlanV2',
        'vaultWorkbookArtifactPlanV2',
        'vaultImageArtifactPlanV2',
    ):
        resource_properties = plan_schema['$defs'][plan_name]['properties']['resource_bounds'][
            'properties'
        ]
        assert all(
            definition['maximum'] == JCS_SAFE_INTEGER_MAX
            for definition in resource_properties.values()
        )
    for value_name in ('workbookNumberValueV2', 'workbookFormulaNumberV2'):
        value_schema = plan_schema['$defs'][value_name]['properties']['value']
        assert value_schema == {
            'type': 'number',
            'minimum': JCS_SAFE_INTEGER_MIN,
            'maximum': JCS_SAFE_INTEGER_MAX,
        }

    patch_schema = load_artifact_patch_schema()
    for patch_name in (
        'documentArtifactPatchV2',
        'workbookArtifactPatchV2',
        'imageArtifactPatchV2',
    ):
        assert patch_schema['$defs'][patch_name]['properties']['base_revision']['maximum'] == (
            JCS_SAFE_INTEGER_MAX
        )

    vault_schema = load_vault_work_request_schema()
    for bounds_name in (
        'resourceBounds',
        'documentResourceBounds',
        'workbookResourceBounds',
        'imageResourceBounds',
    ):
        assert all(
            definition['maximum'] == JCS_SAFE_INTEGER_MAX
            for definition in vault_schema['$defs'][bounds_name]['properties'].values()
        )


def test_operation_payloads_and_input_handles_are_exact_and_non_authorizing() -> None:
    """A widened branch could alias handles or smuggle rendering into retrieval/deletion."""
    rework = {
        **_create_request(),
        'operation': 'rework',
        'input_handles': [
            {
                'local_id': 'source_1',
                'record_handle': 'record_0001',
                'generation_handle': 'artifact_image',
                'role': 'source_artifact',
            },
        ],
        'plan': None,
        'patch': _image_rework_patch(),
    }
    assert VaultWorkRequest.model_validate(rework).operation == 'rework'

    for operation in ('retrieve_session', 'delete', 'redacted_export'):
        request = {**rework, 'operation': operation, 'patch': None}
        del request['value_map_handle']
        request.update(
            {
                'retrieve_session': {'client_proof_digest': 'd' * 64},
                'delete': {'deletion_scope': {'mode': 'private_only'}},
                'redacted_export': {'export_filename': 'approved.docx'},
            }[operation],
        )
        assert VaultWorkRequest.model_validate(request).operation == operation

    invalid = (
        {**_create_request(), 'operation': 'rework'},
        {**_create_request(), 'operation': 'delete'},
        {**rework, 'plan': _source_free_private_image_plan()},
        {
            **rework,
            'input_handles': [
                {
                    'local_id': 'source_1',
                    'record_handle': 'source_1',
                    'generation_handle': 'artifact_image',
                    'role': 'source_artifact',
                },
            ],
        },
    )
    for request in invalid:
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(request)


def test_vault_request_rejects_legacy_audio_and_placeholder_handle_aliases() -> None:
    """Legacy/audio plans and placeholder-derived handles must be unrepresentable at admission."""
    legacy = _source_free_private_image_plan()
    legacy['schema_version'] = 'v1'
    audio = _source_free_private_image_plan()
    audio['kind'] = 'audio'
    audio['output_mime_type'] = 'audio/mpeg'
    aliased = _image_rework_patch()
    aliased['rationale'] = {
        'fragments': [{'structural_id': 'reason_1', 'text': '{_{record_0001}_}'}],
    }

    for request in (
        {**_create_request(), 'plan': legacy},
        {**_create_request(), 'plan': audio},
        {
            **_create_request(),
            'operation': 'rework',
            'input_handles': [
                {
                    'local_id': 'source_1',
                    'record_handle': 'record_0001',
                    'generation_handle': 'artifact_image',
                    'role': 'source_artifact',
                },
            ],
            'plan': None,
            'patch': aliased,
        },
    ):
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(request)


def test_retrieval_relation_is_custody_specific_without_embedding_delivery_data() -> None:
    """A shared relation would let ordinary delivery paths handle private vault artifacts."""
    ordinary, private = _artifact_refs()
    private = deepcopy(private)
    private['retrieval_action'] = {'relation': 'artifact.vault_download_authorization'}

    assert PrivateArtifactRef.model_validate(private).retrieval_action.relation == (
        'artifact.vault_download_authorization'
    )

    ordinary['retrieval_action'] = {'relation': 'artifact.vault_download_authorization'}
    private['retrieval_action'] = {'relation': 'artifact.download_authorization'}
    with pytest.raises(ValidationError):
        OrdinaryArtifactRef.model_validate(ordinary)
    with pytest.raises(ValidationError):
        PrivateArtifactRef.model_validate(private)


def _private_ref() -> dict[str, Any]:
    private = deepcopy(_artifact_refs()[1])
    private['retrieval_action'] = {'relation': 'artifact.vault_download_authorization'}
    return private


def _intent(operation: str) -> dict[str, Any]:
    return {
        'intent_id': f'intent_{operation}',
        'operation': operation,
        'correlation_id': 'correlation_0001',
        'idempotency_key': 'idempotency_0001',
        'expires_at': '2026-08-11T12:00:00Z',
        'state': 'committed',
    }


def test_committed_private_intent_has_exactly_one_operation_specific_outcome() -> None:
    """A generic outcome would let credentials or private refs cross operation boundaries."""
    lifecycle_receipt = {
        'receipt_id': 'receipt_delete_0001',
        'artifact_id': 'art_private_0001',
        'operation': 'delete',
        'state': 'deleted',
        'correlation_id': 'correlation_0001',
        'occurred_at': '2026-08-11T11:00:00Z',
    }
    export_receipt = {
        'receipt_id': 'receipt_export_0001',
        'ordinary_artifact': _artifact_refs()[0],
        'correlation_id': 'correlation_0001',
        'occurred_at': '2026-08-11T11:00:00Z',
    }
    cases = (
        ('create', 'artifact', _private_ref()),
        ('rework', 'artifact', _private_ref()),
        ('delete', 'lifecycle_receipt', lifecycle_receipt),
        ('redacted_export', 'redacted_export_receipt', export_receipt),
        (
            'retrieve_session',
            'retrieval_action',
            {'relation': 'artifact.vault_download_authorization'},
        ),
    )

    for operation, field_name, outcome in cases:
        payload = {**_intent(operation), field_name: outcome}
        projected = PrivateWorkIntentStatus.model_validate(payload)
        assert projected.model_dump(mode='json', exclude_none=True) == payload

        with pytest.raises(ValidationError):
            PrivateWorkIntentStatus.model_validate(
                {**payload, 'retrieval_action': {'relation': 'artifact.download_authorization'}},
            )

    assert PrivateArtifactLifecycleReceipt.model_validate(lifecycle_receipt).state == 'deleted'
    assert (
        RedactedExportReceipt.model_validate(export_receipt).ordinary_artifact.custody == 'ordinary'
    )


def test_nonterminal_private_intent_carries_no_committed_outcome() -> None:
    """A pre-commit outcome would project an artifact or delivery action before vault commit."""
    pending = {**_intent('create'), 'state': 'authorization_pending'}
    assert PrivateWorkIntentStatus.model_validate(pending).artifact is None
    with pytest.raises(ValidationError):
        PrivateWorkIntentStatus.model_validate({**pending, 'artifact': _private_ref()})


def test_vault_request_and_lifecycle_receipt_schema_loaders_round_trip_closed_models() -> None:
    """A loader/model drift would let one service accept a wire shape another rejects."""
    request = _create_request()
    receipt = {
        'receipt_id': 'receipt_create_0001',
        'artifact_id': 'art_private_0001',
        'operation': 'create',
        'state': 'available_in_vault',
        'correlation_id': 'correlation_0001',
        'occurred_at': '2026-08-11T11:00:00Z',
    }

    assert load_vault_work_request_schema()['$id'].endswith('/vault_work_request.schema.json')
    assert load_private_artifact_lifecycle_receipt_schema()['$id'].endswith(
        '/private_artifact_lifecycle_receipt.schema.json',
    )
    assert validate_vault_work_request(request).model_dump(mode='json', exclude_none=True) == {
        key: value for key, value in request.items() if value is not None
    }
    assert validate_private_artifact_lifecycle_receipt(receipt).model_dump(mode='json') == receipt
