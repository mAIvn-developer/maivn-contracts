"""Artifact error codes, classes and the closed error projection."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import StrictBool, model_validator

from maivn_contracts.artifacts.primitives import ArtifactRefInvariantError, ClosedModel

__all__ = [
    '_ARTIFACT_ERROR_PROJECTIONS',
    'ArtifactError',
    'ArtifactErrorClass',
    'ArtifactErrorCode',
]

ArtifactErrorCode: TypeAlias = Literal[
    'artifact_type_not_allowed',
    'artifact_too_large',
    'artifact_quota_exceeded',
    'artifact_upload_expired',
    'artifact_hash_mismatch',
    'artifact_validation_failed',
    'artifact_scan_rejected',
    'artifact_storage_unavailable',
    'artifact_publish_conflict',
    'artifact_revision_conflict',
    'artifact_not_available',
    'artifact_expired',
    'artifact_deleted',
    'artifact_selection_invalid',
    'artifact_custody_violation',
    'artifact_delete_incomplete',
    'vault_authorization_required',
    'vault_grant_expired',
    'vault_grant_consumed',
    'vault_unavailable',
]
ArtifactErrorClass: TypeAlias = Literal[
    'policy',
    'validation',
    'availability',
    'conflict',
    'lifecycle',
    'authorization',
]

_ARTIFACT_ERROR_PROJECTIONS: dict[str, tuple[str, bool]] = {
    'artifact_type_not_allowed': ('policy', False),
    'artifact_too_large': ('policy', False),
    'artifact_quota_exceeded': ('policy', True),
    'artifact_upload_expired': ('lifecycle', False),
    'artifact_hash_mismatch': ('validation', False),
    'artifact_validation_failed': ('validation', False),
    'artifact_scan_rejected': ('validation', False),
    'artifact_storage_unavailable': ('availability', True),
    'artifact_publish_conflict': ('conflict', False),
    'artifact_revision_conflict': ('conflict', False),
    'artifact_not_available': ('availability', True),
    'artifact_expired': ('lifecycle', False),
    'artifact_deleted': ('lifecycle', False),
    'artifact_selection_invalid': ('policy', False),
    'artifact_custody_violation': ('policy', False),
    'artifact_delete_incomplete': ('lifecycle', True),
    'vault_authorization_required': ('authorization', False),
    'vault_grant_expired': ('authorization', False),
    'vault_grant_consumed': ('authorization', False),
    'vault_unavailable': ('availability', True),
}


class ArtifactError(ClosedModel):
    """Stable value-free artifact failure with code-derived public projection."""

    code: ArtifactErrorCode
    error_class: ArtifactErrorClass
    retryable: StrictBool

    @model_validator(mode='after')
    def _validate_error_projection(self) -> ArtifactError:
        error_class, retryable = _ARTIFACT_ERROR_PROJECTIONS[self.code]
        if self.error_class != error_class or self.retryable != retryable:
            raise ArtifactRefInvariantError
        return self
