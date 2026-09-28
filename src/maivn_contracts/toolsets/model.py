"""Hand-authored Pydantic models for ToolSet contracts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from maivn_contracts.tools.model import ToolSpecRef


class ToolSetToolRef(ToolSpecRef):
    """ToolSpec reference inside a ToolSet member list."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['tool'] = Field(..., description='ToolSet member discriminator.')


class ToolSetRef(BaseModel):
    """Reference to a versioned ToolSet."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    kind: Literal['toolset'] = Field(..., description='ToolSet member discriminator.')
    toolset_id: StrictStr = Field(..., min_length=1, description='Referenced ToolSet id.')
    namespace: StrictStr = Field(
        ...,
        min_length=1,
        pattern=r'^[A-Za-z][A-Za-z0-9_.-]*$',
        description='Referenced ToolSet namespace.',
    )
    version: StrictStr = Field(..., min_length=1, description='Referenced ToolSet version.')


ToolSetMember: TypeAlias = Annotated[
    ToolSetToolRef | ToolSetRef,
    Field(discriminator='kind'),
]


class ToolSet(BaseModel):
    """Org-scoped ordered collection of Tool and nested ToolSet references."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    toolset_id: StrictStr = Field(..., min_length=1, description='Stable ToolSet id.')
    org_id: StrictStr = Field(..., min_length=1, description='Owning organization id.')
    name: StrictStr = Field(..., min_length=1, description='Human-readable ToolSet name.')
    description: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional human-readable ToolSet description.',
    )
    members: list[ToolSetMember] = Field(
        ...,
        description='Ordered Tool and nested ToolSet references.',
    )
    created_at: StrictStr = Field(..., description='RFC3339 creation timestamp.')
    updated_at: StrictStr = Field(..., description='RFC3339 update timestamp.')
