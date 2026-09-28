# pyright: strict
"""Isolated eval for the owned runtime protocol contract."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from pydantic import BaseModel

from maivn_contracts.runtime import (
    CancelCommand,
    Command,
    ResumeCommand,
    RunConfig,
    RunState,
    RuntimeProtocol,
    StartCommand,
    StreamMode,
    StreamPart,
    validate_command,
    validate_run_config,
    validate_run_state,
    validate_stream_part,
)

ModelValidator: TypeAlias = Callable[[dict[str, Any]], object]
_EVAL_TS = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)


class FakeInMemoryRuntime:
    """Scripted in-memory RuntimeProtocol implementation for evals and tests."""

    def __init__(self) -> None:
        """Initialize the fake runtime with no active thread."""
        self._state = RunState.model_validate(
            {
                'thread_id': 'thr-eval-001',
                'run_id': 'run-eval-000',
                'status': 'pending',
                'values': {},
                'ts': '2026-07-02T18:00:00Z',
            },
        )

    async def create_thread(self) -> RunState:
        """Create the eval thread."""
        self._state = RunState.model_validate(
            {
                'thread_id': 'thr-eval-001',
                'run_id': 'run-eval-000',
                'status': 'pending',
                'values': {'created': True},
                'ts': '2026-07-02T18:00:00Z',
            },
        )
        return self._state

    async def get_state(self, thread_id: str) -> RunState:
        """Return the eval thread state."""
        if thread_id == self._state.thread_id:
            return self._state
        return RunState.model_validate(
            {
                'thread_id': thread_id,
                'run_id': 'run-eval-missing',
                'status': 'failed',
                'values': {'error': 'unknown thread'},
                'ts': '2026-07-02T18:00:00Z',
            },
        )

    async def wait(self, command: Command, config: RunConfig) -> RunState:
        """Advance the eval state for start, resume, or cancel."""
        if isinstance(command, StartCommand):
            self._state = RunState.model_validate(
                {
                    'thread_id': config.thread_id,
                    'run_id': 'run-eval-001',
                    'status': 'interrupted',
                    'interrupt': {
                        'checkpoint_id': 'chk-eval-approval-001',
                        'reason': 'approval_required',
                        'payload': {'question': 'Approve the support reply?'},
                    },
                    'values': {'phase': 'waiting_for_approval'},
                    'ts': '2026-07-02T18:00:04Z',
                },
            )
        elif isinstance(command, CancelCommand):
            self._state = RunState.model_validate(
                {
                    'thread_id': config.thread_id,
                    'run_id': 'run-eval-001',
                    'status': 'cancelled',
                    'values': {'reason': command.reason},
                    'ts': '2026-07-02T18:00:05Z',
                },
            )
        else:
            self._state = RunState.model_validate(
                {
                    'thread_id': config.thread_id,
                    'run_id': 'run-eval-001',
                    'status': 'completed',
                    'values': {'approved': True, 'final_message_id': 'msg-eval-final'},
                    'ts': '2026-07-02T18:00:06Z',
                },
            )
        return self._state

    def stream(
        self,
        command: Command,
        config: RunConfig,
        stream_modes: Sequence[StreamMode] = ('updates',),
    ) -> AsyncIterator[StreamPart]:
        """Stream the scripted eval parts."""
        _ = command
        _ = config
        _ = stream_modes
        return self._scripted_stream()

    async def cancel(self, command: CancelCommand, config: RunConfig) -> RunState:
        """Cancel the eval run."""
        return await self.wait(command, config)

    async def _scripted_stream(self) -> AsyncIterator[StreamPart]:
        yield StreamPart.model_validate(
            {
                'event': 'values',
                'stream_mode': 'values',
                'data': {'state': {'phase': 'planning'}},
                'subgraph_path': [],
                'ordinal': 'runtime-eval-000001',
                'ts': '2026-07-02T18:00:01Z',
            },
        )
        yield StreamPart.model_validate(
            {
                'event': 'messages/partial',
                'stream_mode': 'messages',
                'data': {'message_id': 'msg-eval-assistant', 'delta': 'Reviewing the case.'},
                'subgraph_path': [],
                'ordinal': 'runtime-eval-000002',
                'ts': '2026-07-02T18:00:02Z',
            },
        )
        yield StreamPart.model_validate(
            {
                'event': 'custom/assignment.progress',
                'stream_mode': 'custom',
                'data': {'assignment_uuid': 'assign-eval-child-001', 'status': 'running'},
                'subgraph_path': ['orchestrator', 'assignment_agent'],
                'ordinal': 'runtime-eval-000003',
                'ts': '2026-07-02T18:00:03Z',
            },
        )


def _message() -> dict[str, Any]:
    return {
        'message_id': 'msg-eval-user-001',
        'role': 'user',
        'content': 'Draft a concise reply for the high-priority support case.',
        'ts': '2026-07-02T18:00:00Z',
    }


def _dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode='json', exclude_none=True)


def _validate_model(
    label: str,
    model: BaseModel,
    validator: ModelValidator,
    errors: list[str],
) -> None:
    try:
        validator(_dump_model(model))
    except Exception as exc:  # noqa: BLE001
        # Keep the eval collecting all contract failures in one run.
        errors.append(f'{label} failed schema validation: {exc}')


async def _run_eval(errors: list[str]) -> dict[str, str]:
    runtime: RuntimeProtocol = FakeInMemoryRuntime()
    created = await runtime.create_thread()
    _validate_model('created state', created, validate_run_state, errors)

    config = RunConfig.model_validate(
        {
            'user_id': 'usr-eval-001',
            'thread_id': created.thread_id,
            'session_id': 'ses-eval-001',
            'invocation_id': 'inv-eval-001',
            'project_id': 'prj-eval',
            'model_directive': 'balanced',
            'job_depth': 0,
            'job_index': 0,
        },
    )
    _validate_model('run config', config, validate_run_config, errors)

    start = StartCommand.model_validate(
        {
            'kind': 'start',
            'messages': [_message()],
            'options': {'assistant_id': 'agt-support-triage'},
        },
    )
    _validate_model('start command', start, validate_command, errors)

    stream_parts: list[StreamPart] = []
    async for part in runtime.stream(start, config, ('values', 'messages', 'custom')):
        stream_parts.append(part)
        _validate_model(f'stream part {part.ordinal}', part, validate_stream_part, errors)

    interrupted = await runtime.wait(start, config)
    _validate_model('interrupted state', interrupted, validate_run_state, errors)
    if interrupted.interrupt is None:
        errors.append('interrupted state did not expose an interrupt payload')
        checkpoint_id = 'missing'
    else:
        checkpoint_id = interrupted.interrupt.checkpoint_id

    resume = ResumeCommand.model_validate(
        {
            'kind': 'resume',
            'checkpoint_id': checkpoint_id,
            'value': {'approved': True, 'approver': 'usr-eval-001'},
        },
    )
    _validate_model('resume command', resume, validate_command, errors)

    completed = await runtime.wait(resume, config)
    _validate_model('completed state', completed, validate_run_state, errors)

    latest = await runtime.get_state(created.thread_id)
    _validate_model('latest state', latest, validate_run_state, errors)

    nested_custom_count = sum(1 for part in stream_parts if part.subgraph_path)
    return {
        'thread_id': created.thread_id,
        'run_id': completed.run_id,
        'stream_parts': str(len(stream_parts)),
        'nested_custom_parts': str(nested_custom_count),
        'final_status': completed.status,
    }


def run_eval() -> dict[str, object]:
    """Run the owned runtime protocol eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.run_protocol',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the owned runtime protocol eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    errors: list[str] = []
    summary = asyncio.run(_run_eval(errors))

    if errors:
        lines = ['FAIL run protocol eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'stream_parts': float(summary.get('stream_parts', '0'))}

    lines = ['PASS run protocol eval', *[f'{key}={value}' for key, value in summary.items()]]
    return (
        0,
        lines,
        {
            'stream_parts': float(summary['stream_parts']),
            'nested_custom_parts': float(summary['nested_custom_parts']),
        },
    )


if __name__ == '__main__':
    sys.exit(main())
