# pyright: strict
"""Isolated eval for trigger and scenario lifecycle contracts."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from maivn_contracts.events import validate_event
from maivn_contracts.scenarios import (
    validate_scenario,
    validate_trigger,
    validate_trigger_fire,
    validate_trigger_invocation,
)

_EVAL_TS = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)


def _scenario() -> dict[str, Any]:
    return {
        'scenario_id': 'scn-eval-customer-triage',
        'project_id': 'prj-eval-support',
        'name': 'Eval customer triage',
        'trigger_id': 'trg-eval-support-webhook',
        'revision': 1,
        'agent': {'agent_id': 'agt-eval-customer-triage', 'version': 1},
        'output_binding': {
            'kind': 'event_emission',
            'target': {'event_type': 'support.case.triaged'},
        },
        'layout': {
            'node_positions': {
                'trigger': {'x': 0, 'y': 120},
                'agent': {'x': 360, 'y': 120},
                'output': {'x': 720, 'y': 120},
            },
        },
        'created_at': '2026-07-01T19:00:00Z',
        'updated_at': '2026-07-01T19:00:00Z',
    }


def _file_scenario() -> dict[str, Any]:
    scenario = _scenario()
    scenario['scenario_id'] = 'scn-eval-file-export'
    scenario['name'] = 'Eval file export'
    scenario['output_binding'] = {
        'kind': 'file',
        'selector': {
            'selector_type': 'logical_output',
            'logical_output_name': 'case_brief',
        },
        'required_kind': 'document',
        'allowed_mime_types': ['application/pdf'],
        'required_custody': 'ordinary',
        'destination_connection_ref': 'connection-eval-export',
        'mode': 'attachment',
        'delivery_policy': {
            'max_size_bytes': 10485760,
            'authorization_ttl_seconds': 900,
            'max_attempts': 3,
            'initial_retry_delay_seconds': 5,
        },
        'private_export_authorization_required': False,
        'idempotency_key_template': (
            '{scenario_revision}:{invocation_id}:{artifact_id}:{destination_revision}'
        ),
    }
    return scenario


def _trigger() -> dict[str, Any]:
    return {
        'trigger_id': 'trg-eval-support-webhook',
        'project_id': 'prj-eval-support',
        'name': 'Eval support webhook',
        'status': 'enabled',
        'source': {
            'kind': 'webhook',
            'phase': 'phase_1',
            'secret_ref': 'vault://project/prj-eval-support/trigger/trg-eval-support-webhook/hmac',
        },
        'filter': "$.case[?(@.priority == 'high')]",
        'binding': {
            'kind': 'template',
            'messages': [
                'Triage case {{event.case.id}} from {{event.customer.email}}.',
            ],
        },
        'agent': {'agent_id': 'agt-eval-customer-triage', 'version': 1},
        'options': {
            'concurrency': 4,
            'retry_policy': {
                'max_attempts': 3,
                'initial_delay_seconds': 30,
                'max_delay_seconds': 3600,
                'backoff': 'exponential',
            },
            'dedupe_window_seconds': 86400,
            'depth_cap': 8,
            'fanout_cap': 100,
            'fire_budget': 5,
        },
        'scenario_id': 'scn-eval-customer-triage',
        'created_at': '2026-07-01T19:00:00Z',
        'updated_at': '2026-07-01T19:00:00Z',
    }


def _inbound_payload() -> dict[str, Any]:
    return {
        'case': {'id': 'case-2001', 'priority': 'high'},
        'customer': {'email': 'grace@example.com'},
    }


def _fire(root_event_id: str, status: str) -> dict[str, Any]:
    return {
        'fire_id': 'fire-eval-support-webhook-0001',
        'trigger_id': 'trg-eval-support-webhook',
        'dedupe_key': 'case-2001',
        'priority': 'triggered',
        'status': status,
        'available_at': '2026-07-01T19:01:00Z',
        'attempt': 0,
        'payload': _inbound_payload(),
        'root_event_id': root_event_id,
        'trigger_chain_depth': 0,
    }


def _invocation(root_event_id: str) -> dict[str, Any]:
    return {
        'invocation_id': 'inv-eval-support-webhook-0001',
        'fire_id': 'fire-eval-support-webhook-0001',
        'trigger_id': 'trg-eval-support-webhook',
        'session_id': 'ses-eval-support-webhook-0001',
        'status': 'completed',
        'outcome': None,
        'started_at': '2026-07-01T19:01:01Z',
        'finished_at': '2026-07-01T19:01:09Z',
        'root_event_id': root_event_id,
        'parent_trigger_id': 'trg-eval-support-webhook',
        'trigger_chain_depth': 1,
    }


def _canonical_event(root_event_id: str) -> dict[str, Any]:
    return {
        'event_id': root_event_id,
        'ordinal': 'eval-trigger-lifecycle-000001',
        'type': 'trigger.fired',
        'session_id': 'ses-eval-support-webhook-0001',
        'scenario_id': 'scn-eval-customer-triage',
        'trigger_id': 'trg-eval-support-webhook',
        'root_event_id': root_event_id,
        'trigger_chain_depth': 0,
        'job_depth': 0,
        'job_index': 0,
        'actor': 'trigger:eval-support-webhook',
        'mode': 'hosted',
        'payload': _inbound_payload(),
        'ts': '2026-07-01T19:01:00Z',
    }


def run_eval() -> dict[str, object]:
    """Run the trigger lifecycle eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.trigger_lifecycle',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the trigger lifecycle eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    errors: list[str] = []
    root_event_id = f'evt-eval-root-{uuid4().hex[:12]}'

    try:
        validate_scenario(_scenario())
        validate_scenario(_file_scenario())
        validate_trigger(_trigger())
        validate_trigger_fire(_fire(root_event_id, 'pending'))
        validate_trigger_fire(_fire(root_event_id, 'claimed'))
        validate_trigger_fire(_fire(root_event_id, 'completed'))
        validate_trigger_invocation(_invocation(root_event_id))
        validate_event(_canonical_event(root_event_id))
    except Exception as exc:  # noqa: BLE001
        # Keep the eval returning a concise contract failure summary.
        errors.append(str(exc))

    if errors:
        lines = ['FAIL trigger lifecycle eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'lifecycle_records_validated': 0.0}

    lines = [
        'PASS trigger lifecycle eval',
        'scenario_validated=2',
        'file_output_binding=validated',
        'trigger_validated=1',
        'fire_states_validated=pending,claimed,completed',
        'invocation_validated=1',
        'canonical_event_lineage_validated=1',
    ]
    return 0, lines, {'lifecycle_records_validated': 8.0}


if __name__ == '__main__':
    sys.exit(main())
