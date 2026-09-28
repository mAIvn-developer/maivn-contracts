"""Closed cross-service contracts for proven ordinary redacted exports."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError

from maivn_contracts import artifacts

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
_PDF = 'application/pdf'
_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
_PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
_PNG = 'image/png'
_JPEG = 'image/jpeg'
_MAX_EXPORT_BYTES = 52_428_800
_NOW = '2026-08-14T18:30:00Z'

_FORMAT_IDENTITIES = {
    'docx': ('document', _DOCX, 'safe-export.docx'),
    'pdf': ('document', _PDF, 'safe-export.pdf'),
    'xlsx': ('spreadsheet', _XLSX, 'safe-export.xlsx'),
    'pptx': ('presentation', _PPTX, 'safe-export.pptx'),
    'png': ('image', _PNG, 'safe-export.png'),
    'jpeg': ('image', _JPEG, 'safe-export.jpeg'),
}


def _manifest(format_name: str = 'pdf', **overrides: object) -> dict[str, object]:
    kind, mime_type, filename = _FORMAT_IDENTITIES[format_name]
    payload: dict[str, object] = {
        'schema_version': 'verified-export-v1',
        'scope': {'organization_id': 'organization_0001', 'project_id': 'project_0001'},
        'surface': {
            'root_invocation_id': 'root_invocation_0001',
            'session_id': 'session_0001',
            'checkpoint_id': 'checkpoint_0001',
            'caller_id': 'caller_0001',
        },
        'correlation_id': 'export_correlation_0001',
        'artifact_kind': kind,
        'mime_type': mime_type,
        'public_filename': filename,
        'content_length': 4_096,
        'content_sha256': 'a' * 64,
        'proof_receipt_id': 'proof_receipt_0001',
    }
    payload.update(overrides)
    return payload


def _ordinary_artifact() -> dict[str, object]:
    return {
        'artifact_id': 'ordinary_artifact_0001',
        'logical_output_id': 'logical_output_0001',
        'revision': 1,
        'kind': 'document',
        'mime_type': _PDF,
        'created_at': _NOW,
        'effective_retention': {
            'policy_snapshot_id': 'retention_policy_0001',
            'retention_class': 'artifact_30d',
            'expires_at': '2026-09-13T18:30:00Z',
        },
        'custody': 'ordinary',
        'state': 'available',
        'display_filename': 'safe-export.pdf',
        'size_bytes': 4_096,
        'sha256': 'a' * 64,
        'producer': {
            'producer_class': 'vault',
            'producer_id': 'verified-redacted-export',
            'root_invocation_id': 'ordinary_root_0001',
            'session_id': 'ordinary_session_0001',
        },
        'validation_receipt': {
            'receipt_id': 'validation_receipt_0001',
            'status': 'validated',
            'validator_profile': 'verified-export-v1',
            'validator_version': '1.0.0',
        },
        'retrieval_action': {'relation': 'artifact.download_authorization'},
    }


def _public_receipt(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'receipt_id': 'publication_receipt_0001',
        'ordinary_artifact': _ordinary_artifact(),
        'correlation_id': 'export_correlation_0001',
        'occurred_at': _NOW,
    }
    payload.update(overrides)
    return payload


def _assert_model_and_loader_refuse(
    model: type[BaseModel],
    validator: Callable[[Mapping[str, Any]], object],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    with pytest.raises((ValidationError, JsonSchemaValidationError)):
        validator(payload)


@pytest.mark.parametrize('format_name', sorted(_FORMAT_IDENTITIES))
def test_verified_export_manifest_accepts_only_the_six_exact_publication_identities(
    format_name: str,
) -> None:
    """Removing a MIME/kind/suffix branch would break one supported export format."""
    payload = _manifest(format_name)

    parsed = artifacts.VerifiedExportManifest.model_validate(payload)

    assert parsed.model_dump(mode='json', exclude_none=True) == payload
    assert artifacts.validate_verified_export_manifest(payload) == parsed


@pytest.mark.parametrize('content_length', [1, _MAX_EXPORT_BYTES])
def test_verified_export_manifest_pins_the_exact_nonempty_content_bound(
    content_length: int,
) -> None:
    """The ordinary wire may admit the first and final byte counts only within 50 MiB."""
    payload = _manifest(content_length=content_length)
    assert artifacts.validate_verified_export_manifest(payload).content_length == content_length


@pytest.mark.parametrize('content_length', [0, _MAX_EXPORT_BYTES + 1, True, 1.0])
def test_verified_export_manifest_refuses_out_of_bound_or_nonexact_lengths(
    content_length: object,
) -> None:
    """An oversized or coerced length would weaken the framing and allocation bound."""
    _assert_model_and_loader_refuse(
        artifacts.VerifiedExportManifest,
        artifacts.validate_verified_export_manifest,
        _manifest(content_length=content_length),
    )


@pytest.mark.parametrize(
    'changes',
    [
        {'artifact_kind': 'image'},
        {'mime_type': _DOCX},
        {'public_filename': 'safe-export.docx'},
        {'public_filename': 'safe-export.PDF'},
        {'artifact_kind': 'audio', 'mime_type': 'audio/mpeg', 'public_filename': 'safe.mp3'},
        {
            'artifact_kind': 'other',
            'mime_type': 'application/octet-stream',
            'public_filename': 'safe.bin',
        },
    ],
)
def test_verified_export_manifest_refuses_mismatched_or_unsupported_identity(
    changes: dict[str, object],
) -> None:
    """Changing any member of the proven format identity must fail closed."""
    payload = _manifest()
    payload.update(changes)
    _assert_model_and_loader_refuse(
        artifacts.VerifiedExportManifest,
        artifacts.validate_verified_export_manifest,
        payload,
    )


@pytest.mark.parametrize(
    'forbidden_field',
    [
        'private_artifact_id',
        'generation_handle',
        'record_namespace',
        'storage_coordinate',
        'source_manifest',
        'known_values',
        'proof_detail',
        'private_deletion_identifier',
    ],
)
def test_verified_export_manifest_refuses_every_private_linkage_field(
    forbidden_field: str,
) -> None:
    """The cross-plane proof output cannot carry a private storage or value link."""
    _assert_model_and_loader_refuse(
        artifacts.VerifiedExportManifest,
        artifacts.validate_verified_export_manifest,
        _manifest(**{forbidden_field: 'private-sentinel'}),
    )


def test_verified_export_manifest_keeps_validation_diagnostics_value_free() -> None:
    """Invalid cross-plane metadata cannot survive any Pydantic error projection."""
    sentinel = 'private-sentinel-invalid.exe'

    with pytest.raises(ValidationError) as caught:
        artifacts.VerifiedExportManifest.model_validate(_manifest(public_filename=sentinel))

    for projection in (
        str(caught.value),
        repr(caught.value),
        repr(caught.value.errors()),
        caught.value.json(),
    ):
        assert sentinel not in projection
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_publication_request_keeps_operation_correlation_and_proof_receipt_distinct() -> None:
    """One identifier cannot impersonate publication, correlation, and proof evidence."""
    payload = {
        'schema_version': 'verified-export-publication-v1',
        'operation_id': 'publication_operation_0001',
        'manifest': _manifest(),
    }
    parsed = artifacts.VerifiedExportPublicationRequest.model_validate(payload)
    assert artifacts.validate_verified_export_publication_request(payload) == parsed

    for conflated in ('export_correlation_0001', 'proof_receipt_0001'):
        _assert_model_and_loader_refuse(
            artifacts.VerifiedExportPublicationRequest,
            artifacts.validate_verified_export_publication_request,
            {**payload, 'operation_id': conflated},
        )

    conflated_manifest = _manifest(proof_receipt_id='export_correlation_0001')
    _assert_model_and_loader_refuse(
        artifacts.VerifiedExportPublicationRequest,
        artifacts.validate_verified_export_publication_request,
        {**payload, 'manifest': conflated_manifest},
    )


def test_internal_publication_outcome_keeps_the_deletion_ref_out_of_public_receipt() -> None:
    """Only the internal outcome carries the resolvable ordinary deletion reference."""
    payload = {
        'receipt': _public_receipt(),
        'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
    }
    parsed = artifacts.VerifiedExportPublicationOutcome.model_validate(payload)

    assert artifacts.validate_verified_export_publication_outcome(payload) == parsed
    assert parsed.model_dump(mode='json', exclude_none=True) == payload
    assert 'ordinary_deletion_ref' not in parsed.receipt.model_dump(mode='json')
    assert set(artifacts.RedactedExportReceipt.model_fields) == {
        'receipt_id',
        'ordinary_artifact',
        'correlation_id',
        'occurred_at',
    }


@pytest.mark.parametrize(
    'conflated_ref',
    [
        'publication_receipt_0001',
        'export_correlation_0001',
        'ordinary_artifact_0001',
        'logical_output_0001',
        'validation_receipt_0001',
    ],
)
def test_internal_publication_outcome_ref_is_distinct_from_every_public_identity(
    conflated_ref: str,
) -> None:
    """The maintenance capability cannot be reconstructed from a public identifier."""
    _assert_model_and_loader_refuse(
        artifacts.VerifiedExportPublicationOutcome,
        artifacts.validate_verified_export_publication_outcome,
        {'receipt': _public_receipt(), 'ordinary_deletion_ref': conflated_ref},
    )


def test_public_redacted_receipt_keeps_its_identity_roles_separate() -> None:
    """Publication, correlation, artifact, logical-output, and validation IDs cannot alias."""
    identities = (
        'export_correlation_0001',
        'ordinary_artifact_0001',
        'logical_output_0001',
        'validation_receipt_0001',
    )
    for conflated in identities:
        with pytest.raises(ValidationError):
            artifacts.RedactedExportReceipt.model_validate(
                _public_receipt(receipt_id=conflated),
            )


def test_ordinary_export_deletion_requests_keep_ref_manifest_and_receipt_separate() -> None:
    """Delete idempotency and status correlation use three noninterchangeable handles."""
    request = {
        'schema_version': 'ordinary-export-deletion-request-v1',
        'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
        'deletion_manifest_id': 'deletion_manifest_0001',
    }
    status = {
        'schema_version': 'ordinary-export-deletion-status-request-v1',
        'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
        'deletion_receipt_id': 'deletion_receipt_0001',
    }

    assert (
        artifacts.validate_ordinary_export_deletion_request(request).model_dump(mode='json')
        == request
    )
    assert (
        artifacts.validate_ordinary_export_deletion_status_request(status).model_dump(mode='json')
        == status
    )

    _assert_model_and_loader_refuse(
        artifacts.OrdinaryExportDeletionRequest,
        artifacts.validate_ordinary_export_deletion_request,
        {**request, 'deletion_manifest_id': request['ordinary_deletion_ref']},
    )
    _assert_model_and_loader_refuse(
        artifacts.OrdinaryExportDeletionStatusRequest,
        artifacts.validate_ordinary_export_deletion_status_request,
        {**status, 'deletion_receipt_id': status['ordinary_deletion_ref']},
    )


@pytest.mark.parametrize(
    ('state', 'classification'),
    [
        ('requested', 'pending'),
        ('draining', 'pending'),
        ('deleting', 'pending'),
        ('delete_incomplete', 'pending'),
        ('deleted', 'terminal'),
    ],
)
def test_ordinary_export_deletion_receipt_closes_state_and_terminal_classification(
    state: str,
    classification: str,
) -> None:
    """Only deleted is terminal; incomplete deletion remains an accepted pending receipt."""
    payload = {
        'schema_version': 'ordinary-export-deletion-receipt-v1',
        'receipt_id': 'deletion_receipt_0001',
        'state': state,
        'updated_at': _NOW,
    }
    parsed = artifacts.validate_ordinary_export_deletion_receipt(payload)

    assert parsed.state == state
    assert ('terminal' if parsed.state == 'deleted' else 'pending') == classification


@pytest.mark.parametrize(
    'forbidden_field',
    [
        'artifact_id',
        'scope',
        'public_filename',
        'content_length',
        'content_sha256',
        'operation_id',
        'deletion_manifest_id',
        'ordinary_deletion_ref',
        'provider_detail',
    ],
)
def test_ordinary_export_deletion_receipt_never_echoes_request_or_artifact_values(
    forbidden_field: str,
) -> None:
    """A maintenance receipt exposes only its stable ID, state, and update time."""
    payload: dict[str, object] = {
        'schema_version': 'ordinary-export-deletion-receipt-v1',
        'receipt_id': 'deletion_receipt_0001',
        'state': 'delete_incomplete',
        'updated_at': _NOW,
        forbidden_field: 'private-sentinel',
    }
    _assert_model_and_loader_refuse(
        artifacts.OrdinaryExportDeletionReceipt,
        artifacts.validate_ordinary_export_deletion_receipt,
        payload,
    )


def test_task5_models_are_frozen_closed_and_value_free_in_diagnostics() -> None:
    """Logging a cross-service object cannot project filename, digest, IDs, or nested receipt."""
    instances = (
        artifacts.VerifiedExportManifest.model_validate(_manifest()),
        artifacts.VerifiedExportPublicationRequest.model_validate(
            {
                'schema_version': 'verified-export-publication-v1',
                'operation_id': 'publication_operation_0001',
                'manifest': _manifest(),
            }
        ),
        artifacts.VerifiedExportPublicationOutcome.model_validate(
            {
                'receipt': _public_receipt(),
                'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
            }
        ),
        artifacts.OrdinaryExportDeletionRequest.model_validate(
            {
                'schema_version': 'ordinary-export-deletion-request-v1',
                'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
                'deletion_manifest_id': 'deletion_manifest_0001',
            }
        ),
        artifacts.OrdinaryExportDeletionStatusRequest.model_validate(
            {
                'schema_version': 'ordinary-export-deletion-status-request-v1',
                'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
                'deletion_receipt_id': 'deletion_receipt_0001',
            }
        ),
        artifacts.OrdinaryExportDeletionReceipt.model_validate(
            {
                'schema_version': 'ordinary-export-deletion-receipt-v1',
                'receipt_id': 'deletion_receipt_0001',
                'state': 'requested',
                'updated_at': _NOW,
            }
        ),
    )
    sentinels = (
        'safe-export.pdf',
        'a' * 64,
        'export_correlation_0001',
        'ordinary_deletion_ref_0001',
        'publication_receipt_0001',
    )

    for instance in instances:
        rendered = f'{instance!s} {instance!r}'
        assert all(sentinel not in rendered for sentinel in sentinels)
        with pytest.raises(ValidationError):
            type(instance).model_validate({**instance.model_dump(mode='json'), 'extra': 'no'})
        with pytest.raises(ValidationError):
            setattr(instance, next(iter(type(instance).model_fields)), 'changed')


def test_task5_stored_schema_set_is_closed_and_loader_owned() -> None:
    """Every generated consumer derives from one checked-in schema with exact fields."""
    schemas = {
        'verified_export_manifest': (
            artifacts.load_verified_export_manifest_schema(),
            set(artifacts.VerifiedExportManifest.model_fields),
        ),
        'verified_export_publication_request': (
            artifacts.load_verified_export_publication_request_schema(),
            set(artifacts.VerifiedExportPublicationRequest.model_fields),
        ),
        'verified_export_publication_outcome': (
            artifacts.load_verified_export_publication_outcome_schema(),
            set(artifacts.VerifiedExportPublicationOutcome.model_fields),
        ),
        'ordinary_export_deletion_request': (
            artifacts.load_ordinary_export_deletion_request_schema(),
            set(artifacts.OrdinaryExportDeletionRequest.model_fields),
        ),
        'ordinary_export_deletion_status_request': (
            artifacts.load_ordinary_export_deletion_status_request_schema(),
            set(artifacts.OrdinaryExportDeletionStatusRequest.model_fields),
        ),
        'ordinary_export_deletion_receipt': (
            artifacts.load_ordinary_export_deletion_receipt_schema(),
            set(artifacts.OrdinaryExportDeletionReceipt.model_fields),
        ),
    }

    for schema_name, (schema, fields) in schemas.items():
        assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
        assert schema['$id'].endswith(f'/{schema_name}.schema.json')
        assert schema['additionalProperties'] is False
        assert set(schema['properties']) == fields
        assert set(schema['required']) == fields

    manifest_schema = schemas['verified_export_manifest'][0]
    assert manifest_schema['properties']['content_length'] == {
        'type': 'integer',
        'minimum': 1,
        'maximum': _MAX_EXPORT_BYTES,
    }
    receipt_schema = schemas['ordinary_export_deletion_receipt'][0]
    assert receipt_schema['properties']['state']['enum'] == [
        'requested',
        'draining',
        'deleting',
        'delete_incomplete',
        'deleted',
    ]


def test_task5_model_fields_are_exactly_the_approved_wire() -> None:
    """A generated consumer may not gain an authority or private-linkage field."""
    assert set(artifacts.VerifiedExportManifest.model_fields) == {
        'schema_version',
        'scope',
        'surface',
        'correlation_id',
        'artifact_kind',
        'mime_type',
        'public_filename',
        'content_length',
        'content_sha256',
        'proof_receipt_id',
    }
    assert set(artifacts.VerifiedExportPublicationRequest.model_fields) == {
        'schema_version',
        'operation_id',
        'manifest',
    }
    assert set(artifacts.VerifiedExportPublicationOutcome.model_fields) == {
        'receipt',
        'ordinary_deletion_ref',
    }
    assert set(artifacts.OrdinaryExportDeletionRequest.model_fields) == {
        'schema_version',
        'ordinary_deletion_ref',
        'deletion_manifest_id',
    }
    assert set(artifacts.OrdinaryExportDeletionStatusRequest.model_fields) == {
        'schema_version',
        'ordinary_deletion_ref',
        'deletion_receipt_id',
    }
    assert set(artifacts.OrdinaryExportDeletionReceipt.model_fields) == {
        'schema_version',
        'receipt_id',
        'state',
        'updated_at',
    }


def test_task5_models_reject_missing_required_fields() -> None:
    """No cross-plane message may default an identity, proof, or lifecycle state."""
    cases = (
        (artifacts.VerifiedExportManifest, _manifest()),
        (
            artifacts.VerifiedExportPublicationRequest,
            {
                'schema_version': 'verified-export-publication-v1',
                'operation_id': 'publication_operation_0001',
                'manifest': _manifest(),
            },
        ),
        (
            artifacts.VerifiedExportPublicationOutcome,
            {'receipt': _public_receipt(), 'ordinary_deletion_ref': 'ordinary_deletion_ref_0001'},
        ),
        (
            artifacts.OrdinaryExportDeletionRequest,
            {
                'schema_version': 'ordinary-export-deletion-request-v1',
                'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
                'deletion_manifest_id': 'deletion_manifest_0001',
            },
        ),
        (
            artifacts.OrdinaryExportDeletionStatusRequest,
            {
                'schema_version': 'ordinary-export-deletion-status-request-v1',
                'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
                'deletion_receipt_id': 'deletion_receipt_0001',
            },
        ),
        (
            artifacts.OrdinaryExportDeletionReceipt,
            {
                'schema_version': 'ordinary-export-deletion-receipt-v1',
                'receipt_id': 'deletion_receipt_0001',
                'state': 'requested',
                'updated_at': _NOW,
            },
        ),
    )

    for model, payload in cases:
        for field in tuple(payload):
            missing = deepcopy(payload)
            del missing[field]
            with pytest.raises(ValidationError):
                model.model_validate(missing)
