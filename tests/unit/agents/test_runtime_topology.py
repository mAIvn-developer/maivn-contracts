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
