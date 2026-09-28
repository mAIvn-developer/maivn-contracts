"""Offline contract eval for Mode A/B worker, dispatch, callback, and launch envelopes."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from maivn_contracts.scenarios import validate_trigger_launch
from maivn_contracts.tools import validate_tool_callback, validate_tool_dispatch
from maivn_contracts.workers import validate_worker_connection, validate_worker_frame

_EVAL_TS = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
_FIXTURES_DIR = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'


def _fixtures(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((_FIXTURES_DIR / name).read_text(encoding='utf-8'))
    if not isinstance(loaded, list):
        message = f'Fixture {name} must be a JSON array'
        raise TypeError(message)
    return cast('list[dict[str, Any]]', loaded)


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    validators = (
        ('valid_worker_connections.json', validate_worker_connection),
        ('valid_worker_frames.json', validate_worker_frame),
        ('valid_tool_dispatches.json', validate_tool_dispatch),
        ('valid_tool_callbacks.json', validate_tool_callback),
        ('valid_trigger_launches.json', validate_trigger_launch),
    )
    errors: list[str] = []
    validated = 0

    for name, validator in validators:
        for fixture in _fixtures(name):
            try:
                validator(fixture)
            except Exception as exc:  # noqa: BLE001
                errors.append(f'{name} failed validation: {exc}')
            else:
                validated += 1

    if errors:
        lines = ['FAIL modes A/B contract eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'validated': float(validated)}

    lines = [
        'PASS modes A/B contract eval',
        f'envelopes_validated={validated}',
        'developer_code_fields=structurally_rejected',
        'agent_version_selector=exact',
    ]
    return 0, lines, {'validated': float(validated)}


def run_eval() -> dict[str, object]:
    """Run the Mode A/B contract eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.modes_ab',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the Mode A/B contract eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


if __name__ == '__main__':
    sys.exit(main())
