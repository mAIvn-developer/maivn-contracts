"""Artifact patch operations and the versioned patch contracts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StrictStr

from maivn_contracts.artifacts.document_v2 import (  # noqa: TC001 - Pydantic resolves this at runtime.
    DocumentFlowBlockV2,
    DocumentNamedStyleV2,
)
from maivn_contracts.artifacts.image_v2 import (  # noqa: TC001 - Pydantic resolves this at runtime.
    ImageLayerV2,
    ImageOperationV2,
)
from maivn_contracts.artifacts.plan_contracts import (
    DocumentArtifactPlanV2,
    ImageArtifactPlanV2,
    WorkbookArtifactPlanV2,
)
from maivn_contracts.artifacts.plan_inputs import (
    STRUCTURAL_ID_PATTERN,
    RedactedArtifactPayload,
    RetentionRequest,
)
from maivn_contracts.artifacts.primitives import (
    ArtifactKind,
    ClosedModel,
    JcsPositiveStrictInt,
    OpaqueTokenId,
    PositiveStrictInt,
)
from maivn_contracts.artifacts.workbook_v2 import (
    WorkbookCellV2,  # noqa: TC001 - Pydantic resolves this at runtime.
    WorkbookChartV2,  # noqa: TC001 - Pydantic resolves this at runtime.
    WorkbookRangeV2,  # noqa: TC001 - Pydantic resolves this at runtime.
    WorkbookTableV2,  # noqa: TC001 - Pydantic resolves this at runtime.
)

__all__ = [
    'ArtifactPatch',
    'ArtifactPatchContract',
    'ArtifactPatchOperation',
    'ArtifactPatchV2',
    'ArtifactPlanV2',
    'DocumentArtifactPatchV2',
    'DocumentInsertBlockOperationV2',
    'DocumentPatchOperationV2',
    'DocumentRemoveBlockOperationV2',
    'DocumentReplaceBlockOperationV2',
    'DocumentUpdateStyleOperationV2',
    'ImageArtifactPatchV2',
    'ImagePatchOperationV2',
    'ImageRemoveLayerOperationV2',
    'ImageReplaceOperationsOperationV2',
    'ImageUpsertLayerOperationV2',
    'InsertAfterOperation',
    'RemoveElementOperation',
    'ReplaceTextOperation',
    'WorkbookArtifactPatchV2',
    'WorkbookPatchOperationV2',
    'WorkbookRemoveCellsOperationV2',
    'WorkbookRemoveChartOperationV2',
    'WorkbookRemoveRangeOperationV2',
    'WorkbookRemoveTableOperationV2',
    'WorkbookUpdateChartOperationV2',
    'WorkbookUpdateRangeOperationV2',
    'WorkbookUpdateTableOperationV2',
    'WorkbookUpsertCellsOperationV2',
    '_ArtifactPatchV2Base',
]


class ReplaceTextOperation(ClosedModel):
    """Replace a structurally-addressed text element with redacted fragments."""

    op: Literal['replace_text']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    payload: RedactedArtifactPayload


class InsertAfterOperation(ClosedModel):
    """Insert redacted fragments after a structural anchor."""

    op: Literal['insert_after']
    anchor_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    payload: RedactedArtifactPayload


class RemoveElementOperation(ClosedModel):
    """Remove one structurally-addressed element."""

    op: Literal['remove_element']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


ArtifactPatchOperation: TypeAlias = Annotated[
    ReplaceTextOperation | InsertAfterOperation | RemoveElementOperation,
    Field(discriminator='op'),
]


class ArtifactPatch(ClosedModel):
    """Exact-revision patch composed only of typed structural operations."""

    schema_version: Literal['v1']
    target_artifact_id: OpaqueTokenId
    base_revision: PositiveStrictInt
    expected_output_kind: ArtifactKind
    renderer_profile: OpaqueTokenId
    disposition: Literal['intermediate', 'candidate', 'final'] | None = None
    retention_request: RetentionRequest | None = None
    rationale: RedactedArtifactPayload
    operations: tuple[ArtifactPatchOperation, ...] = Field(min_length=1, max_length=500)


class DocumentInsertBlockOperationV2(ClosedModel):
    """Insert one closed document block after a stable source anchor."""

    op: Literal['insert_block']
    anchor_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    block: DocumentFlowBlockV2


class DocumentReplaceBlockOperationV2(ClosedModel):
    """Replace one stable document block with one closed block."""

    op: Literal['replace_block']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    block: DocumentFlowBlockV2


class DocumentRemoveBlockOperationV2(ClosedModel):
    """Remove one stable document block."""

    op: Literal['remove_block']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class DocumentUpdateStyleOperationV2(ClosedModel):
    """Replace one stable named document style."""

    op: Literal['update_style']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    style: DocumentNamedStyleV2


DocumentPatchOperationV2: TypeAlias = Annotated[
    DocumentInsertBlockOperationV2
    | DocumentReplaceBlockOperationV2
    | DocumentRemoveBlockOperationV2
    | DocumentUpdateStyleOperationV2,
    Field(discriminator='op'),
]


class WorkbookUpsertCellsOperationV2(ClosedModel):
    """Insert or replace typed cells within one stable sheet."""

    op: Literal['upsert_cells']
    sheet_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    cells: tuple[WorkbookCellV2, ...] = Field(min_length=1, max_length=10_000)


class WorkbookRemoveCellsOperationV2(ClosedModel):
    """Remove a bounded set of stable cells."""

    op: Literal['remove_cells']
    cell_ids: tuple[Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)], ...] = Field(
        min_length=1,
        max_length=10_000,
    )


class WorkbookUpdateRangeOperationV2(ClosedModel):
    """Replace one stable rectangular range declaration."""

    op: Literal['update_range']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    range: WorkbookRangeV2


class WorkbookRemoveRangeOperationV2(ClosedModel):
    """Remove one stable workbook range."""

    op: Literal['remove_range']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookUpdateTableOperationV2(ClosedModel):
    """Replace one stable table declaration."""

    op: Literal['update_table']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    table: WorkbookTableV2


class WorkbookRemoveTableOperationV2(ClosedModel):
    """Remove one stable workbook table."""

    op: Literal['remove_table']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class WorkbookUpdateChartOperationV2(ClosedModel):
    """Replace one stable chart declaration."""

    op: Literal['update_chart']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]
    chart: WorkbookChartV2


class WorkbookRemoveChartOperationV2(ClosedModel):
    """Remove one stable workbook chart."""

    op: Literal['remove_chart']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


WorkbookPatchOperationV2: TypeAlias = Annotated[
    WorkbookUpsertCellsOperationV2
    | WorkbookRemoveCellsOperationV2
    | WorkbookUpdateRangeOperationV2
    | WorkbookRemoveRangeOperationV2
    | WorkbookUpdateTableOperationV2
    | WorkbookRemoveTableOperationV2
    | WorkbookUpdateChartOperationV2
    | WorkbookRemoveChartOperationV2,
    Field(discriminator='op'),
]


class ImageUpsertLayerOperationV2(ClosedModel):
    """Insert or replace one stable image layer."""

    op: Literal['upsert_layer']
    layer: ImageLayerV2


class ImageRemoveLayerOperationV2(ClosedModel):
    """Remove one stable image layer."""

    op: Literal['remove_layer']
    target_id: Annotated[StrictStr, Field(pattern=STRUCTURAL_ID_PATTERN)]


class ImageReplaceOperationsOperationV2(ClosedModel):
    """Replace the complete closed image operation sequence."""

    op: Literal['replace_operations']
    operations: tuple[ImageOperationV2, ...] = Field(min_length=1, max_length=1000)


ImagePatchOperationV2: TypeAlias = Annotated[
    ImageUpsertLayerOperationV2 | ImageRemoveLayerOperationV2 | ImageReplaceOperationsOperationV2,
    Field(discriminator='op'),
]


class _ArtifactPatchV2Base(ClosedModel):
    schema_version: Literal['v2']
    target_artifact_id: OpaqueTokenId
    base_revision: JcsPositiveStrictInt
    source_manifest_digest: Annotated[StrictStr, Field(pattern=r'^[0-9a-f]{64}$')]
    renderer_profile: OpaqueTokenId
    disposition: Literal['intermediate', 'candidate', 'final'] | None = None
    retention_request: RetentionRequest | None = None
    rationale: RedactedArtifactPayload


class DocumentArtifactPatchV2(_ArtifactPatchV2Base):
    """Exact-source structural patch for a normalized v2 document."""

    expected_output_kind: Literal['document']
    operations: tuple[DocumentPatchOperationV2, ...] = Field(min_length=1, max_length=500)


class WorkbookArtifactPatchV2(_ArtifactPatchV2Base):
    """Exact-source structural patch for a normalized v2 workbook."""

    expected_output_kind: Literal['spreadsheet']
    operations: tuple[WorkbookPatchOperationV2, ...] = Field(min_length=1, max_length=500)


class ImageArtifactPatchV2(_ArtifactPatchV2Base):
    """Exact-source structural patch for a normalized v2 image."""

    expected_output_kind: Literal['image']
    operations: tuple[ImagePatchOperationV2, ...] = Field(min_length=1, max_length=500)


ArtifactPatchContract: TypeAlias = (
    ArtifactPatch | DocumentArtifactPatchV2 | WorkbookArtifactPatchV2 | ImageArtifactPatchV2
)

ArtifactPlanV2: TypeAlias = Annotated[
    DocumentArtifactPlanV2 | WorkbookArtifactPlanV2 | ImageArtifactPlanV2,
    Field(discriminator='kind'),
]
ArtifactPatchV2: TypeAlias = (
    DocumentArtifactPatchV2 | WorkbookArtifactPatchV2 | ImageArtifactPatchV2
)
