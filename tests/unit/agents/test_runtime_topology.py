# pyright: strict
"""Unit tests for immutable compiled Flow runtime topology."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maivn_contracts.agents import AgentVersion


def _agent_version_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        'agent_id': 'flow-runtime-support-triage',
        'version': 3,
        'execution_mode': 'hosted_only',
        'model': {'response': {'tier': 'balanced'}},
        'instructions': {'kind': 'inline', 'content': 'Coordinate the Flow.'},
        'tools_snapshot': [],
        'created_at': '2026-07-21T20:00:00Z',
        'created_by': 'usr-owner',
    }
    body.update(overrides)
    return body


def test_agent_version_carries_immutable_swarm_topology() -> None:
    """Carry the same closed roster topology accepted by direct invoke."""
    version = AgentVersion.model_validate(
        _agent_version_body(
            agents_snapshot=[
                {'name': 'researcher', 'system_prompt': 'Research.'},
                {
                    'name': 'writer',
                    'system_prompt': 'Write.',
                    'use_as_final_output': True,
                },
            ],
            agent_tool_dependencies=[],
            swarm_roster=True,
        ),
    )

    assert version.swarm_roster is True
    assert version.agents_snapshot is not None
    assert version.agents_snapshot[1].use_as_final_output is True


def test_agent_version_carries_root_attached_skills() -> None:
    """Preserve explicitly attached root skills for later trigger launches."""
    version = AgentVersion.model_validate(
        _agent_version_body(attached_skill_ids=['skill-review', 'skill-tone']),
    )

    assert version.attached_skill_ids == ['skill-review', 'skill-tone']


def test_agent_version_accepts_the_ultra_model_tier() -> None:
    """Immutable deployed versions must preserve the runtime's Ultra directive."""
    version = AgentVersion.model_validate(
        _agent_version_body(model={'response': {'tier': 'ultra'}}),
    )

    assert version.model.response.tier == 'ultra'


def test_tool_snapshot_carries_immutable_tool_dependency_edges() -> None:
    """Preserve tool-to-tool argument wiring compiled from the Flow canvas."""
    tools: list[dict[str, object]] = [
        {
            'tool_id': 'fetch_document',
            'name': 'fetch_document',
            'description': 'Fetch one document.',
            'parameters_schema': {'type': 'object', 'properties': {}},
            'execution': {
                'locus': 'hosted',
                'provider': 'documents',
                'tool_ref': 'documents.fetch',
            },
        },
        {
            'tool_id': 'summarize',
            'name': 'summarize',
            'description': 'Summarize fetched content.',
            'parameters_schema': {'type': 'object', 'properties': {}},
            'execution': {
                'locus': 'hosted',
                'provider': 'documents',
                'tool_ref': 'documents.summarize',
            },
            'tool_dependencies': [
                {'tool_name': 'fetch_document', 'arg_name': 'document'},
            ],
        },
    ]
    version = AgentVersion.model_validate(
        _agent_version_body(tools_snapshot=tools),
    )

    assert version.tools_snapshot[1].tool_dependencies is not None
    assert version.tools_snapshot[1].tool_dependencies[0].tool_name == 'fetch_document'


def test_swarm_roster_requires_at_least_one_agent() -> None:
    """Reject a saved runtime that claims swarm semantics with no roster."""
    with pytest.raises(ValidationError, match='swarm roster'):
        AgentVersion.model_validate(
            _agent_version_body(
                agents_snapshot=[],
                agent_tool_dependencies=[],
                swarm_roster=True,
            ),
        )


def test_non_swarm_runtime_rejects_hidden_topology() -> None:
    """Do not preserve dormant delegated behavior behind a false selector."""
    with pytest.raises(ValidationError, match='non-swarm'):
        AgentVersion.model_validate(
            _agent_version_body(
                agents_snapshot=[{'name': 'researcher'}],
                agent_tool_dependencies=[],
                swarm_roster=False,
            ),
        )


def _hosted_tool(tool_id: str, *dependencies: str) -> dict[str, object]:
    tool: dict[str, object] = {
        'tool_id': tool_id,
        'name': tool_id,
        'description': f'{tool_id} tool.',
        'parameters_schema': {'type': 'object', 'properties': {}},
        'execution': {
            'locus': 'hosted',
            'provider': 'documents',
            'tool_ref': f'documents.{tool_id}',
        },
    }
    if dependencies:
        tool['tool_dependencies'] = [
            {'tool_name': name, 'arg_name': f'{name}_arg'} for name in dependencies
        ]
    return tool


def _swarm(
    agents: list[dict[str, object]],
    dependencies: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return _agent_version_body(
        tools_snapshot=[_hosted_tool('search'), _hosted_tool('publish')],
        agents_snapshot=agents,
        agent_tool_dependencies=dependencies or [],
        swarm_roster=True,
    )


def test_swarm_members_use_only_granted_known_tools_and_peers() -> None:
    """A valid roster grants known tools, finals within grants and known peers."""
    version = AgentVersion.model_validate(
        _swarm(
            [
                {'name': 'researcher', 'tool_ids': ['search']},
                {
                    'name': 'writer',
                    'tool_ids': ['search', 'publish'],
                    'final_tool_ids': ['publish'],
                    'use_as_final_output': True,
                    'peer_dependencies': [
                        {'kind': 'agent', 'name': 'researcher', 'arg_name': 'notes'},
                        {'kind': 'tool', 'name': 'search', 'arg_name': 'hits'},
                    ],
                },
            ],
            [{'agent_name': 'writer', 'tool_id': 'publish', 'arg_name': 'draft'}],
        ),
    )
    assert version.agents_snapshot is not None
    assert [agent.name for agent in version.agents_snapshot] == ['researcher', 'writer']


@pytest.mark.parametrize(
    ('agents', 'dependencies', 'message'),
    [
        ([{'name': 'a'}, {'name': 'a'}], None, 'names must be unique'),
        (
            [
                {'name': 'a', 'use_as_final_output': True},
                {'name': 'b', 'use_as_final_output': True},
            ],
            None,
            'at most one final-output agent',
        ),
        ([{'name': 'a', 'tool_ids': ['missing']}], None, 'unknown tool id'),
        (
            [{'name': 'a', 'tool_ids': ['search'], 'final_tool_ids': ['publish']}],
            None,
            'final tools must be granted',
        ),
        (
            [{'name': 'a', 'peer_dependencies': [{'kind': 'agent', 'name': 'b', 'arg_name': 'x'}]}],
            None,
            'unknown peer dependency',
        ),
        (
            [
                {
                    'name': 'a',
                    'peer_dependencies': [{'kind': 'tool', 'name': 'nope', 'arg_name': 'x'}],
                }
            ],
            None,
            'unknown peer dependency',
        ),
        (
            [{'name': 'a'}],
            [{'agent_name': 'b', 'tool_id': 'search', 'arg_name': 'x'}],
            'must reference the immutable roster and tools',
        ),
        (
            [{'name': 'a'}],
            [{'agent_name': 'a', 'tool_id': 'missing', 'arg_name': 'x'}],
            'must reference the immutable roster and tools',
        ),
    ],
)
def test_swarm_roster_refuses_ambiguous_or_dangling_topology(
    agents: list[dict[str, object]],
    dependencies: list[dict[str, object]] | None,
    message: str,
) -> None:
    """Every roster reference must resolve and the final output must be unambiguous."""
    with pytest.raises(ValidationError, match=message):
        AgentVersion.model_validate(_swarm(agents, dependencies))


@pytest.mark.parametrize(
    ('tools', 'message'),
    [
        ([_hosted_tool('a'), _hosted_tool('a')], 'tool snapshot names must be unique'),
        ([_hosted_tool('a', 'missing')], "tool 'a' depends on an unknown tool"),
        ([_hosted_tool('a', 'b'), _hosted_tool('b', 'a')], 'cannot contain a cycle'),
        ([_hosted_tool('a', 'a')], 'cannot contain a cycle'),
    ],
)
def test_tool_snapshot_dependencies_are_unique_known_and_acyclic(
    tools: list[dict[str, object]],
    message: str,
) -> None:
    """Tool-to-tool wiring names existing, distinct tools and never loops."""
    with pytest.raises(ValidationError, match=message):
        AgentVersion.model_validate(_agent_version_body(tools_snapshot=tools))


def test_tool_snapshot_dependencies_may_share_an_upstream_tool() -> None:
    """A diamond of tool dependencies is not a cycle."""
    tools = [
        _hosted_tool('source'),
        _hosted_tool('left', 'source'),
        _hosted_tool('right', 'source'),
        _hosted_tool('merge', 'left', 'right'),
    ]
    assert AgentVersion.model_validate(_agent_version_body(tools_snapshot=tools))


@pytest.mark.parametrize(
    ('overrides', 'message'),
    [
        ({'execution_mode': 'webhook'}, 'requires webhook_endpoint'),
        (
            {
                'webhook_endpoint': {
                    'url': 'https://tools.example.com/maivn',
                    'secret_ref': 'vault://project/prj/agent/agt/webhook-hmac',
                },
            },
            'only valid for webhook',
        ),
        (
            {
                'execution_mode': 'worker',
                'tools_snapshot': [
                    {
                        **_hosted_tool('send'),
                        'execution': {'locus': 'webhook', 'path': '/tools/send'},
                    },
                ],
            },
            "tool execution locus 'webhook' is not valid for execution_mode 'worker'",
        ),
    ],
)
def test_execution_mode_binds_endpoint_and_tool_loci(
    overrides: dict[str, object],
    message: str,
) -> None:
    """Webhook mode needs an endpoint only it may carry; tool loci match the mode."""
    with pytest.raises(ValidationError, match=message):
        AgentVersion.model_validate(_agent_version_body(**overrides))


@pytest.mark.parametrize('choice', [{}, {'tier': 'balanced', 'model_id': 'gpt-5-mini'}])
def test_model_choice_names_exactly_one_tier_or_model(choice: dict[str, object]) -> None:
    """A model choice is a tier or an exact model id, never both or neither."""
    with pytest.raises(ValidationError):
        AgentVersion.model_validate(_agent_version_body(model={'response': choice}))
