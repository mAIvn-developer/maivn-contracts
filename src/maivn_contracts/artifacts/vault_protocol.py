"""Canonical Vault sender assertion, request, admission, and grant protocol."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias, cast

import rfc8785
from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)

from maivn_contracts.artifacts.model import (
    ArtifactSurfaceIdentity,
    ArtifactTenantScope,
    AsciiSafeExportFilename,
    DeletionScope,
    OpaqueTokenId,
    Rfc3339Timestamp,
    Sha256Hex,
    VaultWorkRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

VaultOperation: TypeAlias = Literal[
    'ingest_file',
    'create',
    'rework',
    'retrieve_session',
    'redacted_export',
    'delete',
]


def _decode_canonical_base64url(value: object, error_code: str) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or _BASE64URL_NO_PAD_PATTERN.fullmatch(value) is None
        or len(value) % 4 == 1
    ):
        raise ValueError(error_code)
    encoded = value.encode('ascii')
    try:
        decoded = base64.b64decode(
            encoded + (b'=' * (-len(encoded) % 4)),
            altchars=b'-_',
            validate=True,
        )
    except (binascii.Error, ValueError):
        decoded = None
    if decoded is None:
        raise ValueError(error_code)
    if base64.urlsafe_b64encode(decoded).rstrip(b'=').decode('ascii') != value:
        raise ValueError(error_code)
    return decoded


def _validate_base64url_no_pad(value: str) -> str:
    _decode_canonical_base64url(value, _INVALID_BASE64URL)
    return value


Base64UrlNoPad: TypeAlias = Annotated[
    StrictStr,
    AfterValidator(_validate_base64url_no_pad),
]
ClientCapabilityHeader: TypeAlias = Literal[
    'x-maivn-grant-credential',
    'x-maivn-client-proof',
    'x-maivn-session-credential',
]

GRANT_CREDENTIAL_HEADER = 'x-maivn-grant-credential'
CLIENT_PROOF_HEADER = 'x-maivn-client-proof'
RETRIEVAL_SESSION_ID_HEADER = 'x-maivn-session-id'
RETRIEVAL_SESSION_CREDENTIAL_HEADER = 'x-maivn-session-credential'
EXPORT_FILENAME_HEADER = 'x-maivn-export-filename'
OPERATION_ID_HEADER = 'x-maivn-operation-id'
SENDER_ASSERTION_HEADER = 'x-maivn-sender-assertion'
SENDER_SIGNATURE_HEADER = 'x-maivn-sender-signature'

_CLIENT_CAPABILITY_HEADER_NAMES = frozenset(
    {
        GRANT_CREDENTIAL_HEADER,
        CLIENT_PROOF_HEADER,
        RETRIEVAL_SESSION_CREDENTIAL_HEADER,
    },
)
_PUBLIC_HEADER_NAMES = frozenset(
    {
        'content-type',
        'range',
        OPERATION_ID_HEADER,
        RETRIEVAL_SESSION_ID_HEADER,
        EXPORT_FILENAME_HEADER,
    },
)
_ASSERTION_ENVELOPE_HEADERS = frozenset(
    {SENDER_ASSERTION_HEADER, SENDER_SIGNATURE_HEADER},
)
BROWSER_TICKET_REQUEST_HEADERS = frozenset(
    _PUBLIC_HEADER_NAMES | _CLIENT_CAPABILITY_HEADER_NAMES | _ASSERTION_ENVELOPE_HEADERS,
)

_HTTP_TOKEN_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PERCENT_ENCODING_PATTERN = re.compile(r'%([0-9A-F]{2})')
_ORIGIN_FORM_PATTERN = re.compile(
    r"^/[A-Za-z0-9\-._~!$&'()*+,;=:@/%]*(?:\?[A-Za-z0-9\-._~!$&'()*+,;=:@/%?]*)?$",
)
_SHA256_HEX_PATTERN = re.compile(r'^[0-9a-f]{64}$')
_BASE64URL_NO_PAD_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')
_UNRESERVED_BYTES = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~')
_FORBIDDEN_ENCODED_BYTES = frozenset({ord('/'), ord('\\')})
_ASCII_CONTROL_LIMIT = 32
_ASCII_DELETE = 127

_REQUEST_DOMAIN = 'maivn-vault-request-v1'
_ASSERTION_DOMAIN = b'maivn-vault-assertion-v1\0'
_ADMISSION_DOMAIN = b'maivn-vault-admission-v1\0'
_BINDING_DOMAIN = b'maivn-vault-binding-v1\0'
_GRANT_HEADER_DOMAIN = b'maivn-vault-grant-header-v1\0'
_GRANT_VERIFIER_DOMAIN = b'maivn-vault-grant-verifier-v1\0'
_CLIENT_PROOF_DOMAIN = b'maivn-vault-client-proof-v1\0'
_RETRIEVAL_SESSION_CREDENTIAL_DOMAIN = b'maivn-vault-retrieval-session-credential-v1\0'
_TENANT_SCOPE_DOMAIN = b'maivn-vault-tenant-scope-v1\0'
_SURFACE_IDENTITY_DOMAIN = b'maivn-vault-surface-identity-v1\0'
_JCS_SAFE_INTEGER_MAX = (2**53) - 1
_ED25519_SIGNATURE_BYTES = 64

_DUPLICATE_HEADER = 'vault_protocol_duplicate_header'
_UNSAFE_HEADER = 'vault_protocol_unsafe_header'
_INVALID_CLIENT_HEADER_DIGESTS = 'vault_protocol_invalid_client_header_digests'
_INVALID_TARGET = 'vault_protocol_invalid_target'
_INVALID_METHOD = 'vault_protocol_invalid_method'
_INVALID_ASSERTION_LIFETIME = 'vault_sender_assertion_invalid_lifetime'
_DUPLICATE_POLICY_CLAIM = 'vault_issuer_key_policy_duplicate_claim'
_INVALID_TICKET_URL = 'vault_action_ticket_url_path_mismatch'
_INVALID_SECRET = 'vault_protocol_invalid_secret'  # noqa: S105
_INVALID_SALT = 'vault_protocol_invalid_salt'
_INVALID_STORED_SCOPE = 'vault_stored_intent_invalid_deletion_scope'
_INVALID_BASE64URL = 'vault_protocol_invalid_base64url'
_INVALID_TICKET_ASSERTION = 'vault_action_ticket_invalid_sender_assertion'
_INVALID_TICKET_SIGNATURE = 'vault_action_ticket_invalid_sender_signature'
_TICKET_ASSERTION_MISMATCH = 'vault_action_ticket_assertion_mismatch'
_UNSAFE_WORK_INTEGER = 'vault_work_request_unsafe_jcs_integer'
_INVALID_GRANT_CREDENTIAL_DELIVERY = 'vault_grant_credential_delivery_invalid'
_INVALID_RETRIEVAL_CREDENTIAL_DELIVERY = 'vault_retrieval_session_credential_delivery_invalid'

_EXPORT_FILENAME_ADAPTER: TypeAdapter[AsciiSafeExportFilename] = TypeAdapter(
    AsciiSafeExportFilename,
)


class _ClosedVaultProtocolModel(BaseModel):
    """Internal frozen, closed base for public Vault protocol models."""

    model_config = ConfigDict(extra='forbid', frozen=True)


def _jcs_bytes(payload: Any) -> bytes:
    """Return the RFC 8785 JSON Canonicalization Scheme representation."""
    return rfc8785.dumps(payload)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_jcs_safe_integers(value: object) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > _JCS_SAFE_INTEGER_MAX:
            raise ValueError(_UNSAFE_WORK_INTEGER)
        return
    if isinstance(value, float):
        if not isfinite(value) or abs(value) > _JCS_SAFE_INTEGER_MAX:
            raise ValueError(_UNSAFE_WORK_INTEGER)
        return
    if isinstance(value, dict):
        for nested_value in cast('dict[object, object]', value).values():
            _require_jcs_safe_integers(nested_value)
        return
    if isinstance(value, (list, tuple)):
        for nested_value in cast('list[object] | tuple[object, ...]', value):
            _require_jcs_safe_integers(nested_value)


def _validate_secret(value: str) -> bytes:
    _decode_canonical_base64url(value, _INVALID_SECRET)
    return value.encode('ascii')


def _secret_digest(domain: bytes, value: str) -> str:
    return _sha256(domain + _validate_secret(value))


def _validated_headers(
    headers: Mapping[str, str],
    allowed_names: frozenset[str],
) -> dict[str, str]:
    """Return sorted, lower-case, OWS-trimmed headers from one closed vocabulary."""
    canonical: dict[str, str] = {}
    for name, value in headers.items():
        if _HTTP_TOKEN_PATTERN.fullmatch(name) is None:
            raise ValueError(_UNSAFE_HEADER)
        normalized_name = name.lower()
        if normalized_name not in allowed_names:
            raise ValueError(_UNSAFE_HEADER)
        if normalized_name in canonical:
            raise ValueError(_DUPLICATE_HEADER)
        normalized_value = value.strip(' \t')
        if not normalized_value or any(
            ord(character) < _ASCII_CONTROL_LIMIT or ord(character) >= _ASCII_DELETE
            for character in normalized_value
        ):
            raise ValueError(_UNSAFE_HEADER)
        canonical[normalized_name] = normalized_value
    return dict(sorted(canonical.items()))


def _validated_public_headers(headers: Mapping[str, str]) -> dict[str, str]:
    canonical = _validated_headers(headers, _PUBLIC_HEADER_NAMES)
    if EXPORT_FILENAME_HEADER in canonical:
        try:
            _EXPORT_FILENAME_ADAPTER.validate_python(canonical[EXPORT_FILENAME_HEADER])
        except ValueError:
            valid_export_filename = False
        else:
            valid_export_filename = True
        if not valid_export_filename:
            raise ValueError(_UNSAFE_HEADER)
    return canonical


def _validated_client_header_digests(
    client_header_digests: Mapping[ClientCapabilityHeader, Sha256Hex],
) -> dict[ClientCapabilityHeader, Sha256Hex]:
    canonical: dict[ClientCapabilityHeader, Sha256Hex] = {}
    for name, value in client_header_digests.items():
        if name not in _CLIENT_CAPABILITY_HEADER_NAMES:
            raise ValueError(_INVALID_CLIENT_HEADER_DIGESTS)
        if _SHA256_HEX_PATTERN.fullmatch(value) is None:
            raise ValueError(_INVALID_CLIENT_HEADER_DIGESTS)
        canonical[name] = value
    return dict(sorted(canonical.items()))


def _require_exact_client_headers(
    actual_client_headers: frozenset[str],
    expected_client_headers: object,
) -> None:
    if (
        not isinstance(expected_client_headers, frozenset)
        or not expected_client_headers <= _CLIENT_CAPABILITY_HEADER_NAMES
        or actual_client_headers != expected_client_headers
    ):
        raise ValueError(_INVALID_CLIENT_HEADER_DIGESTS)


def _canonical_method(method: str) -> str:
    canonical = method.upper()
    if method.strip() != method or canonical not in {'GET', 'POST'}:
        raise ValueError(_INVALID_METHOD)
    return canonical


def _validated_target(path: str) -> str:
    try:
        path.encode('ascii')
    except UnicodeEncodeError:
        ascii_target = False
    else:
        ascii_target = True
    if not ascii_target:
        raise ValueError(_INVALID_TARGET)
    if (
        not path.startswith('/')
        or path.startswith('//')
        or _ORIGIN_FORM_PATTERN.fullmatch(path) is None
        or '#' in path
        or '\\' in path
        or any(ord(character) < _ASCII_CONTROL_LIMIT for character in path)
        or any(ord(character) == _ASCII_DELETE for character in path)
    ):
        raise ValueError(_INVALID_TARGET)
    path_part = path.partition('?')[0]
    if any(segment in {'.', '..'} for segment in path_part.split('/')):
        raise ValueError(_INVALID_TARGET)
    matches = tuple(_PERCENT_ENCODING_PATTERN.finditer(path))
    if path.count('%') != len(matches):
        raise ValueError(_INVALID_TARGET)
    for match in matches:
        encoded = int(match.group(1), 16)
        if encoded in _UNRESERVED_BYTES or encoded in _FORBIDDEN_ENCODED_BYTES:
            raise ValueError(_INVALID_TARGET)
    return path


def canonical_http_request_bytes(  # noqa: PLR0913 - the complete call is explicit
    method: str,
    path: str,
    body: bytes,
    public_headers: Mapping[str, str],
    client_header_digests: Mapping[ClientCapabilityHeader, Sha256Hex],
    *,
    expected_client_headers: frozenset[ClientCapabilityHeader],
) -> bytes:
    """Return exact RFC 8785 bytes without accepting a raw client capability."""
    validated_client_header_digests = _validated_client_header_digests(
        client_header_digests,
    )
    _require_exact_client_headers(
        frozenset(validated_client_header_digests),
        expected_client_headers,
    )
    return _jcs_bytes(
        {
            'domain': _REQUEST_DOMAIN,
            'method': _canonical_method(method),
            'path': _validated_target(path),
            'body_sha256': _sha256(body),
            'public_headers': _validated_public_headers(public_headers),
            'client_header_digests': validated_client_header_digests,
        },
    )


def vault_actual_request_digest_from_prehashed(  # noqa: PLR0913 - complete call is explicit
    method: str,
    path: str,
    body: bytes,
    public_headers: Mapping[str, str],
    client_header_digests: Mapping[ClientCapabilityHeader, Sha256Hex],
    *,
    expected_client_headers: frozenset[ClientCapabilityHeader],
) -> Sha256Hex:
    """Derive the issuer digest without receiving any raw client capability."""
    return _sha256(
        canonical_http_request_bytes(
            method,
            path,
            body,
            public_headers,
            client_header_digests,
            expected_client_headers=expected_client_headers,
        ),
    )


def vault_actual_request_digest_from_raw(
    method: str,
    path: str,
    body: bytes,
    actual_headers: Mapping[str, str],
    *,
    expected_client_headers: frozenset[ClientCapabilityHeader],
) -> Sha256Hex:
    """Derive the verifier digest from the raw headers received by Vault Plane."""
    headers = _validated_headers(actual_headers, BROWSER_TICKET_REQUEST_HEADERS)
    for envelope_header in _ASSERTION_ENVELOPE_HEADERS:
        headers.pop(envelope_header, None)
    _require_exact_client_headers(
        frozenset(headers) & _CLIENT_CAPABILITY_HEADER_NAMES,
        expected_client_headers,
    )
    client_header_digests: dict[ClientCapabilityHeader, Sha256Hex] = {}
    digest_functions: dict[
        ClientCapabilityHeader,
        Callable[[str], Sha256Hex],
    ] = {
        GRANT_CREDENTIAL_HEADER: vault_grant_header_digest,
        CLIENT_PROOF_HEADER: vault_client_proof_header_digest,
        RETRIEVAL_SESSION_CREDENTIAL_HEADER: vault_retrieval_session_credential_digest,
    }
    for header_name, digest_function in digest_functions.items():
        raw_value = headers.pop(header_name, None)
        if raw_value is not None:
            client_header_digests[header_name] = digest_function(raw_value)
    return vault_actual_request_digest_from_prehashed(
        method,
        path,
        body,
        headers,
        client_header_digests,
        expected_client_headers=expected_client_headers,
    )


class VaultSenderAssertion(_ClosedVaultProtocolModel):
    """Issuer-authenticated identity and exact-call binding for the Vault."""

    issuer: OpaqueTokenId
    key_id: OpaqueTokenId
    audience: OpaqueTokenId
    actor: OpaqueTokenId
    tenant_id: OpaqueTokenId
    surface: OpaqueTokenId
    surface_digest: Sha256Hex
    actual_request_digest: Sha256Hex
    issued_at: Rfc3339Timestamp
    nonce: OpaqueTokenId
    expires_at: Rfc3339Timestamp

    @model_validator(mode='after')
    def _validate_lifetime(self) -> VaultSenderAssertion:
        issued_at = datetime.fromisoformat(self.issued_at[:-1] + '+00:00')
        expires_at = datetime.fromisoformat(self.expires_at[:-1] + '+00:00')
        if expires_at <= issued_at:
            raise ValueError(_INVALID_ASSERTION_LIFETIME)
        return self


class VaultIssuerKeyPolicy(_ClosedVaultProtocolModel):
    """Trust-bundle claim bounds for one issuer signing key."""

    issuer: OpaqueTokenId
    key_id: OpaqueTokenId
    audience: OpaqueTokenId
    allowed_tenant_ids: tuple[OpaqueTokenId, ...] = Field(min_length=1)
    allowed_surfaces: tuple[OpaqueTokenId, ...] = Field(min_length=1)

    @model_validator(mode='after')
    def _validate_allowlists(self) -> VaultIssuerKeyPolicy:
        if len(self.allowed_tenant_ids) != len(set(self.allowed_tenant_ids)) or len(
            self.allowed_surfaces,
        ) != len(set(self.allowed_surfaces)):
            raise ValueError(_DUPLICATE_POLICY_CLAIM)
        return self


class VaultIntentStatusRequest(_ClosedVaultProtocolModel):
    """One value-free server-intent lookup carried only in a fixed POST body."""

    schema_version: Literal['vault-intent-status-request-v1']
    server_intent_id: OpaqueTokenId


class _VaultGrantDeliveryEnvelope(_ClosedVaultProtocolModel):
    """Credential-free preflight for every stable grant-delivery field."""

    intent_id: OpaqueTokenId
    state: Literal['executing_in_vault']
    grant_credential_digest: Sha256Hex
    credential_delivery: Literal['delivered', 'not_replayable']
    expires_at: Rfc3339Timestamp


class VaultGrantCredentialDelivery(_ClosedVaultProtocolModel):
    """Transient approval metadata with an optional first-delivery credential."""

    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)

    intent_id: OpaqueTokenId
    state: Literal['executing_in_vault']
    grant_credential_digest: Sha256Hex
    credential_delivery: Literal['delivered', 'not_replayable']
    grant_credential: Base64UrlNoPad | None = Field(default=None, repr=False)
    expires_at: Rfc3339Timestamp

    @model_validator(mode='before')
    @classmethod
    def _remove_raw_credential_from_invalid_input(cls, value: Any) -> Any:
        """Retain a raw grant only after its complete safe envelope is valid."""
        if not isinstance(value, dict):
            return value
        raw = cast('dict[str, object]', value)
        credential = raw.get('grant_credential')
        if credential is None:
            return raw
        sanitized = dict(raw)
        sanitized.pop('grant_credential', None)
        envelope_valid = False
        try:
            _VaultGrantDeliveryEnvelope.model_validate(sanitized)
            envelope_valid = True
        except PydanticValidationError:
            pass
        valid_delivery = False
        try:
            if envelope_valid and isinstance(credential, str):
                _decode_canonical_base64url(credential, _INVALID_BASE64URL)
                digest = raw.get('grant_credential_digest')
                valid_delivery = (
                    raw.get('credential_delivery') == 'delivered'
                    and isinstance(digest, str)
                    and hmac.compare_digest(vault_grant_header_digest(credential), digest)
                )
        except (TypeError, ValueError):
            valid_delivery = False
        if valid_delivery:
            return raw
        return {'credential_delivery': 'invalid_sensitive_delivery'}

    @model_validator(mode='after')
    def _validate_one_shot_delivery(self) -> VaultGrantCredentialDelivery:
        delivered = self.credential_delivery == 'delivered'
        if delivered != (self.grant_credential is not None):
            raise ValueError(_INVALID_GRANT_CREDENTIAL_DELIVERY) from None
        if self.grant_credential is not None and not hmac.compare_digest(
            vault_grant_header_digest(self.grant_credential),
            self.grant_credential_digest,
        ):
            raise ValueError(_INVALID_GRANT_CREDENTIAL_DELIVERY) from None
        return self


class _VaultRetrievalSessionDeliveryEnvelope(_ClosedVaultProtocolModel):
    """Credential-free preflight for every stable delivery field."""

    schema_version: Literal['vault-retrieval-session-credential-delivery-v1']
    session_id: OpaqueTokenId
    session_credential_digest: Sha256Hex
    credential_delivery: Literal['delivered', 'not_replayable']
    expires_at: Rfc3339Timestamp


class VaultRetrievalSessionCredentialDelivery(_ClosedVaultProtocolModel):
    """Transient retrieval metadata with an optional first-delivery credential."""

    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)

    schema_version: Literal['vault-retrieval-session-credential-delivery-v1']
    session_id: OpaqueTokenId
    session_credential_digest: Sha256Hex
    credential_delivery: Literal['delivered', 'not_replayable']
    session_credential: Base64UrlNoPad | None = Field(default=None, repr=False)
    expires_at: Rfc3339Timestamp

    @model_validator(mode='before')
    @classmethod
    def _remove_raw_credential_from_invalid_input(cls, value: Any) -> Any:
        """Make every sensitive validation failure retain only fixed safe input."""
        if not isinstance(value, dict):
            return value
        raw = cast('dict[str, object]', value)
        credential = raw.get('session_credential')
        if credential is None:
            return raw
        sanitized = dict(raw)
        sanitized.pop('session_credential', None)
        envelope_valid = False
        try:
            _VaultRetrievalSessionDeliveryEnvelope.model_validate(sanitized)
            envelope_valid = True
        except PydanticValidationError:
            pass
        valid_delivery = False
        try:
            if envelope_valid and isinstance(credential, str):
                _decode_canonical_base64url(credential, _INVALID_BASE64URL)
                digest = raw.get('session_credential_digest')
                valid_delivery = (
                    raw.get('credential_delivery') == 'delivered'
                    and isinstance(digest, str)
                    and hmac.compare_digest(
                        vault_retrieval_session_credential_digest(credential),
                        digest,
                    )
                )
        except (TypeError, ValueError):
            valid_delivery = False
        if valid_delivery:
            return raw
        return {'credential_delivery': 'invalid_sensitive_delivery'}

    @model_validator(mode='after')
    def _validate_one_shot_delivery(self) -> VaultRetrievalSessionCredentialDelivery:
        delivered = self.credential_delivery == 'delivered'
        if delivered != (self.session_credential is not None):
            raise ValueError(_INVALID_RETRIEVAL_CREDENTIAL_DELIVERY) from None
        if self.session_credential is not None and not hmac.compare_digest(
            vault_retrieval_session_credential_digest(self.session_credential),
            self.session_credential_digest,
        ):
            raise ValueError(_INVALID_RETRIEVAL_CREDENTIAL_DELIVERY) from None
        return self


def _closed_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(_INVALID_TICKET_ASSERTION)
        result[name] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError(_INVALID_TICKET_ASSERTION)


def decode_vault_sender_assertion(value: Base64UrlNoPad) -> VaultSenderAssertion:
    """Decode one canonical, closed sender assertion from its HTTP header value."""
    assertion_bytes = _decode_canonical_base64url(value, _INVALID_TICKET_ASSERTION)
    try:
        assertion_payload = json.loads(
            assertion_bytes.decode('utf-8'),
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_json_constant,
        )
        assertion = VaultSenderAssertion.model_validate(assertion_payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        PydanticValidationError,
        ValueError,
    ):
        assertion = None
    if assertion is None:
        raise ValueError(_INVALID_TICKET_ASSERTION)
    if _jcs_bytes(assertion.model_dump(mode='json')) != assertion_bytes:
        raise ValueError(_INVALID_TICKET_ASSERTION)
    return assertion


def decode_vault_sender_signature(value: Base64UrlNoPad) -> bytes:
    """Decode one canonical, exactly Ed25519-sized sender signature."""
    signature = _decode_canonical_base64url(value, _INVALID_TICKET_SIGNATURE)
    if len(signature) != _ED25519_SIGNATURE_BYTES:
        raise ValueError(_INVALID_TICKET_SIGNATURE)
    return signature


class VaultActionTicket(_ClosedVaultProtocolModel):
    """One browser-safe call with only public headers and capability digests."""

    method: Literal['GET', 'POST']
    path: StrictStr
    url: AnyHttpUrl
    public_headers: dict[StrictStr, StrictStr]
    client_header_digests: dict[ClientCapabilityHeader, Sha256Hex]
    sender_assertion_base64url: Base64UrlNoPad
    sender_signature_base64url: Base64UrlNoPad
    body_base64url: Base64UrlNoPad | None
    expires_at: Rfc3339Timestamp

    @field_validator('path')
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _validated_target(value)

    @field_validator('public_headers')
    @classmethod
    def _canonicalize_public_headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _validated_public_headers(value)

    @field_validator('client_header_digests')
    @classmethod
    def _canonicalize_client_header_digests(
        cls,
        value: dict[ClientCapabilityHeader, Sha256Hex],
    ) -> dict[ClientCapabilityHeader, Sha256Hex]:
        return _validated_client_header_digests(value)

    @field_validator('sender_assertion_base64url')
    @classmethod
    def _validate_sender_assertion(cls, value: str) -> str:
        decode_vault_sender_assertion(value)
        return value

    @field_validator('sender_signature_base64url')
    @classmethod
    def _validate_sender_signature(cls, value: str) -> str:
        decode_vault_sender_signature(value)
        return value

    @field_validator('body_base64url')
    @classmethod
    def _validate_body(cls, value: str | None) -> str | None:
        if value is not None:
            _decode_canonical_base64url(value, _INVALID_BASE64URL)
        return value

    @model_validator(mode='after')
    def _validate_url_target(self) -> VaultActionTicket:
        url_path = self.url.path
        if self.url.query:
            url_path = f'{url_path}?{self.url.query}'
        if (
            self.url.fragment is not None
            or self.url.username is not None
            or self.url.password is not None
            or url_path != self.path
        ):
            raise ValueError(_INVALID_TICKET_URL)
        body = (
            b''
            if self.body_base64url is None
            else _decode_canonical_base64url(self.body_base64url, _INVALID_BASE64URL)
        )
        assertion = decode_vault_sender_assertion(self.sender_assertion_base64url)
        expected_client_headers = frozenset(self.client_header_digests)
        actual_request_digest = vault_actual_request_digest_from_prehashed(
            self.method,
            self.path,
            body,
            self.public_headers,
            self.client_header_digests,
            expected_client_headers=expected_client_headers,
        )
        if (
            assertion.actual_request_digest != actual_request_digest
            or assertion.expires_at != self.expires_at
        ):
            raise ValueError(_TICKET_ASSERTION_MISMATCH)
        return self

    def declared_request_header_names(self) -> frozenset[str]:
        """Return every header the client must attach to the declared request."""
        declared = frozenset(
            {*self.public_headers, *self.client_header_digests, *_ASSERTION_ENVELOPE_HEADERS},
        )
        if not declared <= BROWSER_TICKET_REQUEST_HEADERS:
            raise ValueError(_UNSAFE_HEADER)
        return declared

    def require_client_header_digests(
        self,
        expected_client_headers: frozenset[ClientCapabilityHeader],
    ) -> None:
        """Refuse a ticket whose capability declarations differ from its route profile."""
        _require_exact_client_headers(
            frozenset(self.client_header_digests),
            expected_client_headers,
        )


class _VerifiedIntentIdentity(_ClosedVaultProtocolModel):
    issuer: OpaqueTokenId
    actor: OpaqueTokenId
    tenant_id: OpaqueTokenId
    surface: OpaqueTokenId


class _OperationBinding(_ClosedVaultProtocolModel):
    intent_id: StrictStr
    issuer: OpaqueTokenId
    actor: OpaqueTokenId
    tenant_id: OpaqueTokenId
    surface: OpaqueTokenId
    operation: VaultOperation
    admission_fingerprint: Sha256Hex
    deletion_scope: DeletionScope | None

    @model_validator(mode='after')
    def _validate_deletion_scope(self) -> _OperationBinding:
        if (self.operation == 'delete') != (self.deletion_scope is not None):
            raise ValueError(_INVALID_STORED_SCOPE)
        return self


def vault_assertion_json_bytes(assertion: VaultSenderAssertion) -> bytes:
    """Return the exact RFC 8785 assertion JSON transported in the envelope."""
    return _jcs_bytes(assertion.model_dump(mode='json'))


def vault_assertion_signing_bytes(assertion: VaultSenderAssertion) -> bytes:
    """Return the NUL-separated domain and exact assertion JSON Ed25519 signs."""
    return _ASSERTION_DOMAIN + vault_assertion_json_bytes(assertion)


def vault_tenant_claim(scope: ArtifactTenantScope) -> Sha256Hex:
    """Derive the opaque tenant claim from the exact structured tenant scope."""
    return _sha256(_TENANT_SCOPE_DOMAIN + _jcs_bytes(scope.model_dump(mode='json')))


def vault_surface_identity_digest(surface: ArtifactSurfaceIdentity) -> Sha256Hex:
    """Derive the signed digest of the exact structured invocation surface."""
    return _sha256(_SURFACE_IDENTITY_DOMAIN + _jcs_bytes(surface.model_dump(mode='json')))


def vault_work_request_json_bytes(work: VaultWorkRequest) -> bytes:
    """Return the only canonical request body accepted at Vault work boundaries."""
    payload = work.model_dump(mode='json', exclude_none=True)
    _require_jcs_safe_integers(payload)
    return _jcs_bytes(payload)


def vault_intent_status_request_json_bytes(request: VaultIntentStatusRequest) -> bytes:
    """Return the exact canonical fixed-path internal status request body."""
    return _jcs_bytes(request.model_dump(mode='json'))


def vault_admission_fingerprint(
    work: VaultWorkRequest,
    *,
    issuer: str,
    actor: str,
    tenant_id: str,
    surface: str,
) -> Sha256Hex:
    """Bind verified identity to the complete canonical admitted work request."""
    identity = _VerifiedIntentIdentity(
        issuer=issuer,
        actor=actor,
        tenant_id=tenant_id,
        surface=surface,
    )
    work_payload = work.model_dump(mode='json', exclude_none=True)
    _require_jcs_safe_integers(work_payload)
    payload = {
        **identity.model_dump(mode='json'),
        'work': work_payload,
    }
    return _sha256(_ADMISSION_DOMAIN + _jcs_bytes(payload))


def vault_operation_binding_digest(  # noqa: PLR0913 - every authority field is explicit
    *,
    intent_id: uuid.UUID,
    issuer: str,
    actor: str,
    tenant_id: str,
    surface: str,
    operation: VaultOperation,
    admission_fingerprint: Sha256Hex,
    deletion_scope: DeletionScope | None,
) -> Sha256Hex:
    """Bind one stored admitted intent to exactly one authorized operation effect."""
    binding = _OperationBinding(
        intent_id=str(uuid.UUID(str(intent_id))),
        issuer=issuer,
        actor=actor,
        tenant_id=tenant_id,
        surface=surface,
        operation=operation,
        admission_fingerprint=admission_fingerprint,
        deletion_scope=deletion_scope,
    )
    payload = {
        'intent_id': str(binding.intent_id),
        'issuer': binding.issuer,
        'actor': binding.actor,
        'tenant': binding.tenant_id,
        'surface': binding.surface,
        'operation': binding.operation,
        'admission_fingerprint': binding.admission_fingerprint,
        'deletion_scope': binding.deletion_scope,
    }
    return _sha256(_BINDING_DOMAIN + _jcs_bytes(payload))


def vault_grant_header_digest(credential: str) -> Sha256Hex:
    """Return the domain-separated grant digest declared to Data Plane."""
    return _secret_digest(_GRANT_HEADER_DOMAIN, credential)


def vault_client_proof_header_digest(client_proof: str) -> Sha256Hex:
    """Return the domain-separated client-proof digest declared to Data Plane."""
    return _secret_digest(_CLIENT_PROOF_DOMAIN, client_proof)


def vault_retrieval_session_credential_digest(credential: str) -> Sha256Hex:
    """Return the domain-separated retrieval-session credential digest."""
    return _secret_digest(_RETRIEVAL_SESSION_CREDENTIAL_DOMAIN, credential)


def vault_grant_verifier(credential: str, salt: bytes) -> Sha256Hex:
    """Return the salted domain-separated verifier stored for a one-use grant."""
    if not salt:
        raise ValueError(_INVALID_SALT)
    return _sha256(
        _GRANT_VERIFIER_DOMAIN + salt + b'\0' + _validate_secret(credential),
    )
