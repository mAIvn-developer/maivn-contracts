"""Proof-bound output and editable-source commitments for direct Vault intake."""

import importlib
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from maivn_contracts.artifacts import (
    VaultFileIntakeManifest,
    VaultWorkRequest,
    validate_vault_work_request,
)


def test_private_generic_file_intake_requires_opaque_download_identity() -> None:
    """New formats reuse the generic route without adding MIME types or renderers."""
    payload = {
        'kind': 'other',
        'mime_type': 'application/octet-stream',
        'output_commitment': 'b' * 64,
        'source_commitment': 'c' * 64,
        'max_source_bytes': 1024,
    }
    manifest = VaultFileIntakeManifest.model_validate(payload)
    assert manifest.kind == 'other'
    for mime in ('image/png', 'application/pdf', 'text/html'):
        with pytest.raises(ValidationError):
            VaultFileIntakeManifest.model_validate({**payload, 'mime_type': mime})


def test_private_file_intake_commitments_bind_part_proof_and_content() -> None:
    """The same file cannot be substituted across parts or another upload proof."""
    artifacts = importlib.import_module('maivn_contracts.artifacts')
    assert hasattr(artifacts, 'vault_file_intake_commitment'), (
        'direct private file intake is missing'
    )
    commit = artifacts.vault_file_intake_commitment
    proof = 'cHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHA'
    payload = b'private file content'
    first = commit(proof, 'private_original', payload)
    assert first == commit(proof, 'private_original', payload)
    assert first != commit(proof, 'editable_source', payload)
    assert first != commit(proof, 'private_original', payload + b'changed')
    other_proof = 'cXFxcXFxcXFxcXFxcXFxcXFxcXFxcXFxcXFxcXFxcXE'
    assert first != commit(other_proof, 'private_original', payload)
    with pytest.raises(ValueError, match=r'.'):
        commit('invalid', 'private_original', payload)


@pytest.mark.parametrize(
    ('kind', 'mime_type'),
    [('document', 'application/pdf'), ('other', 'application/octet-stream')],
)
def test_ingest_work_uses_exact_file_commitments_without_legacy_plan_or_value_map(
    kind: str,
    mime_type: str,
) -> None:
    """Local generated files have their own canonical work operation."""
    work = VaultWorkRequest.model_validate(
        {
            'schema_version': 'vault-work-v1',
            'intent_id': 'intake',
            'idempotency_key': 'retry',
            'operation': 'ingest_file',
            'scope': {'organization_id': 'org', 'project_id': 'project'},
            'surface': {
                'root_invocation_id': 'root',
                'session_id': 'session',
                'checkpoint_id': 'checkpoint',
                'caller_id': 'caller',
            },
            'input_handles': [],
            'bounds': {'max_output_bytes': 1048576},
            'retention_policy_id': 'policy',
            'client_proof_digest': 'a' * 64,
            'expires_at': '2030-01-01T00:00:00Z',
            'file_intake': {
                'kind': kind,
                'mime_type': mime_type,
                'output_commitment': 'b' * 64,
                'source_commitment': 'c' * 64,
                'max_source_bytes': 1048576,
            },
        }
    )
    assert work.operation == 'ingest_file'
    assert work.plan is None
    assert work.value_map_handle is None

    assert validate_vault_work_request(work.model_dump(mode='json', exclude_none=True)) == work
    payload = work.model_dump(mode='json', exclude_none=True)
    for field in ['client_proof_digest', 'file_intake']:
        invalid = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(invalid)
        with pytest.raises((ValueError, SchemaValidationError)):
            validate_vault_work_request(invalid)
    for field in ['plan', 'value_map_handle', 'retrieval_part', 'export_filename']:
        invalid = {**payload, field: 'editable_source'}
        with pytest.raises(ValidationError):
            VaultWorkRequest.model_validate(invalid)
        with pytest.raises((ValueError, SchemaValidationError)):
            validate_vault_work_request(invalid)

    retrieval = {
        **payload,
        'operation': 'retrieve_session',
        'retrieval_part': 'editable_source',
        'input_handles': [
            {
                'local_id': 'source',
                'record_handle': 'logical',
                'generation_handle': 'generation',
                'role': 'source_artifact',
            }
        ],
    }
    retrieval.pop('file_intake')
    assert validate_vault_work_request(retrieval).retrieval_part == 'editable_source'
    deletion = {**retrieval, 'operation': 'delete', 'deletion_scope': {'mode': 'private_only'}}
    deletion.pop('client_proof_digest')
    with pytest.raises(ValidationError):
        VaultWorkRequest.model_validate(deletion)
    with pytest.raises((ValueError, SchemaValidationError)):
        validate_vault_work_request(deletion)


def test_ingest_work_schema_refuses_a_retrieval_part() -> None:
    """The schema, not only the model, keeps retrieval_part to retrieve_session."""
    request: dict[str, Any] = {
        'schema_version': 'vault-work-v1',
        'intent_id': 'intake',
        'idempotency_key': 'retry',
        'operation': 'ingest_file',
        'scope': {'organization_id': 'org', 'project_id': 'project'},
        'surface': {
            'root_invocation_id': 'root',
            'session_id': 'session',
            'checkpoint_id': 'checkpoint',
            'caller_id': 'caller',
        },
        'input_handles': [],
        'bounds': {'max_output_bytes': 1048576},
        'retention_policy_id': 'policy',
        'client_proof_digest': 'a' * 64,
        'expires_at': '2030-01-01T00:00:00Z',
        'file_intake': {
            'kind': 'document',
            'mime_type': 'application/pdf',
            'output_commitment': 'b' * 64,
            'source_commitment': 'c' * 64,
            'max_source_bytes': 1048576,
        },
    }
    assert validate_vault_work_request(request).operation == 'ingest_file'
    with pytest.raises(SchemaValidationError):
        validate_vault_work_request({**request, 'retrieval_part': 'editable_source'})
