# pyright: strict
"""Canonical service authentication for Vault-to-ordinary export calls."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest
import rfc8785
from pydantic import ValidationError

from maivn_contracts.artifacts import (
    OrdinaryExportDeletionRequest,
    VerifiedExportPublicationRequest,
    load_vault_ordinary_export_service_assertion_schema,
    load_vault_ordinary_export_trust_document_schema,
    validate_vault_ordinary_export_service_assertion,
    validate_vault_ordinary_export_trust_document,
)
from maivn_contracts.artifacts.vault_ordinary_export_protocol import (
    VAULT_ORDINARY_EXPORT_ASSERTION_HEADER,
    VAULT_ORDINARY_EXPORT_AUDIENCE,
    VAULT_ORDINARY_EXPORT_DELETION_PATH,
    VAULT_ORDINARY_EXPORT_PUBLICATION_PATH,
    VAULT_ORDINARY_EXPORT_SIGNATURE_HEADER,
    VaultOrdinaryExportServiceAssertion,
    VaultOrdinaryExportTrustDocument,
    VaultOrdinaryExportTrustEntry,
    decode_vault_ordinary_export_assertion,
    decode_vault_ordinary_export_assertion_headers,
    decode_vault_ordinary_export_signature,
    encode_vault_ordinary_export_assertion,
    encode_vault_ordinary_export_signature,
    select_vault_ordinary_export_trust_entry,
    vault_ordinary_export_assertion_json_bytes,
    vault_ordinary_export_assertion_signing_bytes,
    vault_ordinary_export_json_body_bytes,
    vault_ordinary_export_json_request_binding,
    vault_ordinary_export_nonce_digest,
    vault_ordinary_export_publication_control_bytes,
    vault_ordinary_export_publication_request_binding,
)

_NOW = datetime(2026, 8, 14, 18, 30, tzinfo=timezone.utc)
_NONCE_BYTES = bytes(range(16))
_NONCE = base64.urlsafe_b64encode(_NONCE_BYTES).rstrip(b'=').decode('ascii')
_PUBLIC_KEY = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b'=').decode('ascii')
_SIGNATURE = bytes(range(64))
_SIGNATURE_TRANSPORT = base64.urlsafe_b64encode(_SIGNATURE).rstrip(b'=').decode('ascii')


def _manifest() -> dict[str, object]:
    return {
        'schema_version': 'verified-export-v1',
        'scope': {'organization_id': 'organization_0001', 'project_id': 'project_0001'},
        'surface': {
            'root_invocation_id': 'root_invocation_0001',
            'session_id': 'session_0001',
            'checkpoint_id': 'checkpoint_0001',
            'caller_id': 'caller_0001',
        },
        'correlation_id': 'export_correlation_0001',
        'artifact_kind': 'document',
        'mime_type': 'application/pdf',
        'public_filename': 'safe-export.pdf',
        'content_length': 4096,
        'content_sha256': 'a' * 64,
        'proof_receipt_id': 'proof_receipt_0001',
    }


def _publication_request() -> VerifiedExportPublicationRequest:
    return VerifiedExportPublicationRequest.model_validate(
        {
            'schema_version': 'verified-export-publication-v1',
            'operation_id': 'publication_operation_0001',
            'manifest': _manifest(),
        },
    )


def _assertion(**overrides: object) -> VaultOrdinaryExportServiceAssertion:
    payload: dict[str, object] = {
        'schema_version': 'vault-ordinary-export-assertion-v1',
        'issuer': 'vault_executor_0001',
        'key_id': 'key_0001',
        'audience': VAULT_ORDINARY_EXPORT_AUDIENCE,
        'role': 'executor',
        'method': 'POST',
        'fixed_path': VAULT_ORDINARY_EXPORT_PUBLICATION_PATH,
        'request_binding': 'b' * 64,
        'issued_at': '2026-08-14T18:29:30Z',
        'expires_at': '2026-08-14T18:30:20Z',
        'nonce': _NONCE,
    }
    payload.update(overrides)
    return VaultOrdinaryExportServiceAssertion.model_validate(payload)


def _trust_entry(**overrides: object) -> VaultOrdinaryExportTrustEntry:
    payload: dict[str, object] = {
        'peer_leaf_certificate_sha256': 'c' * 64,
        'issuer': 'vault_executor_0001',
        'key_id': 'key_0001',
        'ed25519_public_key_base64url': _PUBLIC_KEY,
        'role': 'executor',
        'audience': VAULT_ORDINARY_EXPORT_AUDIENCE,
        'allowed_paths': [VAULT_ORDINARY_EXPORT_PUBLICATION_PATH],
        'not_before': '2026-08-14T18:00:00Z',
        'not_after': '2026-08-14T19:00:00Z',
    }
    payload.update(overrides)
    return VaultOrdinaryExportTrustEntry.model_validate(payload)


def test_assertion_uses_exact_jcs_transport_and_domain_separated_signing_bytes() -> None:
    """Every assertion byte is frozen across sender and verifier implementations."""
    assertion = _assertion()
    expected_json = rfc8785.dumps(assertion.model_dump(mode='json'))
    expected_transport = base64.urlsafe_b64encode(expected_json).rstrip(b'=').decode('ascii')

    assert vault_ordinary_export_assertion_json_bytes(assertion) == expected_json
    assert vault_ordinary_export_assertion_signing_bytes(assertion) == (
        b'maivn-vault-ordinary-export-assertion-v1\0' + expected_json
    )
    assert encode_vault_ordinary_export_assertion(assertion) == expected_transport
    assert encode_vault_ordinary_export_signature(_SIGNATURE) == _SIGNATURE_TRANSPORT
    assert decode_vault_ordinary_export_assertion(expected_transport) == assertion
    assert decode_vault_ordinary_export_signature(_SIGNATURE_TRANSPORT) == _SIGNATURE


def test_cross_component_golden_vectors_pin_all_protocol_preimages() -> None:
    """Static vectors prevent independent implementations from drifting."""
    vectors = cast(
        'dict[str, object]',
        json.loads(
            (
                Path(__file__).parents[2]
                / 'fixtures/vault_ordinary_export_protocol_golden_vectors.json'
            ).read_text(
                encoding='utf-8',
            ),
        ),
    )
    assertion = VaultOrdinaryExportServiceAssertion.model_validate(vectors['assertion'])
    publication_control = vault_ordinary_export_publication_control_bytes(
        _publication_request(),
    )
    deletion_body = vault_ordinary_export_json_body_bytes(
        OrdinaryExportDeletionRequest.model_validate(
            {
                'schema_version': 'ordinary-export-deletion-request-v1',
                'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
                'deletion_manifest_id': 'deletion_manifest_0001',
            },
        ),
    )

    assert (
        vault_ordinary_export_assertion_json_bytes(assertion).decode()
        == vectors['assertion_json_utf8']
    )
    assert (
        base64.urlsafe_b64encode(
            vault_ordinary_export_assertion_signing_bytes(assertion),
        )
        .rstrip(b'=')
        .decode()
        == vectors['assertion_signing_base64url']
    )
    assert publication_control.decode() == vectors['publication_control_utf8']
    assert (
        vault_ordinary_export_publication_request_binding(
            control=publication_control,
            measured_artifact_length=4096,
            measured_artifact_sha256='d' * 64,
        )
        == vectors['publication_binding']
    )
    assert deletion_body.decode() == vectors['deletion_body_utf8']
    assert (
        vault_ordinary_export_json_request_binding(
            fixed_path=VAULT_ORDINARY_EXPORT_DELETION_PATH,
            body=deletion_body,
        )
        == vectors['deletion_binding']
    )
    assert vault_ordinary_export_nonce_digest(assertion.nonce) == vectors['nonce_digest']


def test_stored_assertion_and_trust_schemas_match_typed_protocol_authority() -> None:
    """Stored schemas and Pydantic projections accept the same canonical documents."""
    assertion = _assertion()
    entry = _trust_entry()
    document = VaultOrdinaryExportTrustDocument(
        schema_version='vault-ordinary-export-trust-v1',
        entries=(entry,),
    )

    assert (
        validate_vault_ordinary_export_service_assertion(
            assertion.model_dump(mode='json'),
        )
        == assertion
    )
    assert (
        validate_vault_ordinary_export_trust_document(
            document.model_dump(mode='json'),
        )
        == document
    )
    assert load_vault_ordinary_export_service_assertion_schema()['additionalProperties'] is False
    assert load_vault_ordinary_export_trust_document_schema()['additionalProperties'] is False


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('nonce', base64.urlsafe_b64encode(bytes(15)).rstrip(b'=').decode('ascii')),
        ('nonce', f'{_NONCE}='),
        ('fixed_path', VAULT_ORDINARY_EXPORT_DELETION_PATH),
        ('expires_at', '2026-08-14T18:30:31Z'),
    ],
)
def test_assertion_refuses_noncanonical_nonce_role_path_and_lifetime(
    field: str,
    value: object,
) -> None:
    """No malformed nonce, cross-role path, or widened TTL reaches verification."""
    with pytest.raises(ValidationError):
        _assertion(**{field: value})


def test_publication_binding_uses_exact_control_length_artifact_length_and_raw_digest() -> None:
    """Publication binds the exact frame plus measured byte length and digest."""
    request = _publication_request()
    control = rfc8785.dumps(request.model_dump(mode='json'))
    measured_digest = bytes.fromhex('d' * 64)
    expected = hashlib.sha256(
        b'maivn-vault-ordinary-export-publication-request-v1\0'
        b'POST\0/internal/v1/vault/ordinary-exports/publications\0'
        + struct.pack('!I', len(control))
        + control
        + struct.pack('!Q', 4096)
        + measured_digest,
    ).hexdigest()

    assert vault_ordinary_export_publication_control_bytes(request) == control
    assert (
        vault_ordinary_export_publication_request_binding(
            control=control,
            measured_artifact_length=4096,
            measured_artifact_sha256='d' * 64,
        )
        == expected
    )


def test_json_binding_uses_exact_closed_body_and_fixed_path() -> None:
    """Maintenance JSON binds exact bytes to its fixed POST path."""
    request = OrdinaryExportDeletionRequest.model_validate(
        {
            'schema_version': 'ordinary-export-deletion-request-v1',
            'ordinary_deletion_ref': 'ordinary_deletion_ref_0001',
            'deletion_manifest_id': 'deletion_manifest_0001',
        },
    )
    body = rfc8785.dumps(request.model_dump(mode='json'))
    expected = hashlib.sha256(
        b'maivn-vault-ordinary-export-json-request-v1\0'
        b'POST\0/internal/v1/vault/ordinary-exports/deletions\0'
        + struct.pack('!I', len(body))
        + body,
    ).hexdigest()

    assert vault_ordinary_export_json_body_bytes(request) == body
    assert (
        vault_ordinary_export_json_request_binding(
            fixed_path=VAULT_ORDINARY_EXPORT_DELETION_PATH,
            body=body,
        )
        == expected
    )


def test_nonce_digest_is_domain_separated_over_exact_ascii_transport() -> None:
    """Replay persistence stores only a domain-separated nonce digest."""
    assert (
        vault_ordinary_export_nonce_digest(_NONCE)
        == hashlib.sha256(
            b'maivn-vault-ordinary-export-assertion-nonce-v1\0' + _NONCE.encode('ascii'),
        ).hexdigest()
    )


def test_raw_headers_are_exact_closed_and_reject_ambiguous_or_ambient_transport() -> None:
    """Raw ASGI transport cannot smuggle duplicate, legacy, or ambient authority."""
    assertion_transport = (
        base64.urlsafe_b64encode(
            vault_ordinary_export_assertion_json_bytes(_assertion()),
        )
        .rstrip(b'=')
        .decode('ascii')
    )
    headers = (
        (VAULT_ORDINARY_EXPORT_ASSERTION_HEADER.encode(), assertion_transport.encode()),
        (VAULT_ORDINARY_EXPORT_SIGNATURE_HEADER.encode(), _SIGNATURE_TRANSPORT.encode()),
    )
    assertion, signature = decode_vault_ordinary_export_assertion_headers(headers)
    assert assertion == _assertion()
    assert signature == _SIGNATURE

    for invalid_headers in (
        (*headers, headers[0]),
        ((b'authorization', b'Bearer secret'), *headers),
        ((b'cookie', b'session=secret'), *headers),
        ((b'x-maivn-signature', b'legacy'), *headers),
        ((b'x-maivn-sender-assertion', b'unrelated'), *headers),
        ((headers[0][0], b' ' + headers[0][1]), headers[1]),
        ((headers[0][0], headers[0][1] + b',' + headers[0][1]), headers[1]),
    ):
        with pytest.raises(ValueError, match='vault_ordinary_export_transport_invalid'):
            decode_vault_ordinary_export_assertion_headers(invalid_headers)


def test_trust_document_is_unique_role_exact_and_selects_one_current_entry() -> None:
    """One pinned peer selects one current issuer, key, role, and path authority."""
    entry = _trust_entry()
    document = VaultOrdinaryExportTrustDocument(
        schema_version='vault-ordinary-export-trust-v1',
        entries=(entry,),
    )

    assert (
        select_vault_ordinary_export_trust_entry(
            document=document,
            assertion=_assertion(),
            peer_leaf_certificate_sha256='c' * 64,
            now=_NOW,
        )
        == entry
    )

    with pytest.raises(ValidationError):
        VaultOrdinaryExportTrustDocument(
            schema_version='vault-ordinary-export-trust-v1',
            entries=(entry, entry),
        )
    with pytest.raises(ValidationError):
        VaultOrdinaryExportTrustEntry.model_validate(
            {**entry.model_dump(mode='json'), 'allowed_paths': ['*']},
        )
    with pytest.raises(ValueError, match='vault_ordinary_export_trust_invalid'):
        select_vault_ordinary_export_trust_entry(
            document=document,
            assertion=_assertion(),
            peer_leaf_certificate_sha256='e' * 64,
            now=_NOW,
        )


def test_protocol_models_and_errors_do_not_project_private_sentinels() -> None:
    """Invalid protocol values never survive in structured exception projections."""
    sentinel = 'private-sentinel-export-auth'
    with pytest.raises(ValidationError) as caught:
        VaultOrdinaryExportServiceAssertion.model_validate(
            {**_assertion().model_dump(mode='json'), 'issuer': sentinel, 'unexpected': sentinel},
        )

    for projection in (
        str(caught.value),
        repr(caught.value),
        json.dumps(caught.value.errors()),
        caught.value.json(),
    ):
        assert sentinel not in projection
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_transport_decode_collapses_private_values_and_exception_chains() -> None:
    """Malformed transported JSON is refused without retaining its decoded values."""
    sentinel = 'private-sentinel-transport-value'
    raw = json.dumps(
        {**_assertion().model_dump(mode='json'), 'issuer': sentinel, 'unexpected': sentinel},
    ).encode()
    transport = base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    with pytest.raises(
        ValueError,
        match='vault_ordinary_export_transport_invalid',
    ) as caught:
        decode_vault_ordinary_export_assertion(transport)

    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
