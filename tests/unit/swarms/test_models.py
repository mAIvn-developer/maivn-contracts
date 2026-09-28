# pyright: strict
"""Unit tests for Swarm contract models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.swarms import Swarm

_RESOLUTION_VERSION = 3


def test_swarm_accepts_agents_global_toolbelt_and_shared_skills() -> None:
    """Swarm carries agent refs plus global tool and skill references."""
    swarm = Swarm.model_validate(
        {
            'swarm_id': 'swm-support',
            'org_id': 'org-acme',
            'name': 'Support desk',
            'description': 'Routes and resolves customer issues.',
            'model': {'tier': 'balanced'},
            'agents': [
                {'agent_id': 'agt-triage', 'version': 'latest'},
                {'agent_id': 'agt-resolution', 'version': _RESOLUTION_VERSION},
            ],
            'global_tools': [
                {
                    'tool_id': 'tool-http-fetch',
                    'namespace': 'connectors.http',
                    'version': '2026-07-06',
                },
            ],
            'global_tool_sets': [
                {
                    'kind': 'toolset',
                    'toolset_id': 'tset-slack',
                    'namespace': 'connectors.slack',
                    'version': '2026-07-06',
                },
            ],
            'shared_skill_ids': ['skill-tone'],
            'shared_skill_set_ids': ['skillset-support'],
            'created_at': '2026-07-06T15:00:00Z',
            'updated_at': '2026-07-06T15:00:00Z',
        },
    )

    assert swarm.agents[0].version == 'latest'
    assert swarm.agents[1].version == _RESOLUTION_VERSION
    assert swarm.global_tools[0].tool_id == 'tool-http-fetch'
    assert swarm.global_tool_sets[0].toolset_id == 'tset-slack'
    assert Swarm.__doc__ is not None
    assert 'available to EVERY nested agent' in Swarm.__doc__


def test_swarm_rejects_extra_fields_and_invalid_agent_versions() -> None:
    """Strict Swarm contracts reject unknown fields and non-positive version pins."""
    base: dict[str, Any] = {
        'swarm_id': 'swm-support',
        'org_id': 'org-acme',
        'name': 'Support desk',
        'model': {'tier': 'balanced'},
        'agents': [{'agent_id': 'agt-triage', 'version': 'latest'}],
        'global_tools': [],
        'global_tool_sets': [],
        'shared_skill_ids': [],
        'shared_skill_set_ids': [],
        'created_at': '2026-07-06T15:00:00Z',
        'updated_at': '2026-07-06T15:00:00Z',
    }

    with pytest.raises(ValidationError):
        Swarm.model_validate(base | {'unexpected': True})

    with pytest.raises(ValidationError):
        Swarm.model_validate(base | {'agents': [{'agent_id': 'agt-triage', 'version': 0}]})
