# pyright: strict
"""Unit tests for pre-commit artifact reservation, intent, and error contracts."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

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
    ArtifactError,
    ArtifactPatch,
    ArtifactReservation,
    AudioArtifactPlan,
    ClientCapabilityHeader,
    DocumentArtifactPlan,
    ImageArtifactPlan,
    PrivateWorkIntentStatus,
    RedactedArtifactPayload,
    Sha256Hex,
    VaultActionTicket,
    VaultSenderAssertion,
    VaultWorkRequest,
    WorkbookArtifactPlan,
    canonical_http_request_bytes,
    load_artifact_error_schema,
    load_artifact_patch_schema,
    load_artifact_plan_schema,
    load_artifact_reservation_schema,
    load_private_work_intent_status_schema,
    validate_artifact_error,
    validate_artifact_patch,
    validate_artifact_reservation,
    validate_legacy_artifact_plan_v1_for_read_migration,
    validate_private_work_intent_status,
    validate_redacted_artifact_payload,
    vault_actual_request_digest_from_prehashed,
    vault_actual_request_digest_from_raw,
    vault_admission_fingerprint,
    vault_assertion_json_bytes,
    vault_assertion_signing_bytes,
    vault_client_proof_header_digest,
    vault_grant_header_digest,
    vault_grant_verifier,
    vault_operation_binding_digest,
    vault_retrieval_session_credential_digest,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ALL_CLIENT_CAPABILITY_HEADERS: frozenset[ClientCapabilityHeader] = frozenset(
    {
        GRANT_CREDENTIAL_HEADER,
        CLIENT_PROOF_HEADER,
        RETRIEVAL_SESSION_CREDENTIAL_HEADER,
    },
)
NO_CLIENT_CAPABILITY_HEADERS: frozenset[ClientCapabilityHeader] = frozenset()


def _artifact_refs() -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / 'valid_artifact_refs.json').read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def _finalized_reservation() -> dict[str, Any]:
    return {
        'reservation_id': 'reservation_0001',
        'organization_id': 'organization_0001',
        'project_id': 'project_0001',
        'root_invocation_id': 'invocation_0001',
        'producing_session_id': 'session_0001',
        'tool_call_id': 'call_0001',
        'dispatch_id': 'dispatch_0001',
        'attempt_id': 'attempt_0001',
        'producer': {
            'producer_class': 'hosted_tool',
            'producer_id': 'producer_0001',
            'root_invocation_id': 'invocation_0001',
            'session_id': 'session_0001',
            'call_id': 'call_0001',
            'dispatch_id': 'dispatch_0001',
            'attempt_id': 'attempt_0001',
        },
        'logical_output_id': 'out_report_0001',
        'allowed_kinds': ['document'],
        'allowed_mime_types': ['application/pdf'],
        'max_artifact_count': 1,
        'max_total_bytes': 52428800,
        'retention_policy_snapshot_id': 'retention_policy_0001',
        'idempotency_key': 'idempotency_0001',
        'expires_at': '2026-08-09T00:10:00Z',
        'state': 'finalized',
        'outcome': _artifact_refs()[0],
    }


def _committed_private_intent() -> dict[str, Any]:
    return {
        'intent_id': 'intent_0001',
        'operation': 'create',
        'correlation_id': 'correlation_0001',
        'idempotency_key': 'idempotency_0001',
        'expires_at': '2026-08-09T00:10:00Z',
        'state': 'committed',
        'artifact': _artifact_refs()[1],
    }


def test_finalized_reservation_and_committed_intent_expose_only_immutable_outcomes() -> None:
    """A missing terminal-outcome guard would expose mutable or cross-custody artifacts."""
    reservation = _finalized_reservation()
    intent = _committed_private_intent()

    assert (
        validate_artifact_reservation(reservation).model_dump(mode='json', exclude_none=True)
        == reservation
    )
    assert (
        validate_private_work_intent_status(intent).model_dump(mode='json', exclude_none=True)
        == intent
    )


@pytest.mark.parametrize(
    ('factory', 'validator', 'model', 'changes'),
    [
        (
            _finalized_reservation,
            validate_artifact_reservation,
            ArtifactReservation,
            {'state': 'uploading'},
        ),
        (
            _finalized_reservation,
            validate_artifact_reservation,
            ArtifactReservation,
            {'outcome': _artifact_refs()[1]},
        ),
        (
            _committed_private_intent,
            validate_private_work_intent_status,
            PrivateWorkIntentStatus,
            {'state': 'executing_in_vault'},
        ),
        (
            _committed_private_intent,
            validate_private_work_intent_status,
            PrivateWorkIntentStatus,
            {'artifact': _artifact_refs()[0]},
        ),
    ],
)
def test_terminal_outcomes_are_required_only_for_the_matching_custody_and_state(
    factory: Any,
    validator: Any,
    model: Any,
    changes: dict[str, Any],
) -> None:
    """A wrong terminal branch would manufacture an invalid artifact outcome."""
    payload = deepcopy(factory())
    payload.update(changes)

    with pytest.raises(ValidationError):
        validator(payload)
    with pytest.raises(PydanticValidationError):
        model.model_validate(payload)


def test_precommit_contracts_forbid_direct_artifact_ids_and_error_is_value_free() -> None:
    """A leaked identifier or error text would disclose pre-commit private state."""
    reservation = _finalized_reservation()
    reservation['artifact_id'] = 'artifact_0001'
    intent = _committed_private_intent()
    intent['artifact_id'] = 'artifact_private_0001'

    with pytest.raises(ValidationError):
        validate_artifact_reservation(reservation)
    with pytest.raises(ValidationError):
        validate_private_work_intent_status(intent)

    error = ArtifactError(
        code='artifact_storage_unavailable', error_class='availability', retryable=True
    )
    assert error.error_class == 'availability'
    assert error.retryable is True
    with pytest.raises(PydanticValidationError):
        ArtifactError.model_validate(
            {'code': 'artifact_storage_unavailable', 'message': 'provider timeout'},
        )


def test_artifact_error_code_pins_its_value_free_class_and_retryability() -> None:
    """A mismatched error triple would cause clients to retry the wrong failure class."""
    valid = {
        'code': 'artifact_storage_unavailable',
        'error_class': 'availability',
        'retryable': True,
    }
    mismatch = {**valid, 'retryable': False}
    missing = {'code': 'artifact_storage_unavailable', 'error_class': 'availability'}

    assert validate_artifact_error(valid).model_dump(mode='json') == valid
    for payload in (mismatch, missing):
        with pytest.raises(ValidationError):
            validate_artifact_error(payload)
        with pytest.raises(PydanticValidationError):
            ArtifactError.model_validate(payload)


@pytest.mark.parametrize(
    ('kind', 'mime_type'),
    [
        ('document', 'image/png'),
        ('spreadsheet', 'application/pdf'),
        ('image', 'audio/mpeg'),
        ('audio', 'application/octet-stream'),
        ('other', 'image/jpeg'),
    ],
)
def test_reservation_allowlisted_mimes_require_the_matching_kind(kind: str, mime_type: str) -> None:
    """A mismatched reservation allowlist would grant an unauthorized output type."""
    payload = _finalized_reservation()
    payload['allowed_kinds'] = [kind]
    payload['allowed_mime_types'] = [mime_type]
    payload['state'] = 'reserved'
    payload.pop('outcome')

    with pytest.raises(ValidationError):
        validate_artifact_reservation(payload)
    with pytest.raises(PydanticValidationError):
        ArtifactReservation.model_validate(payload)


def test_redacted_payload_requires_stable_fragments_and_canonical_placeholders() -> None:
    """A permissive payload would admit malformed placeholders or opaque extensions."""
    payload = {
        'fragments': [
            {'structural_id': 'paragraph_1', 'text': 'Hello {_{customer_name}_}.'},
            {'structural_id': 'paragraph_2', 'text': 'Public summary.'},
        ],
    }

    assert validate_redacted_artifact_payload(payload).model_dump(mode='json') == payload
    with pytest.raises(ValidationError):
        validate_redacted_artifact_payload(
            {'fragments': [{'structural_id': 'paragraph_1', 'text': '{_{bad value}_}'}]},
        )


def test_closed_document_plan_and_patch_allow_only_typed_structural_operations() -> None:
    """An open plan or patch would permit unredacted content or path/value operations."""
    plan: dict[str, Any] = {
        'schema_version': 'v1',
        'kind': 'document',
        'logical_output_name': 'report',
        'custody_request': 'ordinary',
        'content': {'fragments': [{'structural_id': 'p1', 'text': 'Hello'}]},
        'input_refs': [],
        'renderer_profile': 'document_renderer',
        'renderer_min_version': '1.0',
        'output_mime_type': 'application/pdf',
        'validation_profile': 'document_default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {'max_output_bytes': 1024, 'max_pages': 1},
    }
    patch = {
        'schema_version': 'v1',
        'target_artifact_id': 'art_ordinary_0001',
        'base_revision': 1,
        'expected_output_kind': 'document',
        'renderer_profile': 'document_renderer',
        'rationale': {'fragments': [{'structural_id': 'reason_1', 'text': 'Correct typo'}]},
        'operations': [
            {
                'op': 'replace_text',
                'target_id': 'p1',
                'payload': {'fragments': [{'structural_id': 'p1_text', 'text': 'Hi'}]},
            }
        ],
    }

    assert isinstance(
        validate_legacy_artifact_plan_v1_for_read_migration(plan), DocumentArtifactPlan
    )
    assert validate_artifact_patch(patch).model_dump(mode='json', exclude_none=True) == patch
    with pytest.raises(ValidationError):
        validate_artifact_patch(
            {**patch, 'operations': [{'op': 'replace_text', 'path': '/p1', 'value': 'leak'}]}
        )
    with pytest.raises(PydanticValidationError):
        ArtifactPatch.model_validate({**patch, 'base_revision': 0})
    with pytest.raises(PydanticValidationError):
        RedactedArtifactPayload.model_validate(
            {'fragments': [{'structural_id': 'paragraph_1', 'text': 'ok'}], 'metadata': {}},
        )


@pytest.mark.parametrize(
    ('factory', 'validator', 'model', 'state'),
    [
        *[
            (_finalized_reservation, validate_artifact_reservation, ArtifactReservation, state)
            for state in ('reserved', 'uploading', 'validating', 'rejected', 'expired', 'failed')
        ],
        *[
            (
                _committed_private_intent,
                validate_private_work_intent_status,
                PrivateWorkIntentStatus,
                state,
            )
            for state in (
                'planned',
                'authorization_pending',
                'executing_in_vault',
                'authorization_denied',
                'grant_expired',
                'failed',
            )
        ],
    ],
)
def test_nonterminal_precommit_states_forbid_an_outcome(
    factory: Any, validator: Any, model: Any, state: str
) -> None:
    """A nonterminal outcome would manufacture an immutable artifact before commit."""
    payload = factory()
    payload['state'] = state
    with pytest.raises(ValidationError):
        validator(payload)
    with pytest.raises(PydanticValidationError):
        model.model_validate(payload)
    payload.pop('outcome' if 'outcome' in payload else 'artifact')
    assert validator(payload).state == state
    assert model.model_validate(payload).state == state


@pytest.mark.parametrize(
    ('factory', 'validator', 'model'),
    [
        (_finalized_reservation, validate_artifact_reservation, ArtifactReservation),
        (_committed_private_intent, validate_private_work_intent_status, PrivateWorkIntentStatus),
    ],
)
def test_terminal_precommit_states_require_an_outcome(
    factory: Any, validator: Any, model: Any
) -> None:
    """A terminal success missing its immutable result would be unrecoverable."""
    payload = factory()
    payload.pop('outcome' if 'outcome' in payload else 'artifact')
    with pytest.raises(ValidationError):
        validator(payload)
    with pytest.raises(PydanticValidationError):
        model.model_validate(payload)


def _plan(kind: str = 'document', mime: str = 'application/pdf') -> dict[str, Any]:
    return {
        'schema_version': 'v1',
        'kind': kind,
        'logical_output_name': 'report',
        'custody_request': 'ordinary',
        'content': {'fragments': [{'structural_id': 'p1', 'text': 'Hello'}]},
        'input_refs': [],
        'renderer_profile': 'renderer',
        'renderer_min_version': '1.0',
        'output_mime_type': mime,
        'validation_profile': 'default',
        'disposition': 'final',
        'retention_request': {'retention_class': 'invocation_artifact_30d'},
        'resource_bounds': {'max_output_bytes': 1, 'max_cells': 1},
    }


@pytest.mark.parametrize(
    ('kind', 'mime', 'wrong_mime'),
    [
        ('document', 'application/pdf', 'image/png'),
        (
            'spreadsheet',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'audio/wav',
        ),
        ('image', 'image/png', 'application/pdf'),
        ('audio', 'audio/mpeg', 'image/jpeg'),
    ],
)
def test_every_plan_variant_pins_its_output_mime(kind: str, mime: str, wrong_mime: str) -> None:
    """A variant MIME mismatch would dispatch bytes to the wrong renderer/validator."""
    valid = _plan(kind, mime)
    invalid = _plan(kind, wrong_mime)
    assert validate_legacy_artifact_plan_v1_for_read_migration(valid).kind == kind
    with pytest.raises(ValidationError):
        validate_legacy_artifact_plan_v1_for_read_migration(invalid)
    model = {
        'document': DocumentArtifactPlan,
        'spreadsheet': WorkbookArtifactPlan,
        'image': ImageArtifactPlan,
        'audio': AudioArtifactPlan,
    }[kind]
    with pytest.raises(PydanticValidationError):
        model.model_validate(invalid)


@pytest.mark.parametrize(
    'input_ref',
    [
        {'ref_type': 'artifact', 'artifact_id': 'art_1', 'revision': 1},
        {'ref_type': 'resource', 'resource_id': 'resource_1', 'revision': 1},
        {'ref_type': 'template', 'template_id': 'template_1', 'revision': 1},
    ],
)
def test_plan_input_refs_are_closed_and_discriminated(input_ref: dict[str, Any]) -> None:
    """An untagged or extended input ref would make source provenance ambiguous."""
    valid = _plan()
    valid['input_refs'] = [input_ref]
    assert validate_legacy_artifact_plan_v1_for_read_migration(valid).input_refs
    invalid = _plan()
    invalid['input_refs'] = [{'artifact_id': 'art_1', 'revision': 1, 'path': 'private'}]
    with pytest.raises(ValidationError):
        validate_legacy_artifact_plan_v1_for_read_migration(invalid)
    with pytest.raises(PydanticValidationError):
        DocumentArtifactPlan.model_validate(invalid)


def test_plan_patch_composition_preserves_redaction_and_typed_operation_boundaries() -> None:
    """Open text or nonpositive resource bounds would bypass the shared contract boundary."""
    plan = _plan()
    plan['content'] = {'fragments': [{'structural_id': 'p1', 'text': '{_{customer}_}'}]}
    patch: dict[str, Any] = {
        'schema_version': 'v1',
        'target_artifact_id': 'art_1',
        'base_revision': 1,
        'expected_output_kind': 'document',
        'renderer_profile': 'renderer',
        'rationale': {'fragments': [{'structural_id': 'r1', 'text': 'reason'}]},
        'operations': [
            {
                'op': 'replace_text',
                'target_id': 'p1',
                'payload': {'fragments': [{'structural_id': 'a', 'text': 'a'}]},
            },
            {
                'op': 'insert_after',
                'anchor_id': 'p1',
                'payload': {'fragments': [{'structural_id': 'b', 'text': 'b'}]},
            },
            {'op': 'remove_element', 'target_id': 'p2'},
        ],
    }
    projected_plan = validate_legacy_artifact_plan_v1_for_read_migration(plan)
    assert isinstance(projected_plan, DocumentArtifactPlan)
    assert projected_plan.content.fragments[0].structural_id == 'p1'
    operation_count = 3
    assert len(validate_artifact_patch(patch).operations) == operation_count
    invalid_plans: tuple[dict[str, Any], ...] = (
        {**_plan(), 'resource_bounds': {'max_output_bytes': 1, 'max_cells': True}},
        {**_plan(), 'resource_bounds': {'max_output_bytes': 1, 'max_cells': 0}},
        {**_plan(), 'content': {'fragments': [{'structural_id': 'p1', 'text': '{_{bad value}_}'}]}},
    )
    invalid_patches: tuple[dict[str, Any], ...] = (
        {
            **patch,
            'rationale': {'fragments': [{'structural_id': 'r1', 'text': 'ok'}], 'metadata': {}},
        },
        {**patch, 'operations': [{'op': 'replace_text', 'path': '/p1', 'value': 'raw'}]},
        {**patch, 'rationale': 'raw private rationale'},
        {**patch, 'rationale': {'fragments': [{'structural_id': 'r1', 'text': '{_{bad value}_}'}]}},
    )
    for invalid in invalid_plans:
        with pytest.raises(ValidationError):
            validate_legacy_artifact_plan_v1_for_read_migration(invalid)
        with pytest.raises(PydanticValidationError):
            DocumentArtifactPlan.model_validate(invalid)
    for invalid in invalid_patches:
        with pytest.raises(ValidationError):
            validate_artifact_patch(invalid)
        with pytest.raises(PydanticValidationError):
            ArtifactPatch.model_validate(invalid)


def _vault_protocol_vectors() -> dict[str, Any]:
    loaded = json.loads(
        (FIXTURES_DIR / 'vault_protocol_golden_vectors.json').read_text(encoding='utf-8'),
    )
    assert isinstance(loaded, dict)
    return cast('dict[str, Any]', loaded)


def test_vault_protocol_shared_golden_vectors_pin_every_domain() -> None:
    """A producer-specific canonicalizer would split Data Plane, Contracts, and Vault trust."""
    vector = _vault_protocol_vectors()
    request = cast('dict[str, Any]', vector['http_request'])
    body = cast('str', request['body_utf8']).encode()
    public_headers = cast('dict[str, str]', request['public_headers'])
    client_header_digests = cast(
        'dict[ClientCapabilityHeader, Sha256Hex]',
        request['client_header_digests'],
    )
    actual_headers = cast('dict[str, str]', request['actual_headers'])
    assertion = VaultSenderAssertion.model_validate(vector['assertion'])
    work = VaultWorkRequest.model_validate(vector['work'])
    identity = cast('dict[str, str]', vector['identity'])
    stored = cast('dict[str, Any]', vector['stored_intent'])
    capabilities = cast('dict[str, str]', vector['capabilities'])
    transport = cast('dict[str, str]', vector['ticket_transport'])

    assert GRANT_CREDENTIAL_HEADER == 'x-maivn-grant-credential'
    assert CLIENT_PROOF_HEADER == 'x-maivn-client-proof'
    assert RETRIEVAL_SESSION_ID_HEADER == 'x-maivn-session-id'
    assert RETRIEVAL_SESSION_CREDENTIAL_HEADER == 'x-maivn-session-credential'
    assert EXPORT_FILENAME_HEADER == 'x-maivn-export-filename'
    assert OPERATION_ID_HEADER == 'x-maivn-operation-id'
    assert (
        frozenset(
            {
                'content-type',
                'range',
                OPERATION_ID_HEADER,
                SENDER_ASSERTION_HEADER,
                SENDER_SIGNATURE_HEADER,
                GRANT_CREDENTIAL_HEADER,
                CLIENT_PROOF_HEADER,
                RETRIEVAL_SESSION_ID_HEADER,
                RETRIEVAL_SESSION_CREDENTIAL_HEADER,
                EXPORT_FILENAME_HEADER,
            },
        )
        == BROWSER_TICKET_REQUEST_HEADERS
    )
    canonical = canonical_http_request_bytes(
        request['method'],
        request['path'],
        body,
        public_headers,
        client_header_digests,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )
    assert canonical == cast('str', request['canonical_utf8']).encode()
    assert (
        vault_actual_request_digest_from_prehashed(
            request['method'],
            request['path'],
            body,
            public_headers,
            client_header_digests,
            expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
        )
        == request['actual_request_digest']
    )
    assert (
        vault_actual_request_digest_from_raw(
            request['method'],
            request['path'],
            body,
            actual_headers,
            expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
        )
        == request['actual_request_digest']
    )
    assert (
        vault_assertion_json_bytes(assertion)
        == cast(
            'str',
            vector['assertion_json_utf8'],
        ).encode()
    )
    expected_signing = cast('str', vector['assertion_signing_base64url'])
    expected_signing += '=' * (-len(expected_signing) % 4)
    assert vault_assertion_signing_bytes(assertion) == base64.urlsafe_b64decode(expected_signing)
    ticket = VaultActionTicket.model_validate(
        {
            'method': 'POST',
            'path': request['path'],
            'url': f'https://vault.example{request["path"]}',
            'public_headers': public_headers,
            'client_header_digests': client_header_digests,
            'sender_assertion_base64url': transport['sender_assertion_base64url'],
            'sender_signature_base64url': transport['sender_signature_base64url'],
            'body_base64url': transport['body_base64url'],
            'expires_at': '2026-08-11T12:00:00Z',
        },
    )
    ticket.require_client_header_digests(ALL_CLIENT_CAPABILITY_HEADERS)
    assertion_transport = transport['sender_assertion_base64url']
    assertion_transport += '=' * (-len(assertion_transport) % 4)
    assert base64.urlsafe_b64decode(assertion_transport) == vault_assertion_json_bytes(assertion)
    signature_transport = transport['sender_signature_base64url']
    signature_transport += '=' * (-len(signature_transport) % 4)
    assert base64.urlsafe_b64decode(signature_transport) == bytes(range(64))
    body_transport = transport['body_base64url']
    body_transport += '=' * (-len(body_transport) % 4)
    assert base64.urlsafe_b64decode(body_transport) == bytes.fromhex(transport['body_hex'])
    assert vault_admission_fingerprint(work, **identity) == vector['admission_fingerprint']
    assert _operation_binding_digest(stored) == cast(
        'str',
        vector['operation_binding_digest'],
    )
    assert (
        vault_grant_header_digest(capabilities['grant_credential'])
        == capabilities['grant_header_digest']
    )
    assert (
        vault_client_proof_header_digest(capabilities['client_proof'])
        == capabilities['client_proof_digest']
    )
    assert (
        vault_retrieval_session_credential_digest(
            capabilities['session_credential'],
        )
        == capabilities['session_credential_digest']
    )
    assert (
        vault_grant_verifier(
            capabilities['grant_credential'],
            bytes.fromhex(capabilities['grant_salt_hex']),
        )
        == capabilities['grant_verifier']
    )


def test_action_ticket_preserves_arbitrary_exact_body_bytes() -> None:
    """The generic ticket envelope must bind bytes without guessing at body content."""
    vector = _vault_protocol_vectors()
    request = cast('dict[str, Any]', vector['http_request'])
    public_headers = cast('dict[str, str]', request['public_headers'])
    client_header_digests = cast(
        'dict[ClientCapabilityHeader, Sha256Hex]',
        request['client_header_digests'],
    )
    body = b'\x00\x01\xff'
    assertion_payload = {
        **cast('dict[str, str]', vector['assertion']),
        'actual_request_digest': vault_actual_request_digest_from_prehashed(
            'POST',
            request['path'],
            body,
            public_headers,
            client_header_digests,
            expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
        ),
    }
    assertion = VaultSenderAssertion.model_validate(assertion_payload)
    assertion_base64url = (
        base64.urlsafe_b64encode(
            vault_assertion_json_bytes(assertion),
        )
        .rstrip(b'=')
        .decode('ascii')
    )
    transport = cast('dict[str, str]', vector['ticket_transport'])
    ticket = VaultActionTicket.model_validate(
        {
            'method': 'POST',
            'path': request['path'],
            'url': f'https://vault.example{request["path"]}',
            'public_headers': public_headers,
            'client_header_digests': client_header_digests,
            'sender_assertion_base64url': assertion_base64url,
            'sender_signature_base64url': transport['sender_signature_base64url'],
            'body_base64url': 'AAH_',
            'expires_at': assertion.expires_at,
        },
    )

    assert ticket.body_base64url == 'AAH_'


def test_canonical_request_binds_raw_target_body_headers_and_excludes_envelope() -> None:
    """Any normalized or recursively signed request representation would authorize other bytes."""
    request = cast('dict[str, Any]', _vault_protocol_vectors()['http_request'])
    method = cast('str', request['method'])
    path = cast('str', request['path'])
    body = cast('str', request['body_utf8']).encode()
    public_headers = cast('dict[str, str]', request['public_headers'])
    client_header_digests = cast(
        'dict[ClientCapabilityHeader, Sha256Hex]',
        request['client_header_digests'],
    )
    actual_headers = cast('dict[str, str]', request['actual_headers'])
    canonical = canonical_http_request_bytes(
        method,
        path,
        body,
        public_headers,
        client_header_digests,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )
    digest = vault_actual_request_digest_from_prehashed(
        method,
        path,
        body,
        public_headers,
        client_header_digests,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )

    capabilities = cast('dict[str, str]', _vault_protocol_vectors()['capabilities'])
    for raw_name in ('grant_credential', 'client_proof', 'session_credential'):
        assert capabilities[raw_name].encode() not in canonical
    assert b'excluded-assertion' not in canonical
    assert b'excluded-signature' not in canonical
    assert canonical == canonical_http_request_bytes(
        method,
        path,
        body,
        {
            'X-Maivn-Operation-Id': ' operation_0001 ',
            'X-Maivn-Session-Id': 'session_0001',
            'Content-Type': '\tapplication/json ',
        },
        client_header_digests,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )
    assert digest == vault_actual_request_digest_from_raw(
        method,
        path,
        body,
        actual_headers,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )
    changed_envelope = {
        **{
            name: value
            for name, value in actual_headers.items()
            if name.lower() not in {SENDER_ASSERTION_HEADER, SENDER_SIGNATURE_HEADER}
        },
        SENDER_ASSERTION_HEADER: 'other-assertion',
        SENDER_SIGNATURE_HEADER: 'other-signature',
    }
    assert digest == vault_actual_request_digest_from_raw(
        method,
        path,
        body,
        changed_envelope,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )
    public_headers = {name.lower(): value.strip(' \t') for name, value in public_headers.items()}
    substitutions = (
        ('GET', path, body, public_headers, client_header_digests),
        (
            method,
            '/v1/vault/work-intents?a=1&b=2',
            body,
            public_headers,
            client_header_digests,
        ),
        (method, path, b'{"plan":{}}\n', public_headers, client_header_digests),
        (
            method,
            path,
            body,
            {**public_headers, OPERATION_ID_HEADER: 'operation_0002'},
            client_header_digests,
        ),
        (
            method,
            path,
            body,
            {**public_headers, RETRIEVAL_SESSION_ID_HEADER: 'session_0002'},
            client_header_digests,
        ),
        (
            method,
            path,
            body,
            public_headers,
            {**client_header_digests, CLIENT_PROOF_HEADER: 'c' * 64},
        ),
        (
            method,
            path,
            body,
            public_headers,
            {**client_header_digests, GRANT_CREDENTIAL_HEADER: 'd' * 64},
        ),
        (
            method,
            path,
            body,
            public_headers,
            {**client_header_digests, RETRIEVAL_SESSION_CREDENTIAL_HEADER: 'e' * 64},
        ),
    )
    for changed_method, changed_path, changed_body, changed_public, changed_client in substitutions:
        assert digest != vault_actual_request_digest_from_prehashed(
            changed_method,
            changed_path,
            changed_body,
            changed_public,
            cast('dict[ClientCapabilityHeader, Sha256Hex]', changed_client),
            expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
        )


def test_prehashed_and_raw_capability_declarations_fail_closed_on_mismatch() -> None:
    """Missing, extra, wrong-domain, or swapped session bindings must change or refuse the call."""
    vector = _vault_protocol_vectors()
    request = cast('dict[str, Any]', vector['http_request'])
    method = cast('str', request['method'])
    path = cast('str', request['path'])
    body = cast('str', request['body_utf8']).encode()
    public_headers = cast('dict[str, str]', request['public_headers'])
    declared = cast('dict[ClientCapabilityHeader, Sha256Hex]', request['client_header_digests'])
    actual_headers = cast('dict[str, str]', request['actual_headers'])
    expected = vault_actual_request_digest_from_prehashed(
        method,
        path,
        body,
        public_headers,
        declared,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )

    for capability_header in (
        GRANT_CREDENTIAL_HEADER,
        CLIENT_PROOF_HEADER,
        RETRIEVAL_SESSION_CREDENTIAL_HEADER,
    ):
        missing_declaration = dict(declared)
        missing_declaration.pop(capability_header)
        with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
            vault_actual_request_digest_from_prehashed(
                method,
                path,
                body,
                public_headers,
                cast('Any', missing_declaration),
                expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
            )
        missing_actual = {
            name: value
            for name, value in actual_headers.items()
            if name.lower() != capability_header
        }
        with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
            vault_actual_request_digest_from_raw(
                method,
                path,
                body,
                missing_actual,
                expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
            )

    swapped_domains = {
        **declared,
        GRANT_CREDENTIAL_HEADER: declared[CLIENT_PROOF_HEADER],
        CLIENT_PROOF_HEADER: declared[GRANT_CREDENTIAL_HEADER],
    }
    assert expected != vault_actual_request_digest_from_prehashed(
        method,
        path,
        body,
        public_headers,
        cast('dict[ClientCapabilityHeader, Sha256Hex]', swapped_domains),
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )
    cross_session_headers = {
        **{
            name: value
            for name, value in actual_headers.items()
            if name.lower()
            not in {RETRIEVAL_SESSION_ID_HEADER, RETRIEVAL_SESSION_CREDENTIAL_HEADER}
        },
        RETRIEVAL_SESSION_ID_HEADER: 'session_0002',
        RETRIEVAL_SESSION_CREDENTIAL_HEADER: 'c2Vzc2lvbi1zZWNyZXQtMDAwMg',
    }
    assert expected != vault_actual_request_digest_from_raw(
        method,
        path,
        body,
        cross_session_headers,
        expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
    )

    for invalid_declarations in (
        {'x-maivn-unknown': 'a' * 64},
        {GRANT_CREDENTIAL_HEADER: 'A' * 64},
        {GRANT_CREDENTIAL_HEADER: 'raw-capability'},
    ):
        with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
            canonical_http_request_bytes(
                method,
                path,
                body,
                public_headers,
                cast('Any', invalid_declarations),
                expected_client_headers=ALL_CLIENT_CAPABILITY_HEADERS,
            )


def test_canonical_request_requires_an_explicit_exact_client_header_profile() -> None:
    """Issuer, client, and verifier must choose one exact route capability profile."""
    digest = 'a' * 64
    grant_only: frozenset[ClientCapabilityHeader] = frozenset({GRANT_CREDENTIAL_HEADER})

    assert canonical_http_request_bytes(
        'POST',
        '/v1/vault/work-intents',
        b'',
        {},
        {},
        expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
    )
    assert vault_actual_request_digest_from_raw(
        'POST',
        '/v1/vault/work-intents',
        b'',
        {},
        expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
    )
    with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
        canonical_http_request_bytes(
            'POST',
            '/v1/vault/work-intents',
            b'',
            {},
            {},
            expected_client_headers=grant_only,
        )
    with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
        canonical_http_request_bytes(
            'POST',
            '/v1/vault/work-intents',
            b'',
            {},
            {GRANT_CREDENTIAL_HEADER: digest},
            expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
        )
    with pytest.raises(ValueError, match='vault_protocol_invalid_client_header_digests'):
        vault_actual_request_digest_from_raw(
            'POST',
            '/v1/vault/work-intents',
            b'',
            {GRANT_CREDENTIAL_HEADER: 'Z3JhbnQ'},
            expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
        )
    missing_profile_calls: tuple[tuple[Any, tuple[Any, ...]], ...] = (
        (
            canonical_http_request_bytes,
            ('POST', '/v1/vault/work-intents', b'', {}, {}),
        ),
        (
            vault_actual_request_digest_from_prehashed,
            ('POST', '/v1/vault/work-intents', b'', {}, {}),
        ),
        (
            vault_actual_request_digest_from_raw,
            ('POST', '/v1/vault/work-intents', b'', {}),
        ),
    )
    for digest_function, arguments in missing_profile_calls:
        with pytest.raises(TypeError):
            cast('Any', digest_function)(*arguments)


@pytest.mark.parametrize('invalid_secret', ['A', 'AB', 'Zg=', '*'])
def test_raw_capabilities_require_canonical_unpadded_base64url(invalid_secret: str) -> None:
    """A textual alias for capability bytes must not produce another valid binding."""
    for digest_function in (
        vault_grant_header_digest,
        vault_client_proof_header_digest,
        vault_retrieval_session_credential_digest,
    ):
        with pytest.raises(ValueError, match=r'^vault_protocol_invalid_secret$'):
            digest_function(invalid_secret)
    with pytest.raises(ValueError, match=r'^vault_protocol_invalid_secret$'):
        vault_grant_verifier(invalid_secret, b'salt')


@pytest.mark.parametrize(
    'path',
    [
        'v1/vault',
        '//vault.example/path',
        '/v1/./vault',
        '/v1/../vault',
        '/v1/%2Fvault',
        '/v1/%5Cvault',
        '/v1/%7evault',
        '/v1/%zzvault',
        '/v1/vault\\item',
        '/v1/vault#fragment',
        '/v1/vault/é',
        '/x?q=a b',
    ],
)
def test_canonical_request_refuses_ambiguous_raw_targets(path: str) -> None:
    """Normalizing an ambiguous target would sign bytes different from those transmitted."""
    with pytest.raises(ValueError, match='vault_protocol_invalid_target'):
        canonical_http_request_bytes(
            'GET',
            path,
            b'',
            {},
            {},
            expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
        )


@pytest.mark.parametrize(
    ('header_name', 'value'),
    [
        ('authorization', 'Bearer secret'),
        ('cookie', 'session=secret'),
        ('proxy-authorization', 'Basic secret'),
        ('host', 'vault.example'),
        ('x-api-key', 'secret'),
        ('x-maivn-request-digest', 'a' * 64),
        ('x-maivn-unknown', 'value'),
        ('x-maivn-operation', 'delete'),
        ('x-maivn-deletion-scope', 'include_redacted_exports'),
        ('bad header', 'value'),
        ('content-type', 'application/json\r\nx-evil: yes'),
        ('content-type', 'application/json\x00'),
        ('content-type', 'application\tjson'),
    ],
)
def test_canonical_request_refuses_unsafe_or_ambient_headers(
    header_name: str,
    value: str,
) -> None:
    """Ambient authority and control characters must never enter a signed Vault call."""
    with pytest.raises(ValueError, match='vault_protocol_unsafe_header'):
        vault_actual_request_digest_from_raw(
            'POST',
            '/v1/vault/work-intents',
            b'',
            {header_name: value},
            expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
        )


def test_canonical_request_refuses_case_ambiguous_header_names() -> None:
    """Two wire spellings may not collapse into one signed header after receipt."""
    with pytest.raises(ValueError, match='vault_protocol_duplicate_header'):
        vault_actual_request_digest_from_raw(
            'POST',
            '/v1/vault/work-intents',
            b'',
            {'Content-Type': 'application/json', 'content-type': 'application/json'},
            expected_client_headers=NO_CLIENT_CAPABILITY_HEADERS,
        )


def test_assertion_signing_bytes_bind_every_closed_claim() -> None:
    """Changing any identity, call, or time claim must invalidate the signature preimage."""
    vector = _vault_protocol_vectors()
    assertion_payload = cast('dict[str, str]', vector['assertion'])
    baseline = vault_assertion_signing_bytes(VaultSenderAssertion.model_validate(assertion_payload))
    assert baseline == b'maivn-vault-assertion-v1\0' + vault_assertion_json_bytes(
        VaultSenderAssertion.model_validate(assertion_payload),
    )
    substitutions = {
        'issuer': 'other_issuer',
        'key_id': 'key_0002',
        'audience': 'other_audience',
        'actor': 'actor_0002',
        'tenant_id': 'tenant_0002',
        'surface': 'surface_0002',
        'surface_digest': 'c' * 64,
        'actual_request_digest': 'd' * 64,
        'issued_at': '2026-08-11T11:58:00Z',
        'nonce': 'nonce_0002',
        'expires_at': '2026-08-11T12:01:00Z',
    }
    for field_name, value in substitutions.items():
        changed = VaultSenderAssertion.model_validate({**assertion_payload, field_name: value})
        assert baseline != vault_assertion_signing_bytes(changed)


def test_admission_and_operation_digests_bind_stored_authority() -> None:
    """Substituting admitted work or stored identity/scope must select a different effect."""
    vector = _vault_protocol_vectors()
    work_payload = cast('dict[str, Any]', vector['work'])
    identity_payload = cast('dict[str, str]', vector['identity'])
    work = VaultWorkRequest.model_validate(work_payload)
    admission = vault_admission_fingerprint(work, **identity_payload)

    changed_work_payloads = (
        {**work_payload, 'intent_id': 'intent_0002'},
        {**work_payload, 'idempotency_key': 'idempotency_0002'},
        {**work_payload, 'scope': {**work_payload['scope'], 'project_id': 'project_0002'}},
        {**work_payload, 'surface': {**work_payload['surface'], 'caller_id': 'caller_0002'}},
        {
            **work_payload,
            'input_handles': [
                {**work_payload['input_handles'][0], 'generation_handle': 'generation_0002'},
            ],
        },
        {**work_payload, 'bounds': {'max_output_bytes': 2048}},
        {**work_payload, 'retention_policy_id': 'retention_policy_0002'},
        {**work_payload, 'deletion_scope': {'mode': 'private_only'}},
        {**work_payload, 'expires_at': '2026-08-11T12:01:00Z'},
    )
    for changed_payload in changed_work_payloads:
        assert admission != vault_admission_fingerprint(
            VaultWorkRequest.model_validate(changed_payload),
            **identity_payload,
        )
    for field_name, value in {
        'issuer': 'other_issuer',
        'actor': 'actor_0002',
        'tenant_id': 'tenant_0002',
        'surface': 'surface_0002',
    }.items():
        changed_identity = {**identity_payload, field_name: value}
        assert admission != vault_admission_fingerprint(
            work,
            **changed_identity,
        )

    stored_payload = cast('dict[str, Any]', vector['stored_intent'])
    binding = _operation_binding_digest(stored_payload)
    binding_substitutions = (
        {**stored_payload, 'intent_id': '22222222-2222-4222-8222-222222222222'},
        {**stored_payload, 'issuer': 'other_issuer'},
        {**stored_payload, 'actor': 'actor_0002'},
        {**stored_payload, 'tenant_id': 'tenant_0002'},
        {**stored_payload, 'surface': 'surface_0002'},
        {**stored_payload, 'admission_fingerprint': 'e' * 64},
        {**stored_payload, 'deletion_scope': 'private_only'},
        {**stored_payload, 'operation': 'redacted_export', 'deletion_scope': None},
    )
    for changed_payload in binding_substitutions:
        assert binding != _operation_binding_digest(changed_payload)


def _operation_binding_digest(payload: dict[str, Any]) -> str:
    return vault_operation_binding_digest(
        intent_id=UUID(cast('str', payload['intent_id'])),
        issuer=cast('str', payload['issuer']),
        actor=cast('str', payload['actor']),
        tenant_id=cast('str', payload['tenant_id']),
        surface=cast('str', payload['surface']),
        operation=payload['operation'],
        admission_fingerprint=payload['admission_fingerprint'],
        deletion_scope=payload['deletion_scope'],
    )


def test_grant_digests_bind_raw_credential_and_per_grant_salt() -> None:
    """A credential or salt substitution must never verify against the stored grant."""
    credential = 'Z3JhbnQtc2VjcmV0LTAwMDE'
    salt = bytes.fromhex('000102030405060708090a0b0c0d0e0f')

    assert vault_grant_header_digest(credential) != vault_grant_header_digest(
        'Z3JhbnQtc2VjcmV0LTAwMDI',
    )
    assert vault_grant_verifier(credential, salt) != vault_grant_verifier(
        'Z3JhbnQtc2VjcmV0LTAwMDI',
        salt,
    )
    assert vault_grant_verifier(credential, salt) != vault_grant_verifier(
        credential,
        bytes.fromhex('100102030405060708090a0b0c0d0e0f'),
    )
    assert vault_client_proof_header_digest(credential) != vault_grant_header_digest(credential)
    assert vault_retrieval_session_credential_digest(
        credential,
    ) != vault_client_proof_header_digest(credential)
    for invalid_credential in ('', 'secret=', 'secret*', 'secret\r\nleak', 'secret\x00', 'é'):
        for digest_function in (
            vault_grant_header_digest,
            vault_client_proof_header_digest,
            vault_retrieval_session_credential_digest,
        ):
            with pytest.raises(ValueError, match='vault_protocol_invalid_secret'):
                digest_function(invalid_credential)
    with pytest.raises(ValueError, match='vault_protocol_invalid_salt'):
        vault_grant_verifier(credential, b'')


def test_task_1b_wire_field_inventories_are_closed_and_exact() -> None:
    """Renaming a public binding would silently break service and generated consumers."""
    reservation_fields = {
        'reservation_id',
        'organization_id',
        'project_id',
        'root_invocation_id',
        'producing_session_id',
        'tool_call_id',
        'dispatch_id',
        'attempt_id',
        'producer',
        'logical_output_id',
        'allowed_kinds',
        'allowed_mime_types',
        'max_artifact_count',
        'max_total_bytes',
        'retention_policy_snapshot_id',
        'idempotency_key',
        'expires_at',
        'state',
        'outcome',
    }
    intent_fields = {
        'intent_id',
        'operation',
        'correlation_id',
        'idempotency_key',
        'expires_at',
        'state',
        'artifact',
        'lifecycle_receipt',
        'redacted_export_receipt',
        'retrieval_action',
    }
    plan_fields = {
        'schema_version',
        'kind',
        'logical_output_name',
        'custody_request',
        'content',
        'input_refs',
        'renderer_profile',
        'renderer_min_version',
        'output_mime_type',
        'validation_profile',
        'disposition',
        'retention_request',
        'resource_bounds',
    }
    patch_fields = {
        'schema_version',
        'target_artifact_id',
        'base_revision',
        'expected_output_kind',
        'renderer_profile',
        'disposition',
        'retention_request',
        'rationale',
        'operations',
    }
    error_fields = {'code', 'error_class', 'retryable'}
    intent_schema = load_private_work_intent_status_schema()
    intent_schema_fields: set[str] = set()
    for variant in intent_schema['oneOf']:
        definition_name = variant['$ref'].removeprefix('#/$defs/')
        intent_schema_fields.update(intent_schema['$defs'][definition_name]['properties'])
    for schema_fields, model_fields, expected in (
        (
            set(load_artifact_reservation_schema()['properties']),
            set(ArtifactReservation.model_fields),
            reservation_fields,
        ),
        (
            intent_schema_fields,
            set(PrivateWorkIntentStatus.model_fields),
            intent_fields,
        ),
        (
            set(load_artifact_error_schema()['properties']),
            set(ArtifactError.model_fields),
            error_fields,
        ),
    ):
        assert schema_fields == expected
        assert model_fields == expected
    patch_schema = load_artifact_patch_schema()
    patch_schema_fields: set[str] = set()
    for variant in patch_schema['oneOf']:
        definition_name = variant['$ref'].removeprefix('#/$defs/')
        patch_schema_fields.update(patch_schema['$defs'][definition_name]['properties'])
    assert patch_schema_fields == patch_fields | {'source_manifest_digest'}
    assert set(ArtifactPatch.model_fields) == patch_fields
    assert set(load_artifact_plan_schema()['properties']) == plan_fields | {'body'}
    assert set(DocumentArtifactPlan.model_fields) == plan_fields
