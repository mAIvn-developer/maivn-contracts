# pyright: strict
"""Refusal paths of the Vault sender, request-canonicalization and delivery protocol."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import pytest
import rfc8785
from pydantic import BaseModel, ValidationError

from maivn_contracts.artifacts import (
    CLIENT_PROOF_HEADER,
    EXPORT_FILENAME_HEADER,
    GRANT_CREDENTIAL_HEADER,
    OPERATION_ID_HEADER,
    RETRIEVAL_SESSION_CREDENTIAL_HEADER,
    SENDER_ASSERTION_HEADER,
    SENDER_SIGNATURE_HEADER,
    ClientCapabilityHeader,
    VaultActionTicket,
    VaultGrantCredentialDelivery,
    VaultIssuerKeyPolicy,
    VaultRetrievalSessionCredentialDelivery,
    VaultSenderAssertion,
    canonical_http_request_bytes,
    decode_vault_sender_assertion,
    vault_actual_request_digest_from_prehashed,
    vault_actual_request_digest_from_raw,
    vault_client_proof_header_digest,
    vault_grant_header_digest,
    vault_grant_verifier,
    vault_operation_binding_digest,
    vault_retrieval_session_credential_digest,
)

TARGET = 'vault_protocol_invalid_target'
METHOD = 'vault_protocol_invalid_method'
UNSAFE = 'vault_protocol_unsafe_header'
DUPLICATE = 'vault_protocol_duplicate_header'
DIGESTS = 'vault_protocol_invalid_client_header_digests'
SECRET = 'vault_protocol_invalid_secret'  # noqa: S105 - error code, not a secret
ASSERTION = 'vault_action_ticket_invalid_sender_assertion'
GRANT = 'Z3JhbnQtc2VjcmV0LTAwMDE'
SESSION = 'c2Vzc2lvbi1zZWNyZXQ'
EXPIRES_AT = '2026-08-11T12:00:00Z'


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _request_bytes(
    *,
    method: str = 'POST',
    path: str = '/v1/vault/work',
    public_headers: dict[str, str] | None = None,
) -> bytes:
    return canonical_http_request_bytes(
        method,
        path,
        b'',
        public_headers or {},
        {},
        expected_client_headers=frozenset(),
    )


@pytest.mark.parametrize(
    'path',
    [
        'relative',
        '//vault.example/x',
        '/café',
        '/a#fragment',
        '/a\\b',
        '/a\x01b',
        '/a\x7fb',
        '/a b',
        '/a/./b',
        '/a/../b',
        '/a/..',
        '/a%2',
        '/a%zz',
        '/a%2f',
        '/a%41',
        '/a%7E',
        '/a%2F',
        '/a%5C',
    ],
)
def test_request_target_refuses_every_non_origin_form_path(path: str) -> None:
    """Only ASCII origin-form targets without dot segments or ambiguous escapes are bound."""
    with pytest.raises(ValueError, match=f'^{TARGET}$'):
        _request_bytes(path=path)


@pytest.mark.parametrize('path', ['/', '/a%20b%25c', '/a/b?x=1&y=%2C', '/a/b?..', '/a/...'])
def test_request_target_keeps_reserved_escapes_queries_and_dotted_names(path: str) -> None:
    """Escaped reserved bytes, queries and non-dot-segment names stay byte-exact."""
    assert json.loads(_request_bytes(path=path))['path'] == path


def test_request_method_is_upper_cased_and_limited_to_get_and_post() -> None:
    """Lower-case methods are canonicalized; padded or other methods are refused."""
    assert json.loads(_request_bytes(method='get'))['method'] == 'GET'
    for method in (' POST', 'POST ', 'PUT', 'DELETE', ''):
        with pytest.raises(ValueError, match=f'^{METHOD}$'):
            _request_bytes(method=method)


def test_public_headers_are_lower_cased_trimmed_and_sorted() -> None:
    """Names are lower-cased, optional whitespace trimmed and keys sorted."""
    canonical = json.loads(
        _request_bytes(
            public_headers={
                'X-Maivn-Operation-Id': '\t operation_0001 \t',
                'Content-Type': 'application/json',
                'X-Maivn-Export-Filename': 'Report (final).pdf',
            },
        ),
    )
    assert canonical['public_headers'] == {
        'content-type': 'application/json',
        EXPORT_FILENAME_HEADER: 'Report (final).pdf',
        OPERATION_ID_HEADER: 'operation_0001',
    }


@pytest.mark.parametrize(
    ('headers', 'error'),
    [
        ({'x-unknown': 'value'}, UNSAFE),
        ({'content type': 'value'}, UNSAFE),
        ({GRANT_CREDENTIAL_HEADER: GRANT}, UNSAFE),
        ({'Content-Type': 'a', 'content-type': 'b'}, DUPLICATE),
        ({'content-type': ' \t '}, UNSAFE),
        ({'content-type': 'a\x1fb'}, UNSAFE),
        ({'content-type': 'a\x7fb'}, UNSAFE),
        ({'content-type': 'café'}, UNSAFE),
        ({EXPORT_FILENAME_HEADER: '../escape.pdf'}, UNSAFE),
        ({EXPORT_FILENAME_HEADER: 'CON.pdf'}, UNSAFE),
    ],
)
def test_public_headers_refuse_unknown_duplicate_unsafe_or_unsafe_filenames(
    headers: dict[str, str],
    error: str,
) -> None:
    """Only the closed public vocabulary, once each, with visible values, is bound."""
    with pytest.raises(ValueError, match=f'^{error}$'):
        _request_bytes(public_headers=headers)


DIGEST_CASES: list[tuple[dict[str, str], object]] = [
    ({'x-maivn-session-id': 'a' * 64}, frozenset({'x-maivn-session-id'})),
    ({GRANT_CREDENTIAL_HEADER: 'A' * 64}, frozenset({GRANT_CREDENTIAL_HEADER})),
    ({GRANT_CREDENTIAL_HEADER: 'a' * 63}, frozenset({GRANT_CREDENTIAL_HEADER})),
    ({GRANT_CREDENTIAL_HEADER: 'a' * 64}, frozenset()),
    ({}, frozenset({GRANT_CREDENTIAL_HEADER})),
    ({GRANT_CREDENTIAL_HEADER: 'a' * 64}, frozenset({GRANT_CREDENTIAL_HEADER, 'cookie'})),
    ({GRANT_CREDENTIAL_HEADER: 'a' * 64}, {GRANT_CREDENTIAL_HEADER}),
]


@pytest.mark.parametrize(('digests', 'expected'), DIGEST_CASES)
def test_client_header_digests_must_be_closed_lower_hex_and_exactly_expected(
    digests: dict[str, str],
    expected: object,
) -> None:
    """Capability digests: closed names, lower-case SHA-256, exactly the route's profile."""
    with pytest.raises(ValueError, match=f'^{DIGESTS}$'):
        canonical_http_request_bytes(
            'POST',
            '/v1/vault/work',
            b'',
            {},
            digests,  # pyright: ignore[reportArgumentType]
            expected_client_headers=expected,  # pyright: ignore[reportArgumentType]
        )


def test_raw_request_digest_hashes_capabilities_and_drops_the_assertion_envelope() -> None:
    """The verifier digest equals the issuer digest over the same request."""
    expected: frozenset[ClientCapabilityHeader] = frozenset(
        {GRANT_CREDENTIAL_HEADER, CLIENT_PROOF_HEADER},
    )
    raw_headers = {
        'Content-Type': 'application/json',
        'X-Maivn-Grant-Credential': GRANT,
        CLIENT_PROOF_HEADER: SESSION,
        SENDER_ASSERTION_HEADER: 'assertion',
        SENDER_SIGNATURE_HEADER: 'signature',
    }
    prehashed = vault_actual_request_digest_from_prehashed(
        'POST',
        '/v1/vault/work',
        b'{}',
        {'content-type': 'application/json'},
        {
            GRANT_CREDENTIAL_HEADER: vault_grant_header_digest(GRANT),
            CLIENT_PROOF_HEADER: vault_client_proof_header_digest(SESSION),
        },
        expected_client_headers=expected,
    )
    assert (
        vault_actual_request_digest_from_raw(
            'POST',
            '/v1/vault/work',
            b'{}',
            raw_headers,
            expected_client_headers=expected,
        )
        == prehashed
    )
    session_only: frozenset[ClientCapabilityHeader] = frozenset(
        {RETRIEVAL_SESSION_CREDENTIAL_HEADER},
    )
    assert vault_actual_request_digest_from_raw(
        'GET',
        '/v1/vault/session',
        b'',
        {RETRIEVAL_SESSION_CREDENTIAL_HEADER: SESSION},
        expected_client_headers=session_only,
    ) == vault_actual_request_digest_from_prehashed(
        'GET',
        '/v1/vault/session',
        b'',
        {},
        {RETRIEVAL_SESSION_CREDENTIAL_HEADER: vault_retrieval_session_credential_digest(SESSION)},
        expected_client_headers=session_only,
    )
    with pytest.raises(ValueError, match=f'^{DIGESTS}$'):
        vault_actual_request_digest_from_raw(
            'POST',
            '/v1/vault/work',
            b'{}',
            raw_headers,
            expected_client_headers=frozenset((GRANT_CREDENTIAL_HEADER,)),
        )
    with pytest.raises(ValueError, match=f'^{SECRET}$'):
        vault_actual_request_digest_from_raw(
            'POST',
            '/v1/vault/work',
            b'{}',
            {GRANT_CREDENTIAL_HEADER: f'{GRANT}='},
            expected_client_headers=frozenset((GRANT_CREDENTIAL_HEADER,)),
        )


def _assertion_payload(**overrides: str) -> dict[str, str]:
    payload = {
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
        'expires_at': EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def test_sender_assertion_lifetime_must_be_positive() -> None:
    """An assertion that expires when or before it is issued is refused."""
    for expires_at in ('2026-08-11T11:59:00Z', '2026-08-11T11:58:59Z'):
        with pytest.raises(ValidationError, match='vault_sender_assertion_invalid_lifetime'):
            VaultSenderAssertion.model_validate(_assertion_payload(expires_at=expires_at))
    assert VaultSenderAssertion.model_validate(
        _assertion_payload(expires_at='2026-08-11T11:59:01Z'),
    )


def test_sender_assertion_decode_refuses_json_constants() -> None:
    """NaN and Infinity are not JSON and never reach model validation."""
    for constant in ('NaN', 'Infinity', '-Infinity'):
        raw = rfc8785.dumps(_assertion_payload())[:-1] + f',"extra":{constant}}}'.encode()
        with pytest.raises(ValueError, match=f'^{ASSERTION}$') as caught:
            decode_vault_sender_assertion(_b64(raw))
        assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ('tenants', 'surfaces'),
    [(['tenant_0001', 'tenant_0001'], ['surface_0001']), (['tenant_0001'], ['s_1', 's_1'])],
)
def test_issuer_key_policy_refuses_duplicate_allowlist_claims(
    tenants: list[str],
    surfaces: list[str],
) -> None:
    """Allowlists are sets: a repeated tenant or surface is refused."""
    with pytest.raises(ValidationError, match='vault_issuer_key_policy_duplicate_claim'):
        VaultIssuerKeyPolicy.model_validate(
            {
                'issuer': 'data_plane',
                'key_id': 'key_0001',
                'audience': 'vault_plane',
                'allowed_tenant_ids': tenants,
                'allowed_surfaces': surfaces,
            },
        )


def _grant_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'intent_id': 'intent_0001',
        'state': 'executing_in_vault',
        'grant_credential_digest': vault_grant_header_digest(GRANT),
        'credential_delivery': 'delivered',
        'grant_credential': GRANT,
        'expires_at': EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def _session_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'schema_version': 'vault-retrieval-session-credential-delivery-v1',
        'session_id': 'session_0001',
        'session_credential_digest': vault_retrieval_session_credential_digest(SESSION),
        'credential_delivery': 'delivered',
        'session_credential': SESSION,
        'expires_at': EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


DELIVERIES: list[tuple[type[BaseModel], Any, str, str]] = [
    (VaultGrantCredentialDelivery, _grant_payload, 'grant_credential', 'grant_credential_digest'),
    (
        VaultRetrievalSessionCredentialDelivery,
        _session_payload,
        'session_credential',
        'session_credential_digest',
    ),
]


@pytest.mark.parametrize(('model', 'payload', 'field', 'digest'), DELIVERIES)
def test_credential_delivery_accepts_matching_first_delivery_and_replay(
    model: type[BaseModel],
    payload: Any,
    field: str,
    digest: str,
) -> None:
    """A delivered credential must match its digest; a replay carries none."""
    delivered = model.model_validate(payload())
    assert getattr(delivered, field) is not None
    assert getattr(delivered, digest) == payload()[digest]
    replay = model.model_validate(payload(credential_delivery='not_replayable', **{field: None}))
    assert getattr(replay, field) is None


@pytest.mark.parametrize(('model', 'payload', 'field', 'digest'), DELIVERIES)
def test_credential_delivery_collapses_every_invalid_credential_input(
    model: type[BaseModel],
    payload: Any,
    field: str,
    digest: str,
) -> None:
    """Any invalid input that carries a credential fails without echoing the credential."""
    credential = payload()[field]
    invalid_inputs = [
        payload(**{digest: 'f' * 64}),
        payload(credential_delivery='not_replayable'),
        payload(**{field: f'{credential}='}),
        payload(**{field: 12345}),
        payload(expires_at='not-a-timestamp'),
        payload(unexpected='value'),
    ]
    for invalid in invalid_inputs:
        with pytest.raises(ValidationError) as caught:
            model.model_validate(invalid)
        errors = caught.value.errors(include_url=False)
        assert {error['type'] for error in errors} >= {'literal_error'}
        assert credential not in str(caught.value)
        assert credential not in json.dumps(errors, default=str)


@pytest.mark.parametrize(('model', 'payload', 'field', 'digest'), DELIVERIES)
def test_credential_delivery_without_credential_validates_normally(
    model: type[BaseModel],
    payload: Any,
    field: str,
    digest: str,
) -> None:
    """Without a credential the input is validated as given; delivered still needs one."""
    del digest
    with pytest.raises(ValidationError, match=r'vault_.*credential_delivery_invalid'):
        model.model_validate(payload(**{field: None}))
    with pytest.raises(ValidationError) as caught:
        model.model_validate(['not', 'a', 'mapping'])
    assert [error['type'] for error in caught.value.errors()] == ['model_type']


def _ticket(
    public_headers: dict[str, str] | None = None,
    **overrides: object,
) -> dict[str, object]:
    path = '/v1/vault/session?b=2'
    headers = public_headers or {}
    digest = vault_actual_request_digest_from_prehashed(
        'GET',
        path,
        b'',
        headers,
        {},
        expected_client_headers=frozenset(),
    )
    assertion = rfc8785.dumps(_assertion_payload(actual_request_digest=digest))
    ticket: dict[str, object] = {
        'method': 'GET',
        'path': path,
        'url': f'https://vault.example{path}',
        'public_headers': headers,
        'client_header_digests': {},
        'sender_assertion_base64url': _b64(assertion),
        'sender_signature_base64url': _b64(bytes(64)),
        'body_base64url': None,
        'expires_at': EXPIRES_AT,
    }
    ticket.update(overrides)
    return ticket


def test_action_ticket_without_body_binds_the_empty_body() -> None:
    """A body-less ticket is bound to the digest of the empty body."""
    ticket = VaultActionTicket.model_validate(_ticket())
    assert ticket.body_base64url is None
    assert ticket.declared_request_header_names() == frozenset(
        {SENDER_ASSERTION_HEADER, SENDER_SIGNATURE_HEADER},
    )
    ticket.require_client_header_digests(frozenset())
    with pytest.raises(ValueError, match=f'^{DIGESTS}$'):
        ticket.require_client_header_digests(frozenset({GRANT_CREDENTIAL_HEADER}))
    with pytest.raises(ValidationError, match='vault_action_ticket_assertion_mismatch'):
        VaultActionTicket.model_validate(_ticket(body_base64url=_b64(b'{}')))


@pytest.mark.parametrize(
    'url',
    [
        'https://vault.example/v1/vault/session?b=2#frag',
        'https://user@vault.example/v1/vault/session?b=2',
        'https://user:pw@vault.example/v1/vault/session?b=2',
        'https://:pw@vault.example/v1/vault/session?b=2',
        'https://vault.example/v1/vault/session',
        'https://vault.example/v1/vault/session?b=3',
        'https://vault.example/v1/vault/other?b=2',
    ],
)
def test_action_ticket_url_must_carry_exactly_the_bound_target(url: str) -> None:
    """No fragment, no userinfo, and the URL target equals the signed path and query."""
    with pytest.raises(ValidationError, match='vault_action_ticket_url_path_mismatch'):
        VaultActionTicket.model_validate(_ticket(url=url))


def test_action_ticket_expiry_must_equal_the_assertion_expiry() -> None:
    """The ticket cannot outlive or undercut the signed assertion."""
    with pytest.raises(ValidationError, match='vault_action_ticket_assertion_mismatch'):
        VaultActionTicket.model_validate(_ticket(expires_at='2026-08-11T12:00:01Z'))


def test_action_ticket_refuses_noncanonical_body_transport() -> None:
    """The body must itself be canonical unpadded base64url."""
    with pytest.raises(ValidationError, match='vault_protocol_invalid_base64url'):
        VaultActionTicket.model_validate(_ticket(body_base64url='e30='))


@pytest.mark.parametrize(
    ('operation', 'deletion_scope'),
    [
        ('delete', None),
        ('create', 'private_only'),
        ('retrieve_session', 'include_redacted_exports'),
    ],
)
def test_operation_binding_requires_a_scope_exactly_for_delete(
    operation: str,
    deletion_scope: str | None,
) -> None:
    """Only a delete binding carries a deletion scope, and a delete always carries one."""
    with pytest.raises(ValidationError, match='vault_stored_intent_invalid_deletion_scope'):
        vault_operation_binding_digest(
            intent_id=uuid.UUID('11111111-1111-4111-8111-111111111111'),
            issuer='data_plane',
            actor='actor_0001',
            tenant_id='tenant_0001',
            surface='surface_0001',
            operation=operation,  # pyright: ignore[reportArgumentType]
            admission_fingerprint='a' * 64,
            deletion_scope=deletion_scope,  # pyright: ignore[reportArgumentType]
        )


def test_grant_verifier_requires_salt_and_canonical_credential() -> None:
    """An empty salt or a non-canonical credential is refused."""
    with pytest.raises(ValueError, match=r'^vault_protocol_invalid_salt$'):
        vault_grant_verifier(GRANT, b'')
    with pytest.raises(ValueError, match=f'^{SECRET}$'):
        vault_grant_verifier(f'{GRANT}=', b'salt')
    assert vault_grant_verifier(GRANT, b'a') != vault_grant_verifier(GRANT, b'b')


def test_action_ticket_stores_public_headers_canonicalized_and_sorted() -> None:
    """The ticket keeps the lower-cased, trimmed headers in sorted order."""
    ticket = VaultActionTicket.model_validate(
        _ticket(
            public_headers={
                'X-Maivn-Operation-Id': ' operation_0001',
                'Content-Type': 'application/json',
            },
        ),
    )
    assert list(ticket.public_headers.items()) == [
        ('content-type', 'application/json'),
        (OPERATION_ID_HEADER, 'operation_0001'),
    ]
    assert ticket.declared_request_header_names() == frozenset(
        {'content-type', OPERATION_ID_HEADER, SENDER_ASSERTION_HEADER, SENDER_SIGNATURE_HEADER},
    )


@pytest.mark.parametrize(('model', 'payload', 'field', 'digest'), DELIVERIES)
def test_credential_delivery_errors_never_render_input_values(
    model: type[BaseModel],
    payload: Any,
    field: str,
    digest: str,
) -> None:
    """Even credential-free invalid input is kept out of the rendered error."""
    del digest
    sentinel = 'sentinel value!'
    invalid = payload(credential_delivery='not_replayable', **{field: None})
    invalid['expires_at'] = sentinel
    with pytest.raises(ValidationError) as caught:
        model.model_validate(invalid)
    assert sentinel not in str(caught.value)
    assert 'input_value' not in str(caught.value)
