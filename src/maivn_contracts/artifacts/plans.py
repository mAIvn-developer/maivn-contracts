"""Combined legacy and rich artifact-plan aliases without circular imports."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from pydantic import Field

from maivn_contracts.artifacts.document_v3 import DocumentArtifactPlanV3
from maivn_contracts.artifacts.image_v3 import ImageArtifactPlanV3
from maivn_contracts.artifacts.model import ArtifactPlan as LegacyArtifactPlan
from maivn_contracts.artifacts.presentation_v3 import PresentationArtifactPlanV3
from maivn_contracts.artifacts.workbook_v3 import WorkbookArtifactPlanV3

ArtifactPlanV3: TypeAlias = Annotated[
    DocumentArtifactPlanV3
    | WorkbookArtifactPlanV3
    | PresentationArtifactPlanV3
    | ImageArtifactPlanV3,
    Field(discriminator='kind'),
]
ArtifactPlan: TypeAlias = LegacyArtifactPlan | ArtifactPlanV3

__all__ = ['ArtifactPlan', 'ArtifactPlanV3']
