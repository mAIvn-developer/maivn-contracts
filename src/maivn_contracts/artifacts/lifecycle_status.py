"""Reservation, work-intent and export lifecycle status projections."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictInt, model_validator

from maivn_contracts.artifacts.primitives import (
    MAX_VERIFIED_EXPORT_BYTES,
    MIME_TYPES_BY_KIND,
    VAULT_EFFECT_STATUS_BINDING_ERROR,
    VERIFIED_EXPORT_IDENTITY_BY_MIME,
    ArtifactKind,
    ArtifactRefInvariantError,
    ClosedModel,
    MimeType,
    OpaqueTokenId,
    PositiveStrictInt,
    PrivateArtifactState,
    Rfc3339Timestamp,
    Sha256Hex,
    value_free_model_input,
)
from maivn_contracts.artifacts.refs import (
    OrdinaryArtifactRef,  # noqa: TC001 - Pydantic resolves this at runtime.
    PrivateArtifactRef,  # noqa: TC001 - Pydantic resolves this at runtime.
    ProducerLineage,  # noqa: TC001 - Pydantic resolves this at runtime.
    RetrievalAction,  # noqa: TC001 - Pydantic resolves this at runtime.
)
from maivn_contracts.artifacts.vault_types import (
    ArtifactSurfaceIdentity,  # noqa: TC001 - Pydantic resolves this at runtime.
    ArtifactTenantScope,  # noqa: TC001 - Pydantic resolves this at runtime.
    AsciiSafeExportFilename,  # noqa: TC001 - Pydantic resolves this at runtime.
    OpaqueVaultHandle,  # noqa: TC001 - Pydantic resolves this at runtime.
)
from maivn_contracts.artifacts.vault_work import (  # noqa: TC001 - Pydantic resolves this at runtime.
    VaultEffectAccepted,
    VaultWorkRequest,
)

__all__ = [
    'ArtifactReservation',
    'ArtifactReservationState',
    'OrdinaryExportDeletionReceipt',
    'OrdinaryExportDeletionRequest',
    'OrdinaryExportDeletionStatusRequest',
    'PrivateArtifactLifecycleReceipt',
    'PrivateWorkIntentState',
    'PrivateWorkIntentStatus',
    'RedactedExportReceipt',
    'VerifiedExportManifest',
    'VerifiedExportPublicationOutcome',
    'VerifiedExportPublicationRequest',
    '_OrdinaryExportDeletionReceiptEnvelope',
    '_OrdinaryExportDeletionRequestEnvelope',
    '_OrdinaryExportDeletionStatusRequestEnvelope',
    '_VerifiedExportManifestEnvelope',
    '_VerifiedExportPublicationOutcomeEnvelope',
    '_VerifiedExportPublicationRequestEnvelope',
    'validate_vault_effect_status_binding',
]

ArtifactReservationState: TypeAlias = Literal[
    'reserved',
    'uploading',
    'validating',
    'finalized',
    'rejected',
    'expired',
    'failed',
]
PrivateWorkIntentState: TypeAlias = Literal[
    'planned',
    'authorization_pending',
    'executing_in_vault',
    'committed',
    'authorization_denied',
    'grant_expired',
    'failed',
]


class ArtifactReservation(ClosedModel):
    """Value-free ordinary-custody reservation before immutable finalization."""

    reservation_id: OpaqueTokenId
    organization_id: OpaqueTokenId
    project_id: OpaqueTokenId
    root_invocation_id: OpaqueTokenId
    producing_session_id: OpaqueTokenId
    tool_call_id: OpaqueTokenId
    dispatch_id: OpaqueTokenId
    attempt_id: OpaqueTokenId
    producer: ProducerLineage
    logical_output_id: OpaqueTokenId
    allowed_kinds: tuple[ArtifactKind, ...] = Field(min_length=1, max_length=5)
    allowed_mime_types: tuple[MimeType, ...] = Field(min_length=1, max_length=8)
    max_artifact_count: PositiveStrictInt
    max_total_bytes: PositiveStrictInt
    retention_policy_snapshot_id: OpaqueTokenId
    idempotency_key: OpaqueTokenId
    expires_at: Rfc3339Timestamp
    state: ArtifactReservationState
    outcome: OrdinaryArtifactRef | None = None

    @model_validator(mode='after')
    def _validate_reservation_invariants(self) -> ArtifactReservation:
        if len(self.allowed_kinds) != len(set(self.allowed_kinds)):
            raise ArtifactRefInvariantError
        if len(self.allowed_mime_types) != len(set(self.allowed_mime_types)):
            raise ArtifactRefInvariantError
        if any(
            not any(mime_type in MIME_TYPES_BY_KIND[kind] for kind in self.allowed_kinds)
            for mime_type in self.allowed_mime_types
        ):
            raise ArtifactRefInvariantError
        if self.state == 'finalized':
            if self.outcome is None:
                raise ArtifactRefInvariantError
            if self.outcome.state != 'available':
                raise ArtifactRefInvariantError
        elif self.outcome is not None:
            raise ArtifactRefInvariantError
        return self


class PrivateArtifactLifecycleReceipt(ClosedModel):
    """Value-free evidence of one committed private artifact lifecycle operation."""

    receipt_id: OpaqueTokenId
    artifact_id: OpaqueVaultHandle
    operation: Literal['create', 'rework', 'delete']
    state: PrivateArtifactState
    correlation_id: OpaqueTokenId
    occurred_at: Rfc3339Timestamp


class RedactedExportReceipt(ClosedModel):
    """Value-free evidence that a separately validated ordinary export was committed."""

    receipt_id: OpaqueTokenId
    ordinary_artifact: OrdinaryArtifactRef
    correlation_id: OpaqueTokenId
    occurred_at: Rfc3339Timestamp

    @model_validator(mode='after')
    def _validate_export_receipt_identities(self) -> RedactedExportReceipt:
        identities = {
            self.receipt_id,
            self.correlation_id,
            self.ordinary_artifact.artifact_id,
            self.ordinary_artifact.logical_output_id,
            self.ordinary_artifact.validation_receipt.receipt_id,
        }
        if len(identities) != len(
            (
                self.receipt_id,
                self.correlation_id,
                self.ordinary_artifact.artifact_id,
                self.ordinary_artifact.logical_output_id,
                self.ordinary_artifact.validation_receipt.receipt_id,
            )
        ):
            raise ArtifactRefInvariantError
        return self


class _VerifiedExportManifestEnvelope(ClosedModel):
    schema_version: Literal['verified-export-v1']
    scope: ArtifactTenantScope
    surface: ArtifactSurfaceIdentity
    correlation_id: OpaqueTokenId
    artifact_kind: Literal['document', 'spreadsheet', 'presentation', 'image']
    mime_type: MimeType
    public_filename: AsciiSafeExportFilename
    content_length: Annotated[StrictInt, Field(ge=1, le=MAX_VERIFIED_EXPORT_BYTES)]
    content_sha256: Sha256Hex
    proof_receipt_id: OpaqueTokenId

    @model_validator(mode='after')
    def _validate_verified_export_manifest(self) -> _VerifiedExportManifestEnvelope:
        identity = VERIFIED_EXPORT_IDENTITY_BY_MIME.get(self.mime_type)
        if (
            identity is None
            or identity[0] != self.artifact_kind
            or not self.public_filename.endswith(identity[1])
            or self.correlation_id == self.proof_receipt_id
        ):
            raise ArtifactRefInvariantError
        return self


class VerifiedExportManifest(_VerifiedExportManifestEnvelope):
    """Closed proof output for one bounded ordinary export candidate."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        return value_free_model_input(value, _VerifiedExportManifestEnvelope)

    def __repr__(self) -> str:
        """Keep verified export metadata out of diagnostic representations."""
        return 'VerifiedExportManifest(<redacted>)'

    __str__ = __repr__


class _VerifiedExportPublicationRequestEnvelope(ClosedModel):
    schema_version: Literal['verified-export-publication-v1']
    operation_id: OpaqueTokenId
    manifest: VerifiedExportManifest

    @model_validator(mode='after')
    def _validate_publication_identities(self) -> _VerifiedExportPublicationRequestEnvelope:
        if self.operation_id in {
            self.manifest.correlation_id,
            self.manifest.proof_receipt_id,
        }:
            raise ArtifactRefInvariantError
        return self


class VerifiedExportPublicationRequest(_VerifiedExportPublicationRequestEnvelope):
    """Exact control object preceding one proven export byte stream."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        return value_free_model_input(value, _VerifiedExportPublicationRequestEnvelope)

    def __repr__(self) -> str:
        """Keep publication control metadata out of diagnostic representations."""
        return 'VerifiedExportPublicationRequest(<redacted>)'

    __str__ = __repr__


class _VerifiedExportPublicationOutcomeEnvelope(ClosedModel):
    receipt: RedactedExportReceipt
    ordinary_deletion_ref: OpaqueTokenId

    @model_validator(mode='after')
    def _validate_internal_deletion_ref(self) -> _VerifiedExportPublicationOutcomeEnvelope:
        public_identities = {
            self.receipt.receipt_id,
            self.receipt.correlation_id,
            self.receipt.ordinary_artifact.artifact_id,
            self.receipt.ordinary_artifact.logical_output_id,
            self.receipt.ordinary_artifact.validation_receipt.receipt_id,
        }
        if self.ordinary_deletion_ref in public_identities:
            raise ArtifactRefInvariantError
        return self


class VerifiedExportPublicationOutcome(_VerifiedExportPublicationOutcomeEnvelope):
    """Internal publication receipt plus its maintenance-only deletion reference."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        return value_free_model_input(value, _VerifiedExportPublicationOutcomeEnvelope)

    def __repr__(self) -> str:
        """Keep publication outcome metadata out of diagnostic representations."""
        return 'VerifiedExportPublicationOutcome(<redacted>)'

    __str__ = __repr__


class _OrdinaryExportDeletionRequestEnvelope(ClosedModel):
    schema_version: Literal['ordinary-export-deletion-request-v1']
    ordinary_deletion_ref: OpaqueTokenId
    deletion_manifest_id: OpaqueTokenId

    @model_validator(mode='after')
    def _validate_deletion_request_identities(self) -> _OrdinaryExportDeletionRequestEnvelope:
        if self.ordinary_deletion_ref == self.deletion_manifest_id:
            raise ArtifactRefInvariantError
        return self


class OrdinaryExportDeletionRequest(_OrdinaryExportDeletionRequestEnvelope):
    """Closed maintenance request to start or resume one ordinary deletion."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        return value_free_model_input(value, _OrdinaryExportDeletionRequestEnvelope)

    def __repr__(self) -> str:
        """Keep deletion request metadata out of diagnostic representations."""
        return 'OrdinaryExportDeletionRequest(<redacted>)'

    __str__ = __repr__


class _OrdinaryExportDeletionStatusRequestEnvelope(ClosedModel):
    schema_version: Literal['ordinary-export-deletion-status-request-v1']
    ordinary_deletion_ref: OpaqueTokenId
    deletion_receipt_id: OpaqueTokenId

    @model_validator(mode='after')
    def _validate_deletion_status_identities(
        self,
    ) -> _OrdinaryExportDeletionStatusRequestEnvelope:
        if self.ordinary_deletion_ref == self.deletion_receipt_id:
            raise ArtifactRefInvariantError
        return self


class OrdinaryExportDeletionStatusRequest(_OrdinaryExportDeletionStatusRequestEnvelope):
    """Closed fixed-body status lookup for an exact ref/receipt pair."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        return value_free_model_input(value, _OrdinaryExportDeletionStatusRequestEnvelope)

    def __repr__(self) -> str:
        """Keep deletion status metadata out of diagnostic representations."""
        return 'OrdinaryExportDeletionStatusRequest(<redacted>)'

    __str__ = __repr__


class _OrdinaryExportDeletionReceiptEnvelope(ClosedModel):
    schema_version: Literal['ordinary-export-deletion-receipt-v1']
    receipt_id: OpaqueTokenId
    state: Literal['requested', 'draining', 'deleting', 'delete_incomplete', 'deleted']
    updated_at: Rfc3339Timestamp


class OrdinaryExportDeletionReceipt(_OrdinaryExportDeletionReceiptEnvelope):
    """Value-free ordinary deletion status; only deleted is terminal."""

    @model_validator(mode='before')
    @classmethod
    def _preflight_value_free_input(cls, value: object) -> object:
        return value_free_model_input(value, _OrdinaryExportDeletionReceiptEnvelope)

    def __repr__(self) -> str:
        """Keep deletion receipt metadata out of diagnostic representations."""
        return 'OrdinaryExportDeletionReceipt(<redacted>)'

    __str__ = __repr__


class PrivateWorkIntentStatus(ClosedModel):
    """Value-free status keyed by server intent, with the work intent as correlation."""

    intent_id: OpaqueTokenId
    operation: Literal[
        'create', 'rework', 'ingest_file', 'retrieve_session', 'delete', 'redacted_export'
    ]
    correlation_id: OpaqueTokenId
    idempotency_key: OpaqueTokenId
    expires_at: Rfc3339Timestamp
    state: PrivateWorkIntentState
    artifact: PrivateArtifactRef | None = None
    lifecycle_receipt: PrivateArtifactLifecycleReceipt | None = None
    redacted_export_receipt: RedactedExportReceipt | None = None
    retrieval_action: RetrievalAction | None = None

    def _committed_outcome_matches_operation(self) -> bool:
        if self.operation in {'create', 'rework', 'ingest_file'}:
            return self.artifact is not None and self.artifact.state == 'available_in_vault'
        if self.operation == 'delete':
            return (
                self.lifecycle_receipt is not None and self.lifecycle_receipt.operation == 'delete'
            )
        if self.operation == 'redacted_export':
            return self.redacted_export_receipt is not None
        return (
            self.retrieval_action is not None
            and self.retrieval_action.relation == 'artifact.vault_download_authorization'
        )

    @model_validator(mode='after')
    def _validate_intent_outcome(self) -> PrivateWorkIntentStatus:
        if self.intent_id == self.correlation_id:
            raise ArtifactRefInvariantError
        outcomes = (
            self.artifact,
            self.lifecycle_receipt,
            self.redacted_export_receipt,
            self.retrieval_action,
        )
        if self.state != 'committed':
            if any(outcome is not None for outcome in outcomes):
                raise ArtifactRefInvariantError
            return self
        if sum(outcome is not None for outcome in outcomes) != 1:
            raise ArtifactRefInvariantError
        if not self._committed_outcome_matches_operation():
            raise ArtifactRefInvariantError
        return self


def validate_vault_effect_status_binding(
    work: VaultWorkRequest,
    accepted: VaultEffectAccepted,
    status: PrivateWorkIntentStatus,
) -> None:
    """Validate the exact client, server-poll, and operation identity binding."""
    identities = (work.intent_id, accepted.server_intent_id, accepted.operation_id)
    if (
        len(set(identities)) != len(identities)
        or accepted.server_intent_id != status.intent_id
        or work.intent_id != status.correlation_id
        or accepted.operation != work.operation
        or status.operation != accepted.operation
    ):
        raise ArtifactRefInvariantError(VAULT_EFFECT_STATUS_BINDING_ERROR)
