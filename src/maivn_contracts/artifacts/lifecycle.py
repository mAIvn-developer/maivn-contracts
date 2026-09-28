"""Closed frozen payload-only artifact lifecycle event variants."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from maivn_contracts.artifacts.model import (  # noqa: TC001 - Pydantic resolves these at runtime.
    ArtifactCustody,
    ArtifactError,
    OpaqueTokenId,
    PositiveStrictInt,
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class _Reservation(_Payload):
    reservation_id: OpaqueTokenId
    logical_output_id: OpaqueTokenId


class _Artifact(_Payload):
    artifact_id: OpaqueTokenId
    logical_output_id: OpaqueTokenId
    revision: PositiveStrictInt
    custody: ArtifactCustody


class _Delivery(_Artifact):
    delivery_id: OpaqueTokenId
    destination_ref_id: OpaqueTokenId


class _Deletion(_Artifact):
    deletion_id: OpaqueTokenId


class _Intent(_Payload):
    intent_id: OpaqueTokenId
    correlation_id: OpaqueTokenId


class ArtifactReservedPayload(_Reservation):
    """Reservation created."""

    event_type: Literal['artifact.reserved']
    reservation_state: Literal['reserved']
    policy_snapshot_id: OpaqueTokenId


class ArtifactUploadedPayload(_Reservation):
    """Reservation upload accepted."""

    event_type: Literal['artifact.uploaded']
    reservation_state: Literal['uploading']
    upload_receipt_id: OpaqueTokenId


class ArtifactValidationStartedPayload(_Reservation):
    """Reservation validation started."""

    event_type: Literal['artifact.validation_started']
    reservation_state: Literal['validating']
    validation_profile: OpaqueTokenId


class ArtifactValidatedPayload(_Reservation):
    """Reservation bytes validated."""

    event_type: Literal['artifact.validated']
    reservation_state: Literal['validating']
    validation_receipt_id: OpaqueTokenId


class ArtifactAvailablePayload(_Artifact):
    """Immutable artifact became available."""

    event_type: Literal['artifact.available']
    artifact_state: Literal['available', 'available_in_vault']

    @model_validator(mode='after')
    def validate_custody_state(self) -> ArtifactAvailablePayload:
        """Require the public availability state for the declared custody."""
        if (self.custody, self.artifact_state) not in {
            ('ordinary', 'available'),
            ('vault_private', 'available_in_vault'),
        }:
            message = 'available artifact custody and state must agree'
            raise ValueError(message)
        return self


class ArtifactRejectedPayload(_Reservation):
    """Reservation rejected."""

    event_type: Literal['artifact.rejected']
    reservation_state: Literal['rejected']
    error: ArtifactError


class ArtifactFailedPayload(_Reservation):
    """Reservation failed."""

    event_type: Literal['artifact.failed']
    reservation_state: Literal['failed']
    error: ArtifactError


class ArtifactSelectedPayload(_Artifact):
    """Artifact selected for delivery."""

    event_type: Literal['artifact.selected']
    selection_id: OpaqueTokenId


class ArtifactDeliveryQueuedPayload(_Delivery):
    """Artifact delivery queued."""

    event_type: Literal['artifact.delivery_queued']
    delivery_state: Literal['queued']


class ArtifactDeliveryStartedPayload(_Delivery):
    """Artifact delivery started."""

    event_type: Literal['artifact.delivery_started']
    delivery_state: Literal['started']


class ArtifactDeliverySucceededPayload(_Delivery):
    """Artifact delivery succeeded."""

    event_type: Literal['artifact.delivery_succeeded']
    delivery_state: Literal['succeeded']


class ArtifactDeliveryFailedPayload(_Delivery):
    """Artifact delivery failed."""

    event_type: Literal['artifact.delivery_failed']
    delivery_state: Literal['failed']
    error: ArtifactError


class ArtifactExpiredPayload(_Artifact):
    """Artifact retrieval expired."""

    event_type: Literal['artifact.expired']
    artifact_state: Literal['expired']


class ArtifactDeletionRequestedPayload(_Deletion):
    """Artifact deletion requested."""

    event_type: Literal['artifact.deletion_requested']
    artifact_state: Literal['deleting']


class ArtifactDeletionStartedPayload(_Deletion):
    """Artifact deletion started."""

    event_type: Literal['artifact.deletion_started']
    artifact_state: Literal['deleting']


class ArtifactDeletionPendingBackupExpiryPayload(_Payload):
    """Vault deletion awaits backup expiry."""

    event_type: Literal['artifact.deletion_pending_backup_expiry']
    deletion_id: OpaqueTokenId
    artifact_id: OpaqueTokenId
    logical_output_id: OpaqueTokenId
    revision: PositiveStrictInt
    custody: Literal['vault_private']
    artifact_state: Literal['deletion_pending_backup_expiry']
    deletion_receipt_id: OpaqueTokenId


class ArtifactDeletedPayload(_Deletion):
    """Artifact deletion completed."""

    event_type: Literal['artifact.deleted']
    artifact_state: Literal['deleted']
    deletion_receipt_id: OpaqueTokenId


class ArtifactDeleteIncompletePayload(_Deletion):
    """Artifact deletion incomplete."""

    event_type: Literal['artifact.delete_incomplete']
    artifact_state: Literal['delete_incomplete']
    deletion_receipt_id: OpaqueTokenId
    error: ArtifactError


class ArtifactVaultAuthorizationPendingPayload(_Intent):
    """Vault authorization is pending."""

    event_type: Literal['artifact.vault_authorization_pending']
    intent_state: Literal['authorization_pending']


class ArtifactVaultAuthorizationDeniedPayload(_Intent):
    """Vault authorization was denied."""

    event_type: Literal['artifact.vault_authorization_denied']
    intent_state: Literal['authorization_denied']
    error: ArtifactError


class ArtifactVaultRenderStartedPayload(_Intent):
    """Vault rendering started."""

    event_type: Literal['artifact.vault_render_started']
    intent_state: Literal['rendering_in_vault']


class ArtifactVaultRenderFailedPayload(_Intent):
    """Vault rendering failed."""

    event_type: Literal['artifact.vault_render_failed']
    intent_state: Literal['render_failed']
    error: ArtifactError


ArtifactLifecycleEventPayload: TypeAlias = Annotated[
    ArtifactReservedPayload
    | ArtifactUploadedPayload
    | ArtifactValidationStartedPayload
    | ArtifactValidatedPayload
    | ArtifactAvailablePayload
    | ArtifactRejectedPayload
    | ArtifactFailedPayload
    | ArtifactSelectedPayload
    | ArtifactDeliveryQueuedPayload
    | ArtifactDeliveryStartedPayload
    | ArtifactDeliverySucceededPayload
    | ArtifactDeliveryFailedPayload
    | ArtifactExpiredPayload
    | ArtifactDeletionRequestedPayload
    | ArtifactDeletionStartedPayload
    | ArtifactDeletionPendingBackupExpiryPayload
    | ArtifactDeletedPayload
    | ArtifactDeleteIncompletePayload
    | ArtifactVaultAuthorizationPendingPayload
    | ArtifactVaultAuthorizationDeniedPayload
    | ArtifactVaultRenderStartedPayload
    | ArtifactVaultRenderFailedPayload,
    Field(discriminator='event_type'),
]
_LIFECYCLE_PAYLOAD_ADAPTER: TypeAdapter[ArtifactLifecycleEventPayload] = TypeAdapter(
    ArtifactLifecycleEventPayload
)


def parse_artifact_lifecycle_event_payload(obj: object) -> ArtifactLifecycleEventPayload:
    """Parse a closed lifecycle payload without reading JSON Schema files."""
    return _LIFECYCLE_PAYLOAD_ADAPTER.validate_python(obj)


ARTIFACT_LIFECYCLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        'artifact.reserved',
        'artifact.uploaded',
        'artifact.validation_started',
        'artifact.validated',
        'artifact.available',
        'artifact.rejected',
        'artifact.failed',
        'artifact.selected',
        'artifact.delivery_queued',
        'artifact.delivery_started',
        'artifact.delivery_succeeded',
        'artifact.delivery_failed',
        'artifact.expired',
        'artifact.deletion_requested',
        'artifact.deletion_started',
        'artifact.deletion_pending_backup_expiry',
        'artifact.deleted',
        'artifact.delete_incomplete',
        'artifact.vault_authorization_pending',
        'artifact.vault_authorization_denied',
        'artifact.vault_render_started',
        'artifact.vault_render_failed',
    }
)
