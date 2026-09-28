"""Vault replacement plans, full-replacement patches and vault work requests."""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeAlias, TypeVar

from pydantic import Field, model_validator
from typing_extensions import Self

from maivn_contracts.artifacts.document_v3 import DocumentArtifactPlanV3
from maivn_contracts.artifacts.image_v3 import ImageArtifactPlanV3
from maivn_contracts.artifacts.plan_contracts import (
    DocumentArtifactPlanV2,
    ImageArtifactPlanV2,
    WorkbookArtifactPlanV2,
)
from maivn_contracts.artifacts.plan_inputs import ResourceBounds, collect_placeholder_names
from maivn_contracts.artifacts.presentation_v3 import PresentationArtifactPlanV3
from maivn_contracts.artifacts.primitives import (
    ArtifactKind,
    ArtifactRefInvariantError,
    ClosedModel,
    JcsPositiveStrictInt,
    MimeType,
    OpaqueTokenId,
    Rfc3339Timestamp,
    Sha256Hex,
)
from maivn_contracts.artifacts.private_file_intake import (
    VaultFileIntakeManifest,  # noqa: TC001 - Pydantic runtime annotation.
)
from maivn_contracts.artifacts.vault_types import (
    ArtifactSurfaceIdentity,
    ArtifactTenantScope,
    AsciiSafeExportFilename,
    OpaqueVaultHandle,
    VaultArtifactFormat,
    VaultDeletionScope,
    VaultInputHandle,
    VaultValueMapHandle,
)
from maivn_contracts.artifacts.workbook_v3 import WorkbookArtifactPlanV3

__all__ = [
    '_OPTIONAL_RESOURCE_BOUND_FIELDS',
    '_RESOURCE_BOUNDS_BY_KIND',
    '_VAULT_FORMAT_IDENTITY',
    '_VAULT_PROFILE_MAP',
    'VaultArtifactPlan',
    'VaultArtifactPlanV2',
    'VaultArtifactPlanV3',
    'VaultDocumentReplacementPlan',
    'VaultDocxFullReplacementArtifactPatch',
    'VaultEffectAccepted',
    'VaultFullReplacementArtifactPatch',
    'VaultImageReplacementPlan',
    'VaultJpegFullReplacementArtifactPatch',
    'VaultPdfFullReplacementArtifactPatch',
    'VaultPngFullReplacementArtifactPatch',
    'VaultPptxFullReplacementArtifactPatch',
    'VaultWorkRequest',
    'VaultWorkbookReplacementPlan',
    'VaultXlsxFullReplacementArtifactPatch',
    '_VaultFormatT',
    '_VaultFullReplacementArtifactPatchBase',
    '_VaultKindT',
    '_VaultMimeTypeT',
    '_VaultReplacementPlanT',
    '_validate_vault_artifact_plan',
    '_validate_vault_resource_bounds',
]

VaultArtifactPlanV2: TypeAlias = Annotated[
    DocumentArtifactPlanV2 | WorkbookArtifactPlanV2 | ImageArtifactPlanV2,
    Field(discriminator='kind'),
]
VaultArtifactPlanV3: TypeAlias = Annotated[
    DocumentArtifactPlanV3
    | WorkbookArtifactPlanV3
    | PresentationArtifactPlanV3
    | ImageArtifactPlanV3,
    Field(discriminator='kind'),
]
VaultArtifactPlan: TypeAlias = VaultArtifactPlanV2 | VaultArtifactPlanV3

VaultDocumentReplacementPlan: TypeAlias = Annotated[
    DocumentArtifactPlanV2 | DocumentArtifactPlanV3,
    Field(discriminator='schema_version'),
]
VaultWorkbookReplacementPlan: TypeAlias = Annotated[
    WorkbookArtifactPlanV2 | WorkbookArtifactPlanV3,
    Field(discriminator='schema_version'),
]
VaultImageReplacementPlan: TypeAlias = Annotated[
    ImageArtifactPlanV2 | ImageArtifactPlanV3,
    Field(discriminator='schema_version'),
]

_VAULT_FORMAT_IDENTITY: dict[str, tuple[str, str]] = {
    'docx': (
        'document',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ),
    'pdf': ('document', 'application/pdf'),
    'xlsx': (
        'spreadsheet',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ),
    'pptx': (
        'presentation',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ),
    'png': ('image', 'image/png'),
    'jpeg': ('image', 'image/jpeg'),
}
_VAULT_PROFILE_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ('v2', _VAULT_FORMAT_IDENTITY['docx'][1]): (
        'document-v1',
        '1.0.0',
        'document-validator-v1',
    ),
    ('v2', _VAULT_FORMAT_IDENTITY['pdf'][1]): (
        'document-pdf-v1',
        '1.0.0',
        'document-pdf-validator-v1',
    ),
    ('v2', _VAULT_FORMAT_IDENTITY['xlsx'][1]): (
        'workbook-v1',
        '1.0.0',
        'workbook-validator-v1',
    ),
    ('v2', _VAULT_FORMAT_IDENTITY['png'][1]): ('image-v1', '1.0.0', 'image-validator-v1'),
    ('v2', _VAULT_FORMAT_IDENTITY['jpeg'][1]): ('image-v1', '1.0.0', 'image-validator-v1'),
    ('v3', _VAULT_FORMAT_IDENTITY['docx'][1]): (
        'rich_document_v3',
        '3.0.0',
        'rich_document_validator_v3',
    ),
    ('v3', _VAULT_FORMAT_IDENTITY['pdf'][1]): (
        'rich_document_pdf_v3',
        '3.0.0',
        'rich_document_pdf_validator_v3',
    ),
    ('v3', _VAULT_FORMAT_IDENTITY['xlsx'][1]): (
        'rich_workbook_v3',
        '3.0.0',
        'rich_workbook_validator_v3',
    ),
    ('v3', _VAULT_FORMAT_IDENTITY['pptx'][1]): (
        'rich_presentation_v3',
        '3.0.0',
        'rich_presentation_validator_v3',
    ),
    ('v3', _VAULT_FORMAT_IDENTITY['png'][1]): (
        'rich_image_v3',
        '3.0.0',
        'rich_image_validator_v3',
    ),
    ('v3', _VAULT_FORMAT_IDENTITY['jpeg'][1]): (
        'rich_image_v3',
        '3.0.0',
        'rich_image_validator_v3',
    ),
}
_OPTIONAL_RESOURCE_BOUND_FIELDS = (
    'max_pages',
    'max_sheets',
    'max_cells',
    'max_pixels',
    'max_total_decoded_pixels',
    'max_duration_seconds',
)
_RESOURCE_BOUNDS_BY_KIND: dict[str, frozenset[str]] = {
    'document': frozenset({'max_pages'}),
    'spreadsheet': frozenset({'max_sheets', 'max_cells'}),
    'presentation': frozenset({'max_pages'}),
    'image': frozenset({'max_pixels', 'max_total_decoded_pixels'}),
}


def _validate_vault_resource_bounds(bounds: ResourceBounds, kind: str) -> None:
    required = _RESOURCE_BOUNDS_BY_KIND.get(kind)
    if required is None or any(
        (getattr(bounds, field_name) is not None) != (field_name in required)
        for field_name in _OPTIONAL_RESOURCE_BOUND_FIELDS
    ):
        raise ArtifactRefInvariantError


def _validate_vault_artifact_plan(plan: VaultArtifactPlan) -> None:
    profile = _VAULT_PROFILE_MAP.get((plan.schema_version, plan.output_mime_type))
    if plan.custody_request != 'vault_private' or profile != (
        plan.renderer_profile,
        plan.renderer_min_version,
        plan.validation_profile,
    ):
        raise ArtifactRefInvariantError
    _validate_vault_resource_bounds(plan.resource_bounds, plan.kind)


_VaultFormatT = TypeVar('_VaultFormatT', bound=VaultArtifactFormat)
_VaultKindT = TypeVar('_VaultKindT', bound=ArtifactKind)
_VaultMimeTypeT = TypeVar('_VaultMimeTypeT', bound=MimeType)
_VaultReplacementPlanT = TypeVar('_VaultReplacementPlanT', bound=VaultArtifactPlan)


class _VaultFullReplacementArtifactPatchBase(
    ClosedModel,
    Generic[_VaultFormatT, _VaultKindT, _VaultMimeTypeT, _VaultReplacementPlanT],
):
    """Exact source evidence and a same-format complete replacement plan."""

    source_format: _VaultFormatT
    source_generation_handle: OpaqueVaultHandle
    base_revision: JcsPositiveStrictInt
    source_manifest_digest: Sha256Hex
    source_kind: _VaultKindT
    source_mime_type: _VaultMimeTypeT
    source_resource_bounds: ResourceBounds
    replacement_plan: _VaultReplacementPlanT

    @model_validator(mode='after')
    def _validate_exact_source_and_replacement(
        self,
    ) -> Self:
        expected_identity = _VAULT_FORMAT_IDENTITY[self.source_format]
        replacement = self.replacement_plan
        if (self.source_kind, self.source_mime_type) != expected_identity or (
            replacement.kind,
            replacement.output_mime_type,
        ) != expected_identity:
            raise ArtifactRefInvariantError
        _validate_vault_resource_bounds(self.source_resource_bounds, self.source_kind)
        _validate_vault_artifact_plan(replacement)
        return self


class VaultDocxFullReplacementArtifactPatch(
    _VaultFullReplacementArtifactPatchBase[
        Literal['docx'],
        Literal['document'],
        Literal['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
        VaultDocumentReplacementPlan,
    ],
):
    """Exact DOCX source replaced by a complete DOCX plan."""


class VaultPdfFullReplacementArtifactPatch(
    _VaultFullReplacementArtifactPatchBase[
        Literal['pdf'],
        Literal['document'],
        Literal['application/pdf'],
        VaultDocumentReplacementPlan,
    ],
):
    """Exact PDF source replaced by a complete PDF plan."""


class VaultXlsxFullReplacementArtifactPatch(
    _VaultFullReplacementArtifactPatchBase[
        Literal['xlsx'],
        Literal['spreadsheet'],
        Literal['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
        VaultWorkbookReplacementPlan,
    ],
):
    """Exact XLSX source replaced by a complete XLSX plan."""


class VaultPptxFullReplacementArtifactPatch(
    _VaultFullReplacementArtifactPatchBase[
        Literal['pptx'],
        Literal['presentation'],
        Literal['application/vnd.openxmlformats-officedocument.presentationml.presentation'],
        PresentationArtifactPlanV3,
    ],
):
    """Exact PPTX source replaced by a complete PPTX plan."""


class VaultPngFullReplacementArtifactPatch(
    _VaultFullReplacementArtifactPatchBase[
        Literal['png'], Literal['image'], Literal['image/png'], VaultImageReplacementPlan
    ],
):
    """Exact PNG source replaced by a complete PNG plan."""


class VaultJpegFullReplacementArtifactPatch(
    _VaultFullReplacementArtifactPatchBase[
        Literal['jpeg'], Literal['image'], Literal['image/jpeg'], VaultImageReplacementPlan
    ],
):
    """Exact JPEG source replaced by a complete JPEG plan."""


VaultFullReplacementArtifactPatch: TypeAlias = Annotated[
    VaultDocxFullReplacementArtifactPatch
    | VaultPdfFullReplacementArtifactPatch
    | VaultXlsxFullReplacementArtifactPatch
    | VaultPptxFullReplacementArtifactPatch
    | VaultPngFullReplacementArtifactPatch
    | VaultJpegFullReplacementArtifactPatch,
    Field(discriminator='source_format'),
]


class VaultEffectAccepted(ClosedModel):
    """Stable value-free handle returned after an effect is durably queued."""

    server_intent_id: OpaqueTokenId
    operation_id: OpaqueTokenId
    operation: Literal['create', 'rework', 'ingest_file', 'delete', 'redacted_export']
    state: Literal['queued']

    @model_validator(mode='after')
    def _validate_distinct_server_and_operation_ids(self) -> VaultEffectAccepted:
        if self.server_intent_id == self.operation_id:
            raise ArtifactRefInvariantError
        return self


class VaultWorkRequest(ClosedModel):
    """Redacted, non-authorizing instruction submitted to the private vault."""

    schema_version: Literal['vault-work-v1']
    intent_id: OpaqueTokenId
    idempotency_key: OpaqueTokenId
    operation: Literal[
        'create', 'rework', 'ingest_file', 'retrieve_session', 'delete', 'redacted_export'
    ]
    scope: ArtifactTenantScope
    surface: ArtifactSurfaceIdentity
    input_handles: tuple[VaultInputHandle, ...] = Field(max_length=32)
    value_map_handle: VaultValueMapHandle | None = None
    plan: VaultArtifactPlan | None = None
    patch: VaultFullReplacementArtifactPatch | None = None
    file_intake: VaultFileIntakeManifest | None = None
    bounds: ResourceBounds
    retention_policy_id: OpaqueTokenId
    client_proof_digest: Sha256Hex | None = None
    export_filename: AsciiSafeExportFilename | None = None
    deletion_scope: VaultDeletionScope | None = None
    retrieval_part: Literal['editable_source'] | None = None
    expires_at: Rfc3339Timestamp

    def _validate_handle_closure(self) -> None:
        local_ids = [item.local_id for item in self.input_handles]
        record_handles = [item.record_handle for item in self.input_handles]
        generation_handles = [item.generation_handle for item in self.input_handles]
        if (
            len(local_ids) != len(set(local_ids))
            or len(record_handles) != len(set(record_handles))
            or len(generation_handles) != len(set(generation_handles))
            or set(local_ids).intersection(record_handles)
            or set(local_ids).intersection(generation_handles)
            or set(record_handles).intersection(generation_handles)
        ):
            raise ArtifactRefInvariantError
        if self.value_map_handle is not None:
            value_map_handles = {
                self.value_map_handle.record_handle,
                self.value_map_handle.generation_handle,
            }
            if value_map_handles.intersection(
                {*local_ids, *record_handles, *generation_handles},
            ):
                raise ArtifactRefInvariantError
        placeholder_names = collect_placeholder_names(
            {
                'plan': None if self.plan is None else self.plan.model_dump(mode='json'),
                'patch': None if self.patch is None else self.patch.model_dump(mode='json'),
            },
        )
        if placeholder_names.intersection(record_handles) or placeholder_names.intersection(
            generation_handles,
        ):
            raise ArtifactRefInvariantError

    def _validate_create_payload(self) -> None:
        if self.plan is None or self.patch is not None:
            raise ArtifactRefInvariantError
        _validate_vault_artifact_plan(self.plan)
        if self.bounds != self.plan.resource_bounds:
            raise ArtifactRefInvariantError
        plan_local_ids = {item.local_id for item in self.plan.input_refs}
        if {item.local_id for item in self.input_handles} != plan_local_ids:
            raise ArtifactRefInvariantError

    def _validate_file_intake_payload(self) -> None:
        if self.file_intake is None or self.plan is not None or self.patch is not None:
            raise ArtifactRefInvariantError
        base = self.file_intake.expected_base_ref
        if base is None:
            if self.input_handles:
                raise ArtifactRefInvariantError
        elif (
            len(self.input_handles) != 1
            or self.input_handles[0].role != 'source_artifact'
            or self.input_handles[0].generation_handle != base.artifact_id
            or self.input_handles[0].record_handle != base.logical_output_id
        ):
            raise ArtifactRefInvariantError

    def _validate_noncreate_payload(self) -> None:
        if self.operation == 'ingest_file':
            self._validate_file_intake_payload()
            return
        if self.operation == 'rework':
            if self.plan is not None or self.patch is None:
                raise ArtifactRefInvariantError
            sources = tuple(
                handle for handle in self.input_handles if handle.role == 'source_artifact'
            )
            if len(sources) != 1:
                raise ArtifactRefInvariantError
            source = sources[0]
            plan_local_ids = {item.local_id for item in self.patch.replacement_plan.input_refs}
            admitted_plan_local_ids = {
                handle.local_id for handle in self.input_handles if handle.role != 'source_artifact'
            }
            if (
                source.generation_handle != self.patch.source_generation_handle
                or self.bounds != self.patch.replacement_plan.resource_bounds
                or plan_local_ids != admitted_plan_local_ids
            ):
                raise ArtifactRefInvariantError
            return
        if (
            self.plan is not None
            or self.patch is not None
            or len(self.input_handles) != 1
            or self.input_handles[0].role != 'source_artifact'
        ):
            raise ArtifactRefInvariantError

    @model_validator(mode='after')
    def _validate_operation_payload(self) -> VaultWorkRequest:
        self._validate_handle_closure()
        if (self.operation in {'create', 'rework'}) != (self.value_map_handle is not None):
            raise ArtifactRefInvariantError
        if (self.operation == 'delete') != (self.deletion_scope is not None):
            raise ArtifactRefInvariantError
        if (self.operation in {'retrieve_session', 'ingest_file'}) != (
            self.client_proof_digest is not None
        ):
            raise ArtifactRefInvariantError
        if (self.operation == 'ingest_file') != (self.file_intake is not None):
            raise ArtifactRefInvariantError
        if (self.operation == 'redacted_export') != (self.export_filename is not None):
            raise ArtifactRefInvariantError
        if self.retrieval_part is not None and self.operation != 'retrieve_session':
            raise ArtifactRefInvariantError
        if self.operation == 'create':
            self._validate_create_payload()
        else:
            self._validate_noncreate_payload()
        return self
