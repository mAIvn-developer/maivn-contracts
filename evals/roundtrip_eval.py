# pyright: strict
"""Isolated roundtrip eval for the canonical Event contract."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, cast

from maivn_contracts.events import project_event_type, validate_event

_EVAL_TS = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)


def _build_events() -> list[dict[str, Any]]:
    return [
        {
            'event_id': 'evt-eval-trigger-fired-0001',
            'ordinal': 'eval-trigger-000001',
            'type': 'trigger.fired',
            'session_id': 'ses-eval-fire-0001',
            'scenario_id': 'scn-eval-customer-triage',
            'trigger_id': 'trg-eval-inbound-webhook',
            'root_event_id': 'evt-eval-trigger-fired-0001',
            'trigger_chain_depth': 0,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'trigger:inbound-webhook',
            'mode': 'hosted',
            'payload': {'source': 'webhook', 'record_id': 'case-1001'},
            'ts': '2026-07-01T15:00:00Z',
        },
        {
            'event_id': 'evt-eval-agent-thinking-0002',
            'ordinal': 'eval-agent-000002',
            'type': 'planning',
            'session_id': 'ses-eval-fire-0001',
            'scenario_id': 'scn-eval-customer-triage',
            'trigger_id': 'trg-eval-inbound-webhook',
            'root_event_id': 'evt-eval-trigger-fired-0001',
            'parent_trigger_id': 'trg-eval-inbound-webhook',
            'trigger_chain_depth': 1,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'agent:triage',
            'mode': 'hosted',
            'payload': {'phase': 'planning'},
            'ts': '2026-07-01T15:00:01Z',
        },
        {
            'event_id': 'evt-eval-tool-selected-0003',
            'ordinal': 'eval-agent-000003',
            'type': 'agent.tool_selected',
            'session_id': 'ses-eval-fire-0001',
            'scenario_id': 'scn-eval-customer-triage',
            'trigger_id': 'trg-eval-inbound-webhook',
            'root_event_id': 'evt-eval-trigger-fired-0001',
            'parent_trigger_id': 'trg-eval-inbound-webhook',
            'trigger_chain_depth': 1,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'agent:triage',
            'mode': 'hosted',
            'correlation_id': 'eval-tool-call-0003',
            'payload': {'tool_name': 'lookup_case'},
            'ts': '2026-07-01T15:00:02Z',
        },
        {
            'event_id': 'evt-eval-tool-started-0004',
            'ordinal': 'eval-agent-000004',
            'type': 'tool.dispatch_started',
            'session_id': 'ses-eval-fire-0001',
            'scenario_id': 'scn-eval-customer-triage',
            'trigger_id': 'trg-eval-inbound-webhook',
            'root_event_id': 'evt-eval-trigger-fired-0001',
            'parent_trigger_id': 'trg-eval-inbound-webhook',
            'trigger_chain_depth': 1,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'tool:lookup_case',
            'mode': 'webhook',
            'correlation_id': 'eval-tool-call-0003',
            'payload': {'input': {'record_id': 'case-1001'}},
            'ts': '2026-07-01T15:00:03Z',
        },
        {
            'event_id': 'evt-eval-tool-completed-0005',
            'ordinal': 'eval-tool-000005',
            'type': 'tool.dispatch_completed',
            'session_id': 'ses-eval-fire-0001',
            'scenario_id': 'scn-eval-customer-triage',
            'trigger_id': 'trg-eval-inbound-webhook',
            'root_event_id': 'evt-eval-trigger-fired-0001',
            'parent_trigger_id': 'trg-eval-inbound-webhook',
            'trigger_chain_depth': 1,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'tool:lookup_case',
            'mode': 'webhook',
            'correlation_id': 'eval-tool-call-0003',
            'payload': {'output': {'priority': 'high'}},
            'latency_ms': 92,
            'ts': '2026-07-01T15:00:04Z',
        },
        {
            'event_id': 'evt-eval-session-completed-0006',
            'ordinal': 'eval-agent-000006',
            'type': 'session.completed',
            'session_id': 'ses-eval-fire-0001',
            'scenario_id': 'scn-eval-customer-triage',
            'trigger_id': 'trg-eval-inbound-webhook',
            'root_event_id': 'evt-eval-trigger-fired-0001',
            'parent_trigger_id': 'trg-eval-inbound-webhook',
            'trigger_chain_depth': 1,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'agent:triage',
            'mode': 'hosted',
            'payload': {'result': 'drafted escalation response'},
            'ts': '2026-07-01T15:00:05Z',
        },
    ]


def run_eval() -> dict[str, object]:
    """Run the canonical Event contract roundtrip eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.roundtrip',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the canonical Event contract roundtrip eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    events = _build_events()
    errors: list[str] = []
    canvas_targets: list[str] = []
    webhook_targets: list[str] = []

    for event in events:
        event_id = str(event['event_id'])
        try:
            validated = validate_event(event)
            canvas_target = project_event_type(validated.type, 'canvas')
            webhook_target = project_event_type(validated.type, 'webhook')
        except Exception as exc:  # noqa: BLE001
            # Keep the eval collecting all contract/projection failures in one run.
            errors.append(f'{event_id}: {exc}')
            continue

        if canvas_target is not None:
            canvas_targets.append(canvas_target)
        webhook_targets.append(cast('str', webhook_target))

    if errors:
        lines = ['FAIL canonical event roundtrip eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'events_validated': float(len(events) - len(errors))}

    canvas_projection = ','.join(canvas_targets)
    webhook_projection = ','.join(webhook_targets)

    lines = [
        'PASS canonical event roundtrip eval',
        f'events_validated={len(events)}',
        f'canvas_projection={canvas_projection}',
        f'webhook_projection={webhook_projection}',
    ]
    return 0, lines, {'events_validated': float(len(events))}


if __name__ == '__main__':
    sys.exit(main())
