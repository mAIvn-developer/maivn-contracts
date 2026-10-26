# pyright: strict
"""Unit tests for runtime contract loaders, validators, and protocol shape."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.runtime import (
    CancelCommand,
    Command,
    RunConfig,
    RunState,
    RuntimeProtocol,
    StartCommand,
    StreamMode,
    StreamPart,
    load_command_schema,
    load_run_config_schema,
    load_run_state_schema,
    load_stream_part_schema,
    validate_command,
    validate_run_config,
    validate_run_state,
    validate_stream_part,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
_RECURSION_LIMIT_DEFAULT = 100
_RECURSION_LIMIT_MAX = 1000
ContractValidator: TypeAlias = Callable[[dict[str, Any]], object]


class FakeRuntime:
    """Small in-memory implementation that satisfies RuntimeProtocol."""

    def __init__(self) -> None:
        """Create the scripted fake runtime state."""
        self._state = RunState.model_validate(
            {
                'thread_id': 'thr-fake-001',
                'run_id': 'run-fake-001',
                'status': 'pending',
                'values': {},
                'ts': '2026-07-02T17:30:00Z',
            },
        )

    async def create_thread(self) -> RunState:
        """Create a fake thread state."""
        return self._state

    async def get_state(self, thread_id: str) -> RunState:
        """Return the current fake thread state."""
        if thread_id != self._state.thread_id:
            return RunState.model_validate(
                {
                    'thread_id': thread_id,
                    'run_id': 'run-missing',
                    'status': 'failed',
                    'values': {'error': 'unknown thread'},
                    'ts': '2026-07-02T17:30:00Z',
                },
            )
        return self._state

    async def wait(self, command: Command, config: RunConfig) -> RunState:
        """Advance the fake state for a start, resume, or cancel command."""
        if isinstance(command, StartCommand):
            self._state = RunState.model_validate(
                {
                    'thread_id': config.thread_id,
                    'run_id': 'run-fake-001',
                    'status': 'interrupted',
                    'interrupt': {
                        'checkpoint_id': 'chk-fake-001',
                        'reason': 'approval_required',
                        'payload': {'question': 'Approve?'},
                    },
                    'values': {'phase': 'waiting_for_approval'},
                    'ts': '2026-07-02T17:30:03Z',
                },
            )
        elif isinstance(command, CancelCommand):
            self._state = RunState.model_validate(
                {
                    'thread_id': config.thread_id,
                    'run_id': 'run-fake-001',
                    'status': 'cancelled',
                    'values': {'reason': command.reason},
                    'ts': '2026-07-02T17:30:04Z',
                },
            )
        else:
            self._state = RunState.model_validate(
                {
                    'thread_id': config.thread_id,
                    'run_id': 'run-fake-001',
                    'status': 'completed',
                    'values': {'approved': True},
                    'ts': '2026-07-02T17:30:05Z',
                },
            )
        return self._state

    def stream(
        self,
        command: Command,
        config: RunConfig,
        stream_modes: Sequence[StreamMode] = ('updates',),
    ) -> AsyncIterator[StreamPart]:
        """Return scripted fake stream parts."""
        _ = command
        _ = config
        _ = stream_modes
        return self._scripted_stream()

    async def cancel(self, command: CancelCommand, config: RunConfig) -> RunState:
        """Cancel the fake run."""
        return await self.wait(command, config)

    async def _scripted_stream(self) -> AsyncIterator[StreamPart]:
        yield StreamPart.model_validate(
            {
                'event': 'custom/assignment.progress',
                'stream_mode': 'custom',
                'data': {'assignment_uuid': 'assign-fake-001'},
                'subgraph_path': ['orchestrator', 'assignment_agent'],
                'ordinal': 'runtime-fake-000001',
                'ts': '2026-07-02T17:30:01Z',
            },
        )


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_load_run_config_schema_exposes_v1_grounded_defaults() -> None:
    """Expose run config fields and defaults from the v1 build_config contract."""
    schema = load_run_config_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'max_expense_usd',
        'user_id',
        'thread_id',
        'session_id',
        'invocation_id',
        'project_id',
        'organization_id',
        'routing_preference',
        'system_model_choices',
        'planning',
        'agent_id',
        'swarm_id',
        'client_timezone',
        'sdk_deployment_timezone',
        'model_directive',
        'job_depth',
        'job_index',
        'parent_assignment_uuid',
        'child_run_kind',
        'plan_node_id',
        'decomposition_depth',
        'recursion_limit',
        'durability',
        'origin',
    }
    assert schema['properties']['recursion_limit']['default'] == _RECURSION_LIMIT_DEFAULT
    assert schema['properties']['recursion_limit']['minimum'] == 1
    assert schema['properties']['recursion_limit']['maximum'] == _RECURSION_LIMIT_MAX
    assert schema['properties']['durability']['default'] == 'exit'
    # origin is display/filter only: no "enum" keyword, so unrecognized future client
    # names are accepted on read rather than rejected by strict schema validation.
    assert 'enum' not in schema['properties']['origin']


def test_run_config_accepts_closed_system_model_choices() -> None:
    """Each model-backed system tool uses the exact-or-tier model-choice contract."""
    config = validate_run_config(
        {
            'user_id': 'usr-system-models',
            'thread_id': 'thr-system-models',
            'system_model_choices': {
                'thinking': {'tier': 'max'},
                'compose_argument': {'tier': 'ultra'},
                'repl': {'model_id': 'gpt-5.6-luna'},
            },
        }
    )

    assert config.model_dump(mode='json', exclude_none=True)['system_model_choices'] == {
        'thinking': {'tier': 'max'},
        'compose_argument': {'tier': 'ultra'},
        'repl': {'model_id': 'gpt-5.6-luna'},
    }


def test_load_command_schema_keeps_runtime_goto_internal() -> None:
    """Expose only start, resume, and cancel command variants on the wire."""
    schema = load_command_schema()

    assert schema['additionalProperties'] is False
    assert schema['discriminator']['propertyName'] == 'kind'
    assert set(schema['$defs']) == {
        'cancelCommand',
        'message',
        'resumeCommand',
        'startCommand',
    }
    assert 'goto' not in json.dumps(schema, sort_keys=True)


def test_load_stream_part_schema_requires_subgraph_path_and_stream_modes() -> None:
    """Expose stream part namespacing and the owned StreamMode vocabulary."""
    schema = load_stream_part_schema()

    assert set(schema['properties']) == {
        'event',
        'stream_mode',
        'data',
        'subgraph_path',
        'ordinal',
        'ts',
    }
    assert 'subgraph_path' in set(schema['required'])
    assert set(schema['$defs']['streamMode']['enum']) == {
        'values',
        'messages',
        'updates',
        'custom',
    }


def test_load_run_state_schema_exposes_hitl_interrupt_surface() -> None:
    """Expose queryable run state plus the owned interrupt checkpoint surface."""
    schema = load_run_state_schema()

    assert set(schema['properties']) == {
        'thread_id',
        'run_id',
        'status',
        'interrupt',
        'values',
        'ts',
    }
    assert set(schema['properties']['status']['enum']) == {
        'pending',
        'running',
        'interrupted',
        'completed',
        'failed',
        'cancelled',
        # Startup reconciliation's terminal status for a run whose owning process died:
        # neither a failure nor a cancellation (owner ruling 2026-08-21).
        'abandoned',
    }
    assert set(schema['$defs']['interrupt']['properties']) == {
        'checkpoint_id',
        'kind',
        'reason',
        'payload',
        'prompt_source',
        'question',
        'response_schema',
        'session_id',
        'thread_id',
    }


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('valid_run_configs.json', validate_run_config),
        ('valid_commands.json', validate_command),
        ('valid_stream_parts.json', validate_stream_part),
        ('valid_run_states.json', validate_run_state),
    ],
)
def test_validators_accept_valid_runtime_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Accept every valid runtime-contract fixture."""
    for fixture in _load_fixture(fixture_name):
        validated = validator(fixture)
        assert isinstance(validated, BaseModel)


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('invalid_run_configs.json', validate_run_config),
        ('invalid_commands.json', validate_command),
        ('invalid_stream_parts.json', validate_stream_part),
        ('invalid_run_states.json', validate_run_state),
    ],
)
def test_validators_reject_invalid_runtime_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Reject every invalid runtime-contract fixture."""
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)


def test_run_config_defaults_are_filled_by_model() -> None:
    """Fill the owned recursion and durability defaults on minimal configs."""
    minimal_config = _load_fixture('valid_run_configs.json')[1]

    validated = validate_run_config(minimal_config)

    assert validated.recursion_limit == _RECURSION_LIMIT_DEFAULT
    assert validated.durability == 'exit'


def test_run_config_origin_is_absent_by_default_and_display_only() -> None:
    """Historical rows validate with no origin; a seeded fixture carries one through."""
    minimal_config = _load_fixture('valid_run_configs.json')[1]
    tagged_config = _load_fixture('valid_run_configs.json')[0]

    minimal = validate_run_config(minimal_config)
    tagged = validate_run_config(tagged_config)

    assert minimal.origin is None
    assert tagged.origin == 'studio'


def test_run_config_origin_tolerates_unrecognized_client_names() -> None:
    """A future client's self-reported origin round-trips even if it predates the schema."""
    config = {
        'user_id': 'usr-tolerant-001',
        'thread_id': 'thr-tolerant-001',
        'origin': 'some-future-client',
    }

    validated = validate_run_config(config)

    assert validated.origin == 'some-future-client'


def test_runtime_protocol_accepts_fake_in_memory_implementation() -> None:
    """Pin RuntimeProtocol as runtime-checkable for in-memory test doubles."""
    runtime = FakeRuntime()

    assert isinstance(runtime, RuntimeProtocol)
