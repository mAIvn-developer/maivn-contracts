"""Versioned artifact plan envelopes for v1 and v2 renderers."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictStr, model_validator

from maivn_contracts.artifacts.document_v2 import (
    DocumentPlanBodyV2,  # noqa: TC001 - Pydantic resolves this at runtime.
)
from maivn_contracts.artifacts.image_v2 import ImageEncodeOperationV2, ImagePlanBodyV2
from maivn_contracts.artifacts.plan_inputs import (
    STRUCTURAL_ID_PATTERN,
    ArtifactPlanArtifactRefV2,
    ArtifactPlanInputRef,
    ArtifactPlanInputRefV2,
    ArtifactPlanResourceRefV2,
    ArtifactPlanTemplateRefV2,
    RedactedArtifactPayload,
    ResourceBounds,
    RetentionRequest,
    input_ref_authority,
)
from maivn_contracts.artifacts.primitives import (
    MAX_IMAGE_PIXELS,
    MAX_TOTAL_DECODED_PIXELS,
    MAX_WORKBOOK_CELLS,
    MAX_WORKBOOK_SHEETS,
    MIME_TYPES_BY_KIND,
    ArtifactCustody,
    ArtifactRefInvariantError,
    ClosedModel,
    MimeType,
    OpaqueTokenId,
    ValidationProfile,
    ValidationVersion,
)
from maivn_contracts.artifacts.workbook_v2 import (
    WorkbookPlanBodyV2,  # noqa: TC001 - Pydantic resolves this at runtime.
)

__all__ = [
    'ArtifactPlan',
    'ArtifactPlanV1',
    'AudioArtifactPlan',
    'DocumentArtifactPlan',
    'DocumentArtifactPlanV2',
    'ImageArtifactPlan',
    'ImageArtifactPlanV2',
    'WorkbookArtifactPlan',
    'WorkbookArtifactPlanV2',
    '_PlanBase',
]


class _PlanBase(ClosedModel):
    schema_version: Literal['v1']
    logical_output_name: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    custody_request: ArtifactCustody
    content: RedactedArtifactPayload
    input_refs: tuple[ArtifactPlanInputRef, ...] = Field(max_length=32)
    renderer_profile: OpaqueTokenId
    renderer_min_version: ValidationVersion
    output_mime_type: MimeType
    validation_profile: ValidationProfile
    disposition: Literal['intermediate', 'candidate', 'final']
    retention_request: RetentionRequest
    resource_bounds: ResourceBounds


class DocumentArtifactPlan(_PlanBase):
    """Closed minimal fragment plan for a document artifact."""

    kind: Literal['document']

    @model_validator(mode='after')
    def _validate_document_mime(self) -> DocumentArtifactPlan:
        if self.output_mime_type not in MIME_TYPES_BY_KIND['document']:
            raise ArtifactRefInvariantError
        return self


class WorkbookArtifactPlan(_PlanBase):
    """Closed minimal fragment plan for a workbook artifact."""

    kind: Literal['spreadsheet']

    @model_validator(mode='after')
    def _validate_workbook_mime(self) -> WorkbookArtifactPlan:
        if self.output_mime_type not in MIME_TYPES_BY_KIND['spreadsheet']:
            raise ArtifactRefInvariantError
        return self


class ImageArtifactPlan(_PlanBase):
    """Closed minimal fragment plan for an image artifact."""

    kind: Literal['image']

    @model_validator(mode='after')
    def _validate_image_mime(self) -> ImageArtifactPlan:
        if self.output_mime_type not in MIME_TYPES_BY_KIND['image']:
            raise ArtifactRefInvariantError
        return self


class AudioArtifactPlan(_PlanBase):
    """Closed minimal fragment plan for an audio artifact."""

    kind: Literal['audio']

    @model_validator(mode='after')
    def _validate_audio_mime(self) -> AudioArtifactPlan:
        if self.output_mime_type not in MIME_TYPES_BY_KIND['audio']:
            raise ArtifactRefInvariantError
        return self


ArtifactPlanV1: TypeAlias = Annotated[
    DocumentArtifactPlan | WorkbookArtifactPlan | ImageArtifactPlan | AudioArtifactPlan,
    Field(discriminator='kind'),
]


class DocumentArtifactPlanV2(ClosedModel):
    """Closed stable document structure for the attested v2 renderer."""

    schema_version: Literal['v2']
    kind: Literal['document']
    logical_output_name: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    custody_request: ArtifactCustody
    body: DocumentPlanBodyV2
    input_refs: tuple[ArtifactPlanInputRefV2, ...] = Field(max_length=32)
    renderer_profile: OpaqueTokenId
    renderer_min_version: ValidationVersion
    output_mime_type: MimeType
    validation_profile: ValidationProfile
    disposition: Literal['intermediate', 'candidate', 'final']
    retention_request: RetentionRequest
    resource_bounds: ResourceBounds

    @model_validator(mode='after')
    def _validate_document_plan(self) -> DocumentArtifactPlanV2:
        if self.output_mime_type not in MIME_TYPES_BY_KIND['document']:
            raise ArtifactRefInvariantError
        local_ids = tuple(item.local_id for item in self.input_refs)
        if len(local_ids) != len(set(local_ids)):
            raise ArtifactRefInvariantError
        authorities = tuple(input_ref_authority(item) for item in self.input_refs)
        if len(authorities) != len(set(authorities)):
            raise ArtifactRefInvariantError
        if set(local_ids).intersection(self.body.structural_ids()):
            raise ArtifactRefInvariantError
        used_local_ids = set(self.body.used_image_input_local_ids())
        if self.body.template_local_id is not None:
            used_local_ids.add(self.body.template_local_id)
        if set(local_ids) != set(used_local_ids):
            raise ArtifactRefInvariantError
        if self.body.template_local_id is not None and not any(
            isinstance(item, ArtifactPlanTemplateRefV2)
            and item.local_id == self.body.template_local_id
            for item in self.input_refs
        ):
            raise ArtifactRefInvariantError
        image_input_ids = self.body.used_image_input_local_ids()
        if any(
            not any(
                isinstance(item, (ArtifactPlanArtifactRefV2, ArtifactPlanResourceRefV2))
                and item.local_id == image_input_id
                for item in self.input_refs
            )
            for image_input_id in image_input_ids
        ):
            raise ArtifactRefInvariantError
        return self


class ImageArtifactPlanV2(ClosedModel):
    """Closed stable raster composition plan for the attested v2 renderer."""

    schema_version: Literal['v2']
    kind: Literal['image']
    logical_output_name: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    custody_request: ArtifactCustody
    body: ImagePlanBodyV2
    input_refs: tuple[ArtifactPlanInputRefV2, ...] = Field(max_length=32)
    renderer_profile: OpaqueTokenId
    renderer_min_version: ValidationVersion
    output_mime_type: Literal['image/png', 'image/jpeg']
    validation_profile: ValidationProfile
    disposition: Literal['intermediate', 'candidate', 'final']
    retention_request: RetentionRequest
    resource_bounds: ResourceBounds

    @model_validator(mode='after')
    def _validate_image_plan(self) -> ImageArtifactPlanV2:
        local_ids = tuple(item.local_id for item in self.input_refs)
        authorities = tuple(input_ref_authority(item) for item in self.input_refs)
        if len(local_ids) != len(set(local_ids)) or len(authorities) != len(set(authorities)):
            raise ArtifactRefInvariantError
        if set(local_ids).intersection(self.body.structural_ids()):
            raise ArtifactRefInvariantError
        used_local_ids = self.body.used_input_local_ids()
        if set(local_ids) != set(used_local_ids):
            raise ArtifactRefInvariantError
        if any(
            not isinstance(item, (ArtifactPlanArtifactRefV2, ArtifactPlanResourceRefV2))
            for item in self.input_refs
        ):
            raise ArtifactRefInvariantError
        if (
            self.resource_bounds.max_pixels is None
            or self.resource_bounds.max_pixels > MAX_IMAGE_PIXELS
            or self.resource_bounds.max_total_decoded_pixels is None
            or self.resource_bounds.max_total_decoded_pixels > MAX_TOTAL_DECODED_PIXELS
            or self.body.canvas.width_pixels * self.body.canvas.height_pixels
            > self.resource_bounds.max_pixels
        ):
            raise ArtifactRefInvariantError
        encode = self.body.operations[-1]
        if (
            not isinstance(encode, ImageEncodeOperationV2)
            or encode.mime_type != self.output_mime_type
        ):
            raise ArtifactRefInvariantError
        return self


class WorkbookArtifactPlanV2(ClosedModel):
    """Closed stable workbook plan for the attested v2 renderer."""

    schema_version: Literal['v2']
    kind: Literal['spreadsheet']
    logical_output_name: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    custody_request: ArtifactCustody
    body: WorkbookPlanBodyV2
    input_refs: tuple[ArtifactPlanInputRefV2, ...] = Field(max_length=32)
    renderer_profile: OpaqueTokenId
    renderer_min_version: ValidationVersion
    output_mime_type: Literal['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
    validation_profile: ValidationProfile
    disposition: Literal['intermediate', 'candidate', 'final']
    retention_request: RetentionRequest
    resource_bounds: ResourceBounds

    @model_validator(mode='after')
    def _validate_workbook_plan(self) -> WorkbookArtifactPlanV2:
        local_ids = tuple(item.local_id for item in self.input_refs)
        authorities = tuple(input_ref_authority(item) for item in self.input_refs)
        if len(local_ids) != len(set(local_ids)) or len(authorities) != len(set(authorities)):
            raise ArtifactRefInvariantError
        if set(local_ids).intersection(self.body.structural_ids()):
            raise ArtifactRefInvariantError
        used_local_ids: set[str] = (
            {self.body.template_local_id} if self.body.template_local_id is not None else set()
        )
        if set(local_ids) != used_local_ids:
            raise ArtifactRefInvariantError
        if self.input_refs and not isinstance(self.input_refs[0], ArtifactPlanTemplateRefV2):
            raise ArtifactRefInvariantError
        cell_count = sum(len(sheet.cells) for sheet in self.body.sheets)
        if (
            self.resource_bounds.max_sheets is None
            or self.resource_bounds.max_sheets > MAX_WORKBOOK_SHEETS
            or self.resource_bounds.max_sheets < len(self.body.sheets)
            or self.resource_bounds.max_cells is None
            or self.resource_bounds.max_cells > MAX_WORKBOOK_CELLS
            or self.resource_bounds.max_cells < cell_count
        ):
            raise ArtifactRefInvariantError
        return self


ArtifactPlan: TypeAlias = (
    ArtifactPlanV1 | DocumentArtifactPlanV2 | WorkbookArtifactPlanV2 | ImageArtifactPlanV2
)
