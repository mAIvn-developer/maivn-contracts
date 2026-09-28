"""Exact, capability-free private message attachment resolution requests."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from rfc8785 import dumps

from maivn_contracts.artifacts.primitives import (
    ArtifactRefInvariantError,
    ClosedModel,
    OpaqueTokenId,
    Sha256Hex,
)

# Pydantic resolves these field models at runtime.
from maivn_contracts.artifacts.refs import PrivateArtifactRef  # noqa: TC001
from maivn_contracts.artifacts.vault_types import (  # noqa: TC001
    ArtifactSurfaceIdentity,
    ArtifactTenantScope,
    AsciiSafeExportFilename,
    VaultDeletionScope,
)


class PrivateArtifactResolveRequest(ClosedModel):
    """Select an exact private reference within an authenticated session."""

    artifact_ref: PrivateArtifactRef
    session_id: OpaqueTokenId
    operation: Literal['retrieve_session', 'redacted_export', 'delete'] = 'retrieve_session'
    client_proof_digest: Sha256Hex | None = None
    export_filename: AsciiSafeExportFilename | None = None
    deletion_scope: VaultDeletionScope | None = None
    retrieval_part: Literal['private_original', 'editable_source'] = 'private_original'

    @model_validator(mode='after')
    def _validate_action_inputs(self) -> PrivateArtifactResolveRequest:
        if (
            (self.operation == 'retrieve_session') != (self.client_proof_digest is not None)
            or (self.operation == 'redacted_export') != (self.export_filename is not None)
            or (self.operation == 'delete') != (self.deletion_scope is not None)
            or (self.operation != 'retrieve_session' and self.retrieval_part != 'private_original')
        ):
            raise ArtifactRefInvariantError
        return self


class VaultAttachmentResolveRequest(ClosedModel):
    """Internal mTLS request carrying the Data Plane's durable surface proof."""

    attachment: PrivateArtifactResolveRequest
    source_server_intent_id: OpaqueTokenId
    scope: ArtifactTenantScope
    surface: ArtifactSurfaceIdentity


def vault_attachment_resolve_request_json_bytes(request: VaultAttachmentResolveRequest) -> bytes:
    """Canonicalize the exact signed internal resolver request."""
    return dumps(request.model_dump(mode='json'))
