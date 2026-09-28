"""Inline members retain the dependency graph needed to execute their tools."""

from __future__ import annotations

import jsonschema
import pytest
from pydantic import ValidationError

from maivn_contracts.agents import InvokeAgentSpec, load_agent_version_schema


def test_nested_member_dependencies_round_trip() -> None:
    """Delegates remain scoped to the member rather than expanding its swarm roster."""
    payload = {
        'name': 'coordinator',
        'agents': [{'name': 'market'}],
        'agent_tool_dependencies': [
            {'tool_id': 'brief', 'agent_name': 'market', 'arg_name': 'market'},
        ],
    }
    member = InvokeAgentSpec.model_validate(payload)
    restored = InvokeAgentSpec.model_validate(member.model_dump())
    assert restored.agents is not None
    assert restored.agent_tool_dependencies is not None
    assert restored.agents[0].name == 'market'
    assert restored.agent_tool_dependencies[0].arg_name == 'market'
    schema = load_agent_version_schema()
    jsonschema.validate(
        restored.model_dump(mode='json', exclude_none=True),
        {'$ref': '#/$defs/invokeAgentSpec', '$defs': schema['$defs']},
    )


@pytest.mark.parametrize('agents', [[], [{'name': 'other'}], [{'name': 'market'}] * 2])
def test_nested_member_rejects_unresolved_or_duplicate_agents(agents: list[dict[str, str]]) -> None:
    """A malformed member graph fails before provider execution."""
    with pytest.raises(ValidationError):
        InvokeAgentSpec.model_validate(
            {
                'name': 'coordinator',
                'agents': agents,
                'agent_tool_dependencies': [
                    {'tool_id': 'brief', 'agent_name': 'market', 'arg_name': 'market'},
                ],
            },
        )
