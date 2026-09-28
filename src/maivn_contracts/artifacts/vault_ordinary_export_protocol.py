"""Canonical Vault workload authentication for ordinary export operations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import struct
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, TypeAlias

import rfc8785
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

from maivn_contracts.artifacts.model import (
    OpaqueTokenId,
    OrdinaryExportDeletionRequest,
    OrdinaryExportDeletionStatusRequest,
    Rfc3339Timestamp,
    Sha256Hex,
    VerifiedExportPublicationRequest,
)

VAULT_ORDINARY_EXPORT_ASSERTION_HEADER = 'x-maivn-vault-service-assertion'
VAULT_ORDINARY_EXPORT_SIGNATURE_HEADER = 'x-maivn-vault-service-signature'
VAULT_ORDINARY_EXPORT_AUDIENCE = 'maivn-data-plane-ordinary-export-v1'
VAULT_ORDINARY_EXPORT_PUBLICATION_PATH = '/internal/v1/vault/ordinary-exports/publications'
VAULT_ORDINARY_EXPORT_DELETION_PATH = '/internal/v1/vault/ordinary-exports/deletions'
VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH = '/internal/v1/vault/ordinary-exports/deletion-status'

VaultOrdinaryExportRole: TypeAlias = Literal['executor', 'maintenance']
VaultOrdinaryExportPath: TypeAlias = Literal[
    '/internal/v1/vault/ordinary-exports/publications',
    '/internal/v1/vault/ordinary-exports/deletions',
    '/internal/v1/vault/ordinary-exports/deletion-status',
]
RawHeaderMultimap: TypeAlias = tuple[tuple[bytes, bytes], ...]

_ASSERTION_DOMAIN = b'maivn-vault-ordinary-export-assertion-v1\0'
_PUBLICATION_BINDING_DOMAIN = b'maivn-vault-ordinary-export-publication-request-v1\0'
_JSON_BINDING_DOMAIN = b'maivn-vault-ordinary-export-json-request-v1\0'
_NONCE_DOMAIN = b'maivn-vault-ordinary-export-assertion-nonce-v1\0'
_MAX_ASSERTION_TTL = timedelta(seconds=60)
_MAX_FUTURE_SKEW = timedelta(seconds=5)
_MAX_CONTROL_BYTES = 16 * 1024
_MAX_ARTIFACT_BYTES = 52_428_800
_MAX_UINT32 = 0xFFFF_FFFF
_SHA256_BYTES = 32
_ED25519_SIGNATURE_BYTES = 64
_VISIBLE_ASCII_MIN = 33
_VISIBLE_ASCII_MAX = 126
_BASE64URL_CHARS = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')
_ROLE_PATHS: dict[VaultOrdinaryExportRole, tuple[VaultOrdinaryExportPath, ...]] = {
    'executor': (VAULT_ORDINARY_EXPORT_PUBLICATION_PATH,),
    'maintenance': (
        VAULT_ORDINARY_EXPORT_DELETION_PATH,
        VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH,
    ),
}
_FORBIDDEN_HEADERS = frozenset(
    {
        b'authorization',
        b'cookie',
        b'x-maivn-signature',
        b'x-maivn-sender-assertion',
        b'x-maivn-sender-signature',
    },
)
_TRANSPORT_INVALID = 'vault_ordinary_export_transport_invalid'
_ASSERTION_INVALID = 'vault_ordinary_export_assertion_invalid'
_TRUST_INVALID = 'vault_ordinary_export_trust_invalid'
_BINDING_INVALID = 'vault_ordinary_export_binding_invalid'


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + '+00:00').astimezone(timezone.utc)


def _canonical_base64url(value: object, *, size: int) -> bytes:
    if not isinstance(value, str) or not value or '=' in value:
        raise ValueError(_TRANSPORT_INVALID)
    try:
        encoded = value.encode('ascii')
    except UnicodeEncodeError as error:
        raise ValueError(_TRANSPORT_INVALID) from error
    if any(character not in _BASE64URL_CHARS for character in encoded):
        raise ValueError(_TRANSPORT_INVALID)
    try:
        decoded = base64.b64decode(
            encoded + (b'=' * (-len(encoded) % 4)),
            altchars=b'-_',
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError(_TRANSPORT_INVALID) from error
    if len(decoded) != size or base64.urlsafe_b64encode(decoded).rstrip(b'=') != encoded:
        raise ValueError(_TRANSPORT_INVALID)
    return decoded


def _validate_nonce(value: str) -> str:
    _canonical_base64url(value, size=16)
    return value


NonceBase64Url: TypeAlias = Annotated[StrictStr, AfterValidator(_validate_nonce)]


def _value_free_invalid() -> dict[str, str]:
    return {'schema_version': 'invalid'}


def _require_bytes(value: object, error_code: str) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(error_code)
    return value


def _require_exact_int(value: object, error_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(error_code)
    return value


class _ServiceAssertionEnvelope(_ClosedModel):
    schema_version: Literal['vault-ordinary-export-assertion-v1']
    issuer: OpaqueTokenId
    key_id: OpaqueTokenId
    audience: Literal['maivn-data-plane-ordinary-export-v1']
    role: VaultOrdinaryExportRole
    method: Literal['POST']
    fixed_path: VaultOrdinaryExportPath
    request_binding: Sha256Hex
    issued_at: Rfc3339Timestamp
    expires_at: Rfc3339Timestamp
    nonce: NonceBase64Url

    @model_validator(mode='after')
    def _validate_role_path_and_lifetime(self) -> _ServiceAssertionEnvelope:
        issued_at = _parse_timestamp(self.issued_at)
        expires_at = _parse_timestamp(self.expires_at)
        if (
            self.fixed_path not in _ROLE_PATHS[self.role]
            or expires_at <= issued_at
            or expires_at - issued_at > _MAX_ASSERTION_TTL
        ):
            raise ValueError(_ASSERTION_INVALID)
        return self


class VaultOrdinaryExportServiceAssertion(_ServiceAssertionEnvelope):
    """Closed short-lived Ed25519 claims for one fixed ordinary-export call."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        try:
            parsed = _ServiceAssertionEnvelope.model_validate(value)
        except (TypeError, ValueError):
            return _value_free_invalid()
        return parsed.model_dump(mode='json')

    def __repr__(self) -> str:
        """Keep service claims out of diagnostic representations."""
        return 'VaultOrdinaryExportServiceAssertion(<redacted>)'

    __str__ = __repr__


class _TrustEntryEnvelope(_ClosedModel):
    peer_leaf_certificate_sha256: Sha256Hex
    issuer: OpaqueTokenId
    key_id: OpaqueTokenId
    ed25519_public_key_base64url: StrictStr
    role: VaultOrdinaryExportRole
    audience: Literal['maivn-data-plane-ordinary-export-v1']
    allowed_paths: tuple[VaultOrdinaryExportPath, ...]
    not_before: Rfc3339Timestamp
    not_after: Rfc3339Timestamp
    revoked_at: Rfc3339Timestamp | None = None

    @field_validator('ed25519_public_key_base64url')
    @classmethod
    def _validate_public_key(cls, value: str) -> str:
        _canonical_base64url(value, size=32)
        return value

    @model_validator(mode='after')
    def _validate_role_paths_and_time(self) -> _TrustEntryEnvelope:
        if self.allowed_paths != _ROLE_PATHS[self.role] or _parse_timestamp(
            self.not_after
        ) <= _parse_timestamp(self.not_before):
            raise ValueError(_TRUST_INVALID)
        return self


class VaultOrdinaryExportTrustEntry(_TrustEntryEnvelope):
    """One pinned mTLS peer and Ed25519 workload authority."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        try:
            parsed = _TrustEntryEnvelope.model_validate(value)
        except (TypeError, ValueError):
            return _value_free_invalid()
        return parsed.model_dump(mode='json')

    def __repr__(self) -> str:
        """Keep pinned trust claims out of diagnostic representations."""
        return 'VaultOrdinaryExportTrustEntry(<redacted>)'

    __str__ = __repr__


class _TrustDocumentEnvelope(_ClosedModel):
    schema_version: Literal['vault-ordinary-export-trust-v1']
    entries: Annotated[tuple[VaultOrdinaryExportTrustEntry, ...], Field(min_length=1)]

    @model_validator(mode='after')
    def _validate_unique_authorities(self) -> _TrustDocumentEnvelope:
        identities: set[tuple[str, str, str]] = set()
        peers: dict[str, tuple[str, VaultOrdinaryExportRole]] = {}
        for entry in self.entries:
            identity = (
                entry.peer_leaf_certificate_sha256,
                entry.issuer,
                entry.key_id,
            )
            peer_authority = (entry.issuer, entry.role)
            if identity in identities or (
                entry.peer_leaf_certificate_sha256 in peers
                and peers[entry.peer_leaf_certificate_sha256] != peer_authority
            ):
                raise ValueError(_TRUST_INVALID)
            identities.add(identity)
            peers[entry.peer_leaf_certificate_sha256] = peer_authority
        return self


class VaultOrdinaryExportTrustDocument(_TrustDocumentEnvelope):
    """Closed mounted trust document for Vault workload identities."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        try:
            parsed = _TrustDocumentEnvelope.model_validate(value)
        except (TypeError, ValueError):
            return _value_free_invalid()
        return parsed.model_dump(mode='json')

    def __repr__(self) -> str:
        """Keep the mounted trust set out of diagnostic representations."""
        return 'VaultOrdinaryExportTrustDocument(<redacted>)'

    __str__ = __repr__


def vault_ordinary_export_assertion_json_bytes(
    assertion: VaultOrdinaryExportServiceAssertion,
) -> bytes:
    """Return the exact RFC8785 assertion bytes transported in the header."""
    return rfc8785.dumps(assertion.model_dump(mode='json'))


def vault_ordinary_export_assertion_signing_bytes(
    assertion: VaultOrdinaryExportServiceAssertion,
) -> bytes:
    """Return the exact domain-separated Ed25519 signing bytes."""
    return _ASSERTION_DOMAIN + vault_ordinary_export_assertion_json_bytes(assertion)


def encode_vault_ordinary_export_assertion(
    assertion: VaultOrdinaryExportServiceAssertion,
) -> str:
    """Encode the exact assertion JSON as canonical unpadded base64url."""
    return (
        base64.urlsafe_b64encode(
            vault_ordinary_export_assertion_json_bytes(assertion),
        )
        .rstrip(b'=')
        .decode('ascii')
    )


def encode_vault_ordinary_export_signature(signature: bytes) -> str:
    """Encode exactly one 64-byte Ed25519 signature for raw HTTP transport."""
    checked = _require_bytes(signature, _TRANSPORT_INVALID)
    if len(checked) != _ED25519_SIGNATURE_BYTES:
        raise ValueError(_TRANSPORT_INVALID)
    return base64.urlsafe_b64encode(checked).rstrip(b'=').decode('ascii')


def _decode_unbounded_base64url(value: object) -> bytes:
    if not isinstance(value, str) or not value or '=' in value:
        raise ValueError(_TRANSPORT_INVALID)
    try:
        encoded = value.encode('ascii')
    except UnicodeEncodeError as error:
        raise ValueError(_TRANSPORT_INVALID) from error
    if any(character not in _BASE64URL_CHARS for character in encoded):
        raise ValueError(_TRANSPORT_INVALID)
    try:
        decoded = base64.b64decode(
            encoded + (b'=' * (-len(encoded) % 4)),
            altchars=b'-_',
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError(_TRANSPORT_INVALID) from error
    if base64.urlsafe_b64encode(decoded).rstrip(b'=') != encoded:
        raise ValueError(_TRANSPORT_INVALID)
    return decoded


def decode_vault_ordinary_export_assertion(
    value: object,
) -> VaultOrdinaryExportServiceAssertion:
    """Decode one canonical assertion transport with duplicate-key refusal."""
    raw = _decode_unbounded_base64url(value)

    def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, nested_value in pairs:
            if key in result:
                raise ValueError(_TRANSPORT_INVALID)
            result[key] = nested_value
        return result

    assertion: VaultOrdinaryExportServiceAssertion | None = None
    try:
        payload = json.loads(raw, object_pairs_hook=_closed_object)
        assertion = VaultOrdinaryExportServiceAssertion.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    if assertion is None or vault_ordinary_export_assertion_json_bytes(assertion) != raw:
        raise ValueError(_TRANSPORT_INVALID)
    return assertion


def decode_vault_ordinary_export_signature(value: object) -> bytes:
    """Decode exactly one canonical 64-byte Ed25519 signature."""
    return _canonical_base64url(value, size=_ED25519_SIGNATURE_BYTES)


def _strict_transport_header_value(raw_name: bytes, raw_value: bytes) -> str:
    name = raw_name.lower()
    if (
        raw_name != name
        or not raw_value
        or raw_value != raw_value.strip(b' \t')
        or b',' in raw_value
        or b'=' in raw_value
        or any(
            character < _VISIBLE_ASCII_MIN or character > _VISIBLE_ASCII_MAX
            for character in raw_value
        )
    ):
        raise ValueError(_TRANSPORT_INVALID)
    try:
        return raw_value.decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError(_TRANSPORT_INVALID) from error


def decode_vault_ordinary_export_assertion_headers(
    headers: RawHeaderMultimap,
) -> tuple[VaultOrdinaryExportServiceAssertion, bytes]:
    """Extract the exact two assertion headers from a raw ASGI multimap."""
    assertion_value: str | None = None
    signature_value: str | None = None
    for raw_name, raw_value in headers:
        checked_name = _require_bytes(raw_name, _TRANSPORT_INVALID)
        checked_value = _require_bytes(raw_value, _TRANSPORT_INVALID)
        name = checked_name.lower()
        if name in _FORBIDDEN_HEADERS:
            raise ValueError(_TRANSPORT_INVALID)
        if name not in {
            VAULT_ORDINARY_EXPORT_ASSERTION_HEADER.encode('ascii'),
            VAULT_ORDINARY_EXPORT_SIGNATURE_HEADER.encode('ascii'),
        }:
            continue
        value = _strict_transport_header_value(checked_name, checked_value)
        if name == VAULT_ORDINARY_EXPORT_ASSERTION_HEADER.encode('ascii'):
            if assertion_value is not None:
                raise ValueError(_TRANSPORT_INVALID)
            assertion_value = value
        else:
            if signature_value is not None:
                raise ValueError(_TRANSPORT_INVALID)
            signature_value = value
    if assertion_value is None or signature_value is None:
        raise ValueError(_TRANSPORT_INVALID)
    return (
        decode_vault_ordinary_export_assertion(assertion_value),
        decode_vault_ordinary_export_signature(signature_value),
    )


def vault_ordinary_export_publication_control_bytes(
    request: VerifiedExportPublicationRequest,
) -> bytes:
    """Return the exact bounded control frame preceding publication bytes."""
    control = rfc8785.dumps(request.model_dump(mode='json'))
    if len(control) > _MAX_CONTROL_BYTES:
        raise ValueError(_BINDING_INVALID)
    return control


def vault_ordinary_export_publication_request_binding(
    *,
    control: bytes,
    measured_artifact_length: int,
    measured_artifact_sha256: Sha256Hex,
) -> Sha256Hex:
    """Bind exact control bytes to a measured bounded artifact stream."""
    checked_control = _require_bytes(control, _BINDING_INVALID)
    checked_length = _require_exact_int(measured_artifact_length, _BINDING_INVALID)
    if (
        len(checked_control) > _MAX_CONTROL_BYTES
        or checked_length < 1
        or checked_length > _MAX_ARTIFACT_BYTES
    ):
        raise ValueError(_BINDING_INVALID)
    try:
        digest = bytes.fromhex(measured_artifact_sha256)
    except (TypeError, ValueError) as error:
        raise ValueError(_BINDING_INVALID) from error
    if len(digest) != _SHA256_BYTES or digest.hex() != measured_artifact_sha256:
        raise ValueError(_BINDING_INVALID)
    preimage = (
        _PUBLICATION_BINDING_DOMAIN
        + b'POST\0'
        + VAULT_ORDINARY_EXPORT_PUBLICATION_PATH.encode('ascii')
        + b'\0'
        + struct.pack('!I', len(checked_control))
        + checked_control
        + struct.pack('!Q', checked_length)
        + digest
    )
    return hashlib.sha256(preimage).hexdigest()


JsonOrdinaryExportRequest: TypeAlias = (
    OrdinaryExportDeletionRequest | OrdinaryExportDeletionStatusRequest
)


def vault_ordinary_export_json_body_bytes(request: JsonOrdinaryExportRequest) -> bytes:
    """Return exact RFC8785 JSON for maintenance delete/status requests."""
    return rfc8785.dumps(request.model_dump(mode='json'))


def vault_ordinary_export_json_request_binding(
    *, fixed_path: VaultOrdinaryExportPath, body: bytes
) -> Sha256Hex:
    """Bind an exact closed JSON request to its fixed maintenance path."""
    checked_body = _require_bytes(body, _BINDING_INVALID)
    if (
        fixed_path
        not in {
            VAULT_ORDINARY_EXPORT_DELETION_PATH,
            VAULT_ORDINARY_EXPORT_DELETION_STATUS_PATH,
        }
        or len(checked_body) > _MAX_UINT32
    ):
        raise ValueError(_BINDING_INVALID)
    preimage = (
        _JSON_BINDING_DOMAIN
        + b'POST\0'
        + fixed_path.encode('ascii')
        + b'\0'
        + struct.pack('!I', len(checked_body))
        + checked_body
    )
    return hashlib.sha256(preimage).hexdigest()


def vault_ordinary_export_nonce_digest(nonce: NonceBase64Url) -> Sha256Hex:
    """Return the global replay digest without decoding or persisting the nonce."""
    _canonical_base64url(nonce, size=16)
    return hashlib.sha256(_NONCE_DOMAIN + nonce.encode('ascii')).hexdigest()


def select_vault_ordinary_export_trust_entry(
    *,
    document: VaultOrdinaryExportTrustDocument,
    assertion: VaultOrdinaryExportServiceAssertion,
    peer_leaf_certificate_sha256: Sha256Hex,
    now: datetime,
) -> VaultOrdinaryExportTrustEntry:
    """Select exactly one current trust entry for pinned peer and assertion claims."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(_TRUST_INVALID)
    now_utc = now.astimezone(timezone.utc)
    issued_at = _parse_timestamp(assertion.issued_at)
    expires_at = _parse_timestamp(assertion.expires_at)
    matches = tuple(
        entry
        for entry in document.entries
        if hmac.compare_digest(
            entry.peer_leaf_certificate_sha256,
            peer_leaf_certificate_sha256,
        )
        and entry.issuer == assertion.issuer
        and entry.key_id == assertion.key_id
        and entry.role == assertion.role
        and entry.audience == assertion.audience
        and assertion.fixed_path in entry.allowed_paths
    )
    if len(matches) != 1:
        raise ValueError(_TRUST_INVALID)
    selected = matches[0]
    revoked_at = None if selected.revoked_at is None else _parse_timestamp(selected.revoked_at)
    if (
        issued_at > now_utc + _MAX_FUTURE_SKEW
        or now_utc > expires_at
        or now_utc < _parse_timestamp(selected.not_before)
        or now_utc > _parse_timestamp(selected.not_after)
        or (revoked_at is not None and now_utc >= revoked_at)
    ):
        raise ValueError(_TRUST_INVALID)
    return selected
