"""Vault handles, tenancy scopes and export filename projections."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import AfterValidator, Field, StrictStr, model_validator

from maivn_contracts.artifacts.plan_inputs import STRUCTURAL_ID_PATTERN
from maivn_contracts.artifacts.primitives import (
    ArtifactRefInvariantError,
    ClosedModel,
    OpaqueTokenId,
)

__all__ = [
    '_PLATFORM_RESERVED_EXPORT_BASENAMES',
    'ArtifactSurfaceIdentity',
    'ArtifactTenantScope',
    'AsciiSafeExportFilename',
    'DeletionScope',
    'OpaqueVaultHandle',
    'VaultArtifactFormat',
    'VaultDeletionScope',
    'VaultInputHandle',
    'VaultValueMapHandle',
    '_validate_ascii_safe_export_filename',
]

OpaqueVaultHandle: TypeAlias = OpaqueTokenId
DeletionScope: TypeAlias = Literal['private_only', 'include_redacted_exports']
VaultArtifactFormat: TypeAlias = Literal['docx', 'pdf', 'xlsx', 'pptx', 'png', 'jpeg']
_PLATFORM_RESERVED_EXPORT_BASENAMES = frozenset(
    {
        'CON',
        'PRN',
        'AUX',
        'NUL',
        *(f'COM{index}' for index in range(1, 10)),
        *(f'LPT{index}' for index in range(1, 10)),
    },
)


def _validate_ascii_safe_export_filename(value: str) -> str:
    basename = value.partition('.')[0].rstrip(' .').upper()
    if (
        value in {'.', '..'}
        or value.endswith(('.', ' '))
        or basename in _PLATFORM_RESERVED_EXPORT_BASENAMES
    ):
        raise ArtifactRefInvariantError
    return value


AsciiSafeExportFilename: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._ ()-]{0,254}$'),
    AfterValidator(_validate_ascii_safe_export_filename),
]


class ArtifactTenantScope(ClosedModel):
    """Exact tenant boundary stamped onto an untrusted vault request."""

    organization_id: OpaqueTokenId
    project_id: OpaqueTokenId


class ArtifactSurfaceIdentity(ClosedModel):
    """Exact invocation surface that a vault authorization must bind."""

    root_invocation_id: OpaqueTokenId
    session_id: OpaqueTokenId
    checkpoint_id: OpaqueTokenId
    caller_id: OpaqueTokenId


class VaultInputHandle(ClosedModel):
    """Value-free vault binding for one plan-local immutable input."""

    local_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    record_handle: OpaqueVaultHandle
    generation_handle: OpaqueVaultHandle
    role: Literal['template', 'source_artifact', 'source_image', 'source_file']


class VaultValueMapHandle(ClosedModel):
    """Opaque Vault routing identities for one immutable value-map generation."""

    record_handle: OpaqueVaultHandle
    generation_handle: OpaqueVaultHandle

    @model_validator(mode='after')
    def _validate_distinct_handles(self) -> VaultValueMapHandle:
        if self.record_handle == self.generation_handle:
            raise ArtifactRefInvariantError
        return self


class VaultDeletionScope(ClosedModel):
    """Closed retention choice for a private deletion effect."""

    mode: DeletionScope
