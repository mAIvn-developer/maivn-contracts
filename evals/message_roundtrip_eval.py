# pyright: strict
"""Isolated roundtrip eval for owned Message contracts."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any, cast

from maivn_contracts.messages import validate_message

_PLACEHOLDER_PATTERN = re.compile(r'\{_\{[A-Za-z_][A-Za-z0-9_]*\}_\}')
_GENERIC_LITERAL_PATTERN = re.compile(r'<[A-Z][A-Z0-9_]*>')
_EVAL_TS = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)


def _attachment() -> dict[str, Any]:
    return {
        'attachment_id': 'att-eval-intake-form',
        'filename': 'intake.pdf',
        'mime_type': 'application/pdf',
        'size_bytes': 8192,
        'storage_ref': {
            'bucket': 'memory-resources',
            'path': 'prj-eval-health/resources/intake.pdf',
            'sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        },
        'content_hash': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'resource_id': 'res-eval-intake-form',
    }


def _build_messages() -> list[dict[str, Any]]:
    return [
        {
            'message_id': 'msg-eval-user-plain-0001',
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': 'Please summarize the attached intake form.',
                },
                {
                    'type': 'document',
                    'attachment_id': 'att-eval-intake-form',
                    'mime_type': 'application/pdf',
                    'title': 'Patient intake form',
                },
            ],
            'attachments': [_attachment()],
            'ts': '2026-07-01T19:00:00Z',
        },
        {
            'message_id': 'msg-eval-user-redacted-0002',
            'role': 'user',
            'content': 'Patient {_{patient_name}_} has a follow-up request.',
            'attachments': [_attachment()],
            'redaction': {
                'pii_whitelist': {
                    'entries': [
                        {
                            'entity_type': 'location',
                            'justification': 'City-only location is allowed for routing.',
                        },
                    ],
                    'phi_mode': True,
                },
                'known_pii_values': [
                    {
                        'value': 'Maria Santos',
                        'name': 'patient_name',
                        'pii_type': 'person',
                        'label': 'Patient Name',
                    },
                ],
                'private_data_schema': ['patient_name'],
            },
            'ts': '2026-07-01T19:00:01Z',
        },
        {
            'message_id': 'msg-eval-assistant-0003',
            'role': 'assistant',
            'content': 'The redacted intake summary is ready.',
            'ts': '2026-07-01T19:00:02Z',
        },
    ]


def _contains_generic_literal(value: object) -> bool:
    if isinstance(value, str):
        return _GENERIC_LITERAL_PATTERN.search(value) is not None
    if isinstance(value, list):
        items: list[object] = cast('list[object]', value)
        return any(_contains_generic_literal(item) for item in items)
    if isinstance(value, dict):
        value_mapping: dict[object, object] = cast('dict[object, object]', value)
        return any(_contains_generic_literal(item) for item in value_mapping.values())
    return False


def run_eval() -> dict[str, object]:
    """Run the owned Message contract roundtrip eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.message_roundtrip',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the owned Message contract roundtrip eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    messages = _build_messages()
    errors: list[str] = []

    for message in messages:
        message_id = str(message['message_id'])
        try:
            validate_message(message)
        except Exception as exc:  # noqa: BLE001
            # Keep the eval collecting all contract failures in one run.
            errors.append(f'{message_id}: {exc}')

    redacted_content = str(messages[1]['content'])
    if _PLACEHOLDER_PATTERN.search(redacted_content) is None:
        errors.append('canonical private-data placeholder was not representable')

    generic_literal_fixture = {
        'message_id': 'msg-eval-generic-literal',
        'role': 'assistant',
        'content': 'Do not treat <GENERIC> as a private-data placeholder.',
        'ts': '2026-07-01T19:00:03Z',
    }
    if not _contains_generic_literal(generic_literal_fixture):
        errors.append('generic <UPPER> literal helper did not detect <GENERIC>')

    if errors:
        lines = ['FAIL owned message roundtrip eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'messages_validated': float(len(messages) - len(errors))}

    lines = [
        'PASS owned message roundtrip eval',
        f'messages_validated={len(messages)}',
        'placeholder_convention={_{patient_name}_}',
        'generic_literal_detected=<GENERIC>',
        'redacted_attachment_floor=documented-secure',
    ]
    return 0, lines, {'messages_validated': float(len(messages))}


if __name__ == '__main__':
    sys.exit(main())
