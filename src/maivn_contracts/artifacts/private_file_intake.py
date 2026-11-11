"""Private generated output/source commitments and exact revision selection."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Literal, TypeVar

from pydantic import Field, StrictInt, model_validator

from maivn_contracts.artifacts.primitives import (
    MIME_TYPES_BY_KIND,
    ArtifactRefInvariantError,
    ClosedModel,
    JcsPositiveStrictInt,
    MimeType,
    OpaqueTokenId,
    Rfc3339Timestamp,
    Sha256Hex,
)
from maivn_contracts.artifacts.refs import PrivateArtifactRef  # noqa: TC001 - Pydantic field.

if TYPE_CHECKING:
    from collections.abc import Callable

_DOMAIN = b'maivn-vault-file-intake-v1\0'
_MAX_SOURCE_BYTES = 52_428_800
_Commitment = TypeVar('_Commitment')


class VaultFileIntakeManifest(ClosedModel):
    """Value-free declarations for an exact private output and editable source."""

    kind: Literal['document', 'spreadsheet', 'presentation', 'image', 'other']
    mime_type: MimeType
    output_commitment: Sha256Hex
    source_commitment: Sha256Hex
    max_source_bytes: JcsPositiveStrictInt = Field(le=_MAX_SOURCE_BYTES)
    source_format: Literal['maivn-source-archive-v1'] = 'maivn-source-archive-v1'
    expected_base_ref: PrivateArtifactRef | None = None

    @model_validator(mode='after')
    def _validate_format_and_base(self) -> VaultFileIntakeManifest:
        if self.mime_type not in MIME_TYPES_BY_KIND[self.kind]:
            raise ArtifactRefInvariantError
        if self.expected_base_ref is not None and (
            self.expected_base_ref.kind != self.kind
            or self.expected_base_ref.mime_type != self.mime_type
            or self.expected_base_ref.state != 'available_in_vault'
        ):
            raise ArtifactRefInvariantError
        return self


class PrivateFileIntakePrepareRequest(ClosedModel):
    """Prepare exact work for one authenticated active SDK tool output."""

    session_id: OpaqueTokenId
    call_id: OpaqueTokenId
    output_index: StrictInt = Field(ge=0, le=128)
    file_intake: VaultFileIntakeManifest
    client_proof_digest: Sha256Hex


class VaultFileIntakeSession(ClosedModel):
    """An upload route bound to previously authorized exact work and proof."""

    server_intent_id: OpaqueTokenId
    operation_id: OpaqueTokenId
    upload_id: OpaqueTokenId
    expires_at: Rfc3339Timestamp
    state: Literal['accepting'] = 'accepting'


class VaultFileIntakePartSealed(ClosedModel):
    """A fixed completion marker carrying no private byte measurements."""

    state: Literal['sealed'] = 'sealed'


def vault_file_intake_hasher(
    client_proof: str,
    part: Literal['private_original', 'editable_source'],
) -> hmac.HMAC:
    """Start a streaming exact-content commitment under a private client proof."""
    return initialize_file_intake_commitment(
        client_proof,
        part,
        lambda key, prefix: hmac.new(key, prefix, 'sha256'),
    )


def initialize_file_intake_commitment(
    client_proof: str,
    part: Literal['private_original', 'editable_source'],
    factory: Callable[[bytes, bytes], _Commitment],
) -> _Commitment:
    """Start the chosen HMAC-SHA256 primitive with the canonical key and prefix."""
    # Delay this import because vault_work imports the manifest above.
    from maivn_contracts.artifacts.vault_protocol import (  # noqa: PLC0415
        vault_client_proof_header_digest,
    )

    vault_client_proof_header_digest(client_proof)
    if part not in {'private_original', 'editable_source'}:
        raise ArtifactRefInvariantError
    return factory(client_proof.encode('ascii'), _DOMAIN + part.encode('ascii') + b'\0')


def vault_file_intake_commitment(
    client_proof: str,
    part: Literal['private_original', 'editable_source'],
    content: bytes,
) -> str:
    """Commit to one private part without exposing its unkeyed content digest."""
    digest = vault_file_intake_hasher(client_proof, part)
    digest.update(content)
    return digest.hexdigest()
