"""Hand-authored Pydantic models for Swarm contracts."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictStr

if TYPE_CHECKING:
    from maivn_contracts.agents.model import ModelChoice, PositiveStrictInt
    from maivn_contracts.tools.model import ToolSpecRef
    from maivn_contracts.toolsets.model import ToolSetRef


class SwarmAgentRef(BaseModel):
    """Reference to a deployed agent version used by a Swarm."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(..., min_length=1, description='Referenced Agent id.')
    version: PositiveStrictInt | Literal['latest'] = Field(
        ...,
        description='Immutable Agent version number or latest for publish/run resolution.',
    )


class Swarm(BaseModel):
    """Org-scoped Swarm assembly contract.

    Swarm global tools and toolsets are available to EVERY nested agent. The
    effective toolbelt is the union of swarm-global and agent-local refs, with
    agent-local refs winning on name collision. This contract carries refs only;
    resolution happens at publish/run time.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    swarm_id: StrictStr = Field(..., min_length=1, description='Stable Swarm id.')
    org_id: StrictStr = Field(..., min_length=1, description='Owning organization id.')
    name: StrictStr = Field(..., min_length=1, description='Human-readable Swarm name.')
    description: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional human-readable Swarm description.',
    )
    model: ModelChoice = Field(..., description='Default model choice for the Swarm.')
    agents: list[SwarmAgentRef] = Field(..., description='Nested Agent refs.')
    global_tools: list[ToolSpecRef] = Field(
        ...,
        description='Tool refs available to every nested Agent.',
    )
    global_tool_sets: list[ToolSetRef] = Field(
        ...,
        description='ToolSet refs available to every nested Agent.',
    )
    shared_skill_ids: list[StrictStr] = Field(..., description='Shared Skill ids.')
    shared_skill_set_ids: list[StrictStr] = Field(..., description='Shared SkillSet ids.')
    created_at: StrictStr = Field(..., description='RFC3339 creation timestamp.')
    updated_at: StrictStr = Field(..., description='RFC3339 update timestamp.')


def _swarm_types_namespace() -> dict[str, object]:
    agents_model = import_module('maivn_contracts.agents.model')
    tools_model = import_module('maivn_contracts.tools.model')
    toolsets_model = import_module('maivn_contracts.toolsets.model')
    return {
        'ModelChoice': cast('object', agents_model.ModelChoice),
        'PositiveStrictInt': cast('object', agents_model.PositiveStrictInt),
        'ToolSpecRef': cast('object', tools_model.ToolSpecRef),
        'ToolSetRef': cast('object', toolsets_model.ToolSetRef),
    }


SwarmAgentRef.model_rebuild(_types_namespace=_swarm_types_namespace())
Swarm.model_rebuild(_types_namespace=_swarm_types_namespace())
