# pyright: strict
"""Isolated eval for the deployed-agent registry contracts."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, cast

from maivn_contracts.agents import (
    TemplateMessageBinding,
    validate_agent,
    validate_agent_version,
    validate_message_binding,
)

_PLACEHOLDER_PATTERN = re.compile(r'\{\{event\.([A-Za-z0-9_.]+)\}\}')
_EVAL_TS = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)


class _MissingEventPathError(KeyError):
    """Raised when a local preview template references a missing event path."""

    def __init__(self, dotted_path: str) -> None:
        """Build the missing event path error."""
        message = f'missing event path: {dotted_path}'
        super().__init__(message)


def _agent() -> dict[str, Any]:
    return {
        'agent_id': 'agt-eval-customer-triage',
        'project_id': 'prj-eval-support',
        'name': 'Eval customer triage',
        'description': 'Classifies support cases from trigger payloads.',
        'latest_version': 2,
        'created_at': '2026-07-01T17:00:00Z',
        'updated_at': '2026-07-01T17:15:00Z',
    }


def _version_1() -> dict[str, Any]:
    return {
        'agent_id': 'agt-eval-customer-triage',
        'version': 1,
        'execution_mode': 'hosted_only',
        'model': {'response': {'tier': 'fast'}},
        'instructions': {
            'kind': 'inline',
            'content': 'Use hosted connector tools to classify the support case.',
        },
        'tools_snapshot': [
            {
                'name': 'gmail_fetch_thread',
                'description': 'Read a Gmail thread through the hosted connector.',
                'parameters_schema': {
                    'type': 'object',
                    'properties': {'thread_id': {'type': 'string'}},
                    'required': ['thread_id'],
                },
                'execution': {
                    'locus': 'hosted',
                    'provider': 'gmail',
                    'tool_ref': 'gmail.fetch_thread',
                },
            },
        ],
        'created_at': '2026-07-01T17:01:00Z',
        'created_by': 'usr-platform-owner',
    }


def _version_2() -> dict[str, Any]:
    return {
        'agent_id': 'agt-eval-customer-triage',
        'version': 2,
        'execution_mode': 'webhook',
        'model': {'response': {'tier': 'balanced'}},
        'instructions': {
            'kind': 'ref',
            'ref': 'maivn://prompts/eval-customer-triage/v2',
        },
        'tools_snapshot': [
            {
                'name': 'lookup_customer',
                'description': 'Fetch customer account and entitlement details.',
                'parameters_schema': {
                    'type': 'object',
                    'properties': {'customer_id': {'type': 'string'}},
                    'required': ['customer_id'],
                },
                'execution': {'locus': 'webhook', 'path': '/tools/lookup-customer'},
            },
        ],
        'webhook_endpoint': {
            'url': 'https://tools.example.com/maivn',
            'secret_ref': (
                'vault://project/prj-eval-support/agent/agt-eval-customer-triage/webhook-hmac'
            ),
        },
        'created_at': '2026-07-01T17:15:00Z',
        'created_by': 'usr-platform-owner',
    }


def _template_binding() -> dict[str, Any]:
    return {
        'kind': 'template',
        'messages': [
            'Case {{event.case.id}} for {{event.customer.email}}.',
            'Priority: {{event.case.priority}}',
        ],
    }


def _trigger_event_payload() -> dict[str, Any]:
    return {
        'case': {
            'id': 'case-1001',
            'priority': 'high',
        },
        'customer': {
            'email': 'ada@example.com',
        },
    }


def _canonical_bytes(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _resolve_event_path(event: dict[str, Any], dotted_path: str) -> str:
    current: object = event
    for part in dotted_path.split('.'):
        if not isinstance(current, dict) or part not in current:
            raise _MissingEventPathError(dotted_path)
        current_mapping = cast('dict[str, object]', current)
        current = current_mapping[part]
    return str(current)


def _preview_render(messages: list[str], event: dict[str, Any]) -> list[str]:
    def replace_placeholder(match: re.Match[str]) -> str:
        return _resolve_event_path(event, match.group(1))

    return [_PLACEHOLDER_PATTERN.sub(replace_placeholder, message) for message in messages]


def run_eval() -> dict[str, object]:
    """Run the deployed-agent registry eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.agent_registry',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the deployed-agent registry eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    errors: list[str] = []
    agent = _agent()
    version_1 = _version_1()
    version_1_before = _canonical_bytes(version_1)
    version_2 = _version_2()
    binding = _template_binding()
    payload = _trigger_event_payload()

    try:
        validate_agent(agent)
        validate_agent_version(version_1)
        validate_agent_version(version_2)
        validated_binding = validate_message_binding(binding)
        validate_agent_version(version_1)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    else:
        if version_1_before != _canonical_bytes(version_1):
            errors.append('version 1 changed after version 2 was created')
        if not isinstance(validated_binding, TemplateMessageBinding):
            errors.append('expected template binding for local preview')
        else:
            preview = _preview_render(validated_binding.messages, payload)
            if preview != ['Case case-1001 for ada@example.com.', 'Priority: high']:
                errors.append(f'unexpected preview-rendered messages: {preview}')

    if errors:
        lines = ['FAIL deployed-agent registry eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'records_validated': 0.0}

    lines = [
        'PASS deployed-agent registry eval',
        'records_validated=4',
        'version_1_immutability=byte-identical',
        'preview_messages=Case case-1001 for ada@example.com.|Priority: high',
        'note=local preview only; authoritative template rendering is server-side',
    ]
    return 0, lines, {'records_validated': 4.0}


if __name__ == '__main__':
    sys.exit(main())
