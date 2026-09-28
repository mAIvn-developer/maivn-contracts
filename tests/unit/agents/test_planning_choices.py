"""Planning-choice contracts remain distinct from response model choices."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maivn_contracts.agents import ModelSettings, PlanningChoice, load_agent_version_schema
from maivn_contracts.runtime import RunConfig, load_run_config_schema


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'tier': 'advanced', 'model_id': 'gpt-5.6-terra'},
        {'tier': 'balanced'},
        {'model_id': ''},
    ],
)
def test_planning_choice_requires_one_valid_selector(payload: dict[str, str]) -> None:
    """Planning choices accept only one public planning tier or exact model id."""
    with pytest.raises(ValidationError):
        PlanningChoice.model_validate(payload)


def test_planning_choice_is_frozen_and_available_to_both_config_scopes() -> None:
    """Planning is a separate immutable selector on runs and stored agent versions."""
    planning = PlanningChoice(tier='deep')

    with pytest.raises(ValidationError):
        planning.tier = 'standard'

    settings = ModelSettings.model_validate(
        {'response': {'tier': 'balanced'}, 'planning': planning.model_dump(mode='json')}
    )
    run = RunConfig(user_id='usr-planning', thread_id='thr-planning', planning=planning)

    assert settings.planning == planning
    assert run.planning == planning


def test_run_config_schema_defines_a_distinct_planning_choice() -> None:
    """The authored runtime schema keeps planning tiers separate from response tiers."""
    schema = load_run_config_schema()

    assert schema['properties']['planning']['$ref'] == '#/$defs/planningChoice'
    assert schema['$defs']['planningChoice']['properties']['tier']['enum'] == [
        'auto',
        'standard',
        'advanced',
        'deep',
    ]


def test_agent_version_schema_defines_the_same_separate_planning_choice() -> None:
    """Stored immutable agent settings expose planning without changing response tiers."""
    schema = load_agent_version_schema()

    assert schema['$defs']['modelSettings']['properties']['planning'] == {
        '$ref': '#/$defs/planningChoice'
    }
    assert schema['$defs']['planningChoice']['properties']['tier']['enum'] == [
        'auto',
        'standard',
        'advanced',
        'deep',
    ]
