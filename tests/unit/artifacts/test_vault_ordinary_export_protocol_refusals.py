# pyright: strict
"""Every refusal path of the Vault ordinary-export workload authentication protocol."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from maivn_contracts.artifacts import VerifiedExportPublicationRequest
from maivn_contracts.artifacts.vault_ordinary_export_protocol import (
    VAULT_ORDINARY_EXPORT_ASSERTION_HEADER,
    VAULT_ORDINARY_EXPORT_AUDIENCE,
    VAULT_ORDINARY_EXPORT_DELETION_PATH,
    VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH,
    VAULT_ORDINARY_EXPORT_PUBLICATION_PATH,
    VAULT_ORDINARY_EXPORT_SIGNATURE_HEADER,
    RawHeaderMultimap,
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
    vault_ordinary_export_json_request_binding,
    vault_ordinary_export_nonce_digest,
    vault_ordinary_export_publication_control_bytes,
    vault_ordinary_export_publication_request_binding,
)

TRANSPORT = 'vault_ordinary_export_transport_invalid'
TRUST = 'vault_ordinary_export_trust_invalid'
BINDING = 'vault_ordinary_export_binding_invalid'
NOW = datetime(2026, 8, 14, 18, 30, tzinfo=timezone.utc)
NONCE = base64.urlsafe_b64encode(bytes(range(16))).rstrip(b'=').decode('ascii')
PUBLIC_KEY = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b'=').decode('ascii')
SIGNATURE = bytes(range(64))
SIGNATURE_TRANSPORT = base64.urlsafe_b64encode(SIGNATURE).rstrip(b'=').decode('ascii')
PEER = 'c' * 64


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _assertion_payload(**overrides: object) -> dict[str, object]:
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
        'nonce': NONCE,
    }
    payload.update(overrides)
    return payload


def _assertion(**overrides: object) -> VaultOrdinaryExportServiceAssertion:
    return VaultOrdinaryExportServiceAssertion.model_validate(_assertion_payload(**overrides))


def _entry_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'peer_leaf_certificate_sha256': PEER,
        'issuer': 'vault_executor_0001',
        'key_id': 'key_0001',
        'ed25519_public_key_base64url': PUBLIC_KEY,
        'role': 'executor',
        'audience': VAULT_ORDINARY_EXPORT_AUDIENCE,
        'allowed_paths': [VAULT_ORDINARY_EXPORT_PUBLICATION_PATH],
        'not_before': '2026-08-14T18:00:00Z',
        'not_after': '2026-08-14T19:00:00Z',
    }
    payload.update(overrides)
    return payload


def _document(*entries: dict[str, object]) -> VaultOrdinaryExportTrustDocument:
    return VaultOrdinaryExportTrustDocument.model_validate(
        {'schema_version': 'vault-ordinary-export-trust-v1', 'entries': list(entries)},
    )


def _select(
    document: VaultOrdinaryExportTrustDocument,
    assertion: VaultOrdinaryExportServiceAssertion,
    *,
    now: datetime = NOW,
) -> VaultOrdinaryExportTrustEntry:
    return select_vault_ordinary_export_trust_entry(
        document=document,
        assertion=assertion,
        peer_leaf_certificate_sha256=PEER,
        now=now,
    )


NONCANONICAL_BASE64URL: list[object] = [
    None,
    b'AAAA',
    '',
    'AAAA=',
    'AAAé',
    'AA+/',
    'A',
    'AB',
]


@pytest.mark.parametrize('value', NONCANONICAL_BASE64URL)
def test_signature_decode_refuses_every_noncanonical_transport(value: object) -> None:
    """Non-strings, padding, non-ASCII, standard alphabet, bad length and loose bits fail."""
    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        decode_vault_ordinary_export_signature(value)


@pytest.mark.parametrize('size', [63, 65])
def test_signature_decode_refuses_wrong_decoded_size(size: int) -> None:
    """Only exactly 64 decoded bytes are an Ed25519 signature."""
    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        decode_vault_ordinary_export_signature(_b64(bytes(size)))


@pytest.mark.parametrize('value', NONCANONICAL_BASE64URL[:-1])
def test_assertion_decode_refuses_every_noncanonical_transport(value: object) -> None:
    """The unbounded assertion decoder applies the same canonical base64url rules."""
    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        decode_vault_ordinary_export_assertion(value)


def test_assertion_decode_refuses_loose_trailing_bits_in_valid_json() -> None:
    """A transport that decodes to the right JSON but is not canonical base64url fails."""
    transport = encode_vault_ordinary_export_assertion(_assertion())
    last = transport[-1]
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    sibling = alphabet[alphabet.index(last) + 1]
    loose = transport[:-1] + sibling
    assert base64.urlsafe_b64decode(loose + '=' * (-len(loose) % 4)) == base64.urlsafe_b64decode(
        transport + '=' * (-len(transport) % 4),
    )

    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        decode_vault_ordinary_export_assertion(loose)


def test_assertion_decode_refuses_duplicate_keys_and_noncanonical_json() -> None:
    """Duplicate keys and any JSON that is not the exact RFC 8785 rendering fail."""
    canonical = vault_ordinary_export_assertion_json_bytes(_assertion())
    duplicated = canonical[:-1] + b',"issuer":"vault_executor_0001"}'
    spaced = json.dumps(_assertion_payload(), sort_keys=True).encode()
    for raw in (duplicated, spaced, b'\xff', b'[]', b'not json'):
        with pytest.raises(ValueError, match=f'^{TRANSPORT}$') as caught:
            decode_vault_ordinary_export_assertion(_b64(raw))
        assert caught.value.__cause__ is None


def test_signature_encode_requires_exactly_64_bytes() -> None:
    """Encoding refuses non-bytes with TypeError and wrong lengths with ValueError."""
    assert encode_vault_ordinary_export_signature(SIGNATURE) == SIGNATURE_TRANSPORT
    with pytest.raises(TypeError, match=f'^{TRANSPORT}$'):
        encode_vault_ordinary_export_signature(bytearray(SIGNATURE))  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        encode_vault_ordinary_export_signature(bytes(63))


def _headers() -> list[tuple[bytes, bytes]]:
    return [
        (
            VAULT_ORDINARY_EXPORT_ASSERTION_HEADER.encode(),
            encode_vault_ordinary_export_assertion(_assertion()).encode(),
        ),
        (VAULT_ORDINARY_EXPORT_SIGNATURE_HEADER.encode(), SIGNATURE_TRANSPORT.encode()),
    ]


def test_headers_ignore_unrelated_names_and_accept_either_order() -> None:
    """Unrelated headers are skipped; the two protocol headers may come in any order."""
    assertion_header, signature_header = _headers()
    headers: RawHeaderMultimap = (
        (b'content-type', b'application/json'),
        signature_header,
        (b'x-request-id', b'a,b=c'),
        assertion_header,
    )
    assert decode_vault_ordinary_export_assertion_headers(headers) == (_assertion(), SIGNATURE)


def _malformed_headers() -> dict[str, RawHeaderMultimap]:
    assertion, signature = _headers()
    name, value = signature
    return {
        'missing-signature': (assertion,),
        'missing-assertion': (signature,),
        'duplicate-signature': (assertion, signature, signature),
        'uppercase-name': ((assertion[0].upper(), assertion[1]), signature),
        'forbidden-any-case': (assertion, signature, (b'Authorization', b'x')),
        'forbidden-sender': (assertion, signature, (b'x-maivn-sender-signature', b'x')),
        'empty-value': (assertion, (name, b'')),
        'trailing-tab': (assertion, (name, value + b'\t')),
        'equals-sign': (assertion, (name, value + b'=')),
        'inner-space': (assertion, (name, value[:10] + b' ' + value[10:])),
        'del-byte': (assertion, (name, value + b'\x7f')),
        'non-ascii': (assertion, (name, value + b'\x80')),
        'short-signature': (assertion, (name, b'AAAA')),
    }


@pytest.mark.parametrize('case', sorted(_malformed_headers()))
def test_headers_refuse_ambiguous_or_malformed_transport(case: str) -> None:
    """Missing, repeated, mis-cased, ambient-authority or non-token headers fail."""
    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        decode_vault_ordinary_export_assertion_headers(_malformed_headers()[case])


def test_headers_refuse_non_bytes_names_and_values_with_type_error() -> None:
    """A multimap carrying str instead of raw bytes is a caller bug, refused loudly."""
    assertion_header, signature_header = _headers()
    for headers in (
        ((VAULT_ORDINARY_EXPORT_ASSERTION_HEADER, assertion_header[1]), signature_header),
        ((assertion_header[0], assertion_header[1].decode()), signature_header),
    ):
        with pytest.raises(TypeError, match=f'^{TRANSPORT}$'):
            decode_vault_ordinary_export_assertion_headers(headers)  # pyright: ignore[reportArgumentType]


def test_assertion_lifetime_must_be_positive_and_at_most_sixty_seconds() -> None:
    """A zero or negative lifetime fails; exactly sixty seconds is the inclusive maximum."""
    assert _assertion(expires_at='2026-08-14T18:30:30Z').expires_at == '2026-08-14T18:30:30Z'
    for expires_at in ('2026-08-14T18:29:30Z', '2026-08-14T18:29:29Z'):
        with pytest.raises(ValidationError):
            _assertion(expires_at=expires_at)


def test_maintenance_assertions_bind_only_maintenance_paths() -> None:
    """The maintenance role carries the deletion paths and never the publication path."""
    for path in (VAULT_ORDINARY_EXPORT_DELETION_PATH, VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH):
        assert _assertion(role='maintenance', fixed_path=path).fixed_path == path
    with pytest.raises(ValidationError):
        _assertion(role='maintenance', fixed_path=VAULT_ORDINARY_EXPORT_PUBLICATION_PATH)


def test_invalid_protocol_input_is_reported_without_echoing_any_value() -> None:
    """Every closed protocol model collapses invalid input to one value-free error."""
    sentinel = 'private-sentinel-value'
    cases: list[tuple[type[BaseModel], dict[str, object]]] = [
        (VaultOrdinaryExportServiceAssertion, _assertion_payload(nonce=sentinel)),
        (VaultOrdinaryExportTrustEntry, _entry_payload(ed25519_public_key_base64url=sentinel)),
        (
            VaultOrdinaryExportTrustDocument,
            {'schema_version': sentinel, 'entries': [_entry_payload()]},
        ),
    ]
    for model, payload in cases:
        with pytest.raises(ValidationError) as caught:
            model.model_validate(payload)
        errors = caught.value.errors(include_url=False)
        assert errors
        assert {json.dumps(error['input']) for error in errors} <= {
            '"invalid"',
            '{"schema_version": "invalid"}',
        }
        assert sentinel not in str(caught.value)


def test_protocol_models_redact_repr_and_str() -> None:
    """Claims and trust material never appear in diagnostic renderings."""
    entry = VaultOrdinaryExportTrustEntry.model_validate(_entry_payload())
    document = _document(_entry_payload())
    assertion = _assertion()
    assert repr(assertion) == str(assertion) == 'VaultOrdinaryExportServiceAssertion(<redacted>)'
    assert repr(entry) == str(entry) == 'VaultOrdinaryExportTrustEntry(<redacted>)'
    assert repr(document) == str(document) == 'VaultOrdinaryExportTrustDocument(<redacted>)'


@pytest.mark.parametrize(
    'overrides',
    [
        {'not_after': '2026-08-14T18:00:00Z'},
        {'not_after': '2026-08-14T17:59:59Z'},
        {'role': 'maintenance'},
        {'allowed_paths': []},
        {'ed25519_public_key_base64url': _b64(bytes(31))},
    ],
)
def test_trust_entry_refuses_empty_windows_and_mismatched_role_paths(
    overrides: dict[str, object],
) -> None:
    """Validity windows must be non-empty; allowed paths must equal the role's paths exactly."""
    with pytest.raises(ValidationError):
        VaultOrdinaryExportTrustEntry.model_validate(_entry_payload(**overrides))


def test_trust_document_peer_maps_to_one_issuer_and_role() -> None:
    """A peer may rotate keys under one authority but never serve two issuers or roles."""
    rotated = _document(_entry_payload(), _entry_payload(key_id='key_0002'))
    assert [entry.key_id for entry in rotated.entries] == ['key_0001', 'key_0002']
    other_peer = _document(_entry_payload(), _entry_payload(peer_leaf_certificate_sha256='d' * 64))
    assert [entry.peer_leaf_certificate_sha256 for entry in other_peer.entries] == [PEER, 'd' * 64]

    maintenance = _entry_payload(
        key_id='key_0002',
        role='maintenance',
        allowed_paths=[
            VAULT_ORDINARY_EXPORT_DELETION_PATH,
            VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH,
        ],
    )
    for second in (_entry_payload(key_id='key_0002', issuer='vault_other_0001'), maintenance):
        with pytest.raises(ValidationError):
            _document(_entry_payload(), second)
    with pytest.raises(ValidationError):
        _document()


def test_trust_selection_requires_an_aware_clock() -> None:
    """A naive datetime is refused rather than silently read as local time."""
    local_wall_clock = NOW.astimezone().replace(tzinfo=None)
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(_document(_entry_payload()), _assertion(), now=local_wall_clock)


def test_trust_selection_accepts_any_aware_offset() -> None:
    """The clock is compared in UTC whatever its offset."""
    document = _document(_entry_payload())
    local = NOW.astimezone(timezone(timedelta(hours=-5)))
    assert _select(document, _assertion(), now=local) == document.entries[0]


@pytest.mark.parametrize(
    'claims',
    [
        {'issuer': 'vault_other_0001'},
        {'key_id': 'key_0002'},
        {'role': 'maintenance', 'fixed_path': VAULT_ORDINARY_EXPORT_DELETION_PATH},
    ],
)
def test_trust_selection_requires_matching_issuer_key_and_role(
    claims: dict[str, object],
) -> None:
    """Every claim must match the pinned entry for the peer."""
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(_document(_entry_payload()), _assertion(**claims))


def test_trust_selection_time_boundaries() -> None:
    """Skew, expiry, validity window and revocation are each enforced at their edges."""
    document = _document(_entry_payload())
    entry = document.entries[0]
    assertion = _assertion(issued_at='2026-08-14T18:30:05Z', expires_at='2026-08-14T18:31:00Z')
    assert _select(document, assertion) == entry
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(
            document,
            _assertion(issued_at='2026-08-14T18:30:06Z', expires_at='2026-08-14T18:31:00Z'),
        )

    expiring = _assertion(expires_at='2026-08-14T18:30:20Z')
    assert _select(document, expiring, now=NOW + timedelta(seconds=20)) == entry
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(document, expiring, now=NOW + timedelta(seconds=21))

    early = _document(_entry_payload(not_before='2026-08-14T18:30:01Z'))
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(early, _assertion())
    assert _select(_document(_entry_payload(not_before='2026-08-14T18:30:00Z')), _assertion())

    late = _document(_entry_payload(not_after='2026-08-14T18:29:59Z'))
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(late, _assertion())
    assert _select(_document(_entry_payload(not_after='2026-08-14T18:30:00Z')), _assertion())

    revoked_now = _document(_entry_payload(revoked_at='2026-08-14T18:30:00Z'))
    with pytest.raises(ValueError, match=f'^{TRUST}$'):
        _select(revoked_now, _assertion())
    revoked_later = _document(_entry_payload(revoked_at='2026-08-14T18:30:01Z'))
    assert _select(revoked_later, _assertion()) == revoked_later.entries[0]


def test_publication_control_frame_is_bounded() -> None:
    """A control frame over 16 KiB is refused before it can be bound."""
    oversized = VerifiedExportPublicationRequest.model_construct(operation_id='x' * 16_384)
    with pytest.raises(ValueError, match=f'^{BINDING}$'):
        vault_ordinary_export_publication_control_bytes(oversized)


@pytest.mark.parametrize(
    ('control', 'length', 'digest'),
    [
        (b'x' * 16_385, 1, 'd' * 64),
        (b'{}', 0, 'd' * 64),
        (b'{}', 52_428_801, 'd' * 64),
        (b'{}', 1, 'D' * 64),
        (b'{}', 1, 'd' * 62),
        (b'{}', 1, 'not-hex'),
    ],
)
def test_publication_binding_refuses_out_of_bounds_inputs(
    control: bytes,
    length: int,
    digest: str,
) -> None:
    """Control size, artifact length bounds and lower-case 32-byte digest are all enforced."""
    with pytest.raises(ValueError, match=f'^{BINDING}$'):
        vault_ordinary_export_publication_request_binding(
            control=control,
            measured_artifact_length=length,
            measured_artifact_sha256=digest,
        )


def test_publication_binding_accepts_both_inclusive_bounds() -> None:
    """One byte and exactly 50 MiB are both bindable; the control may be exactly 16 KiB."""
    for control, length in ((b'x' * 16_384, 1), (b'{}', 52_428_800)):
        binding = vault_ordinary_export_publication_request_binding(
            control=control,
            measured_artifact_length=length,
            measured_artifact_sha256='d' * 64,
        )
        assert re.fullmatch('[0-9a-f]{64}', binding)


@pytest.mark.parametrize(
    ('control', 'length', 'digest'),
    [
        ('{}', 1, 'd' * 64),
        (b'{}', True, 'd' * 64),
        (b'{}', 1.0, 'd' * 64),
        (b'{}', 1, None),
    ],
)
def test_publication_binding_refuses_wrong_types(
    control: object,
    length: object,
    digest: object,
) -> None:
    """Non-bytes control and non-int (including bool) lengths are TypeErrors; digests ValueError."""
    expected = ValueError if digest is None else TypeError
    with pytest.raises(expected, match=f'^{BINDING}$'):
        vault_ordinary_export_publication_request_binding(
            control=control,  # pyright: ignore[reportArgumentType]
            measured_artifact_length=length,  # pyright: ignore[reportArgumentType]
            measured_artifact_sha256=digest,  # pyright: ignore[reportArgumentType]
        )


def test_json_binding_accepts_only_maintenance_paths_and_bytes() -> None:
    """The publication path and non-bytes bodies are refused."""
    assert vault_ordinary_export_json_request_binding(
        fixed_path=VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH,
        body=b'{}',
    ) != vault_ordinary_export_json_request_binding(
        fixed_path=VAULT_ORDINARY_EXPORT_DELETION_PATH,
        body=b'{}',
    )
    with pytest.raises(ValueError, match=f'^{BINDING}$'):
        vault_ordinary_export_json_request_binding(
            fixed_path=VAULT_ORDINARY_EXPORT_PUBLICATION_PATH,
            body=b'{}',
        )
    with pytest.raises(TypeError, match=f'^{BINDING}$'):
        vault_ordinary_export_json_request_binding(
            fixed_path=VAULT_ORDINARY_EXPORT_DELETION_PATH,
            body='{}',  # pyright: ignore[reportArgumentType]
        )


@pytest.mark.parametrize('nonce', ['', _b64(bytes(15)), _b64(bytes(17)), f'{NONCE}='])
def test_nonce_digest_refuses_noncanonical_nonces(nonce: str) -> None:
    """Only a canonical 16-byte nonce has a replay digest."""
    with pytest.raises(ValueError, match=f'^{TRANSPORT}$'):
        vault_ordinary_export_nonce_digest(nonce)
