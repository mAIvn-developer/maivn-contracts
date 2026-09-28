# pyright: strict
"""Unit tests for the curated session audit-log assembly."""

from __future__ import annotations

from typing import Any

import pytest

from maivn_contracts.events import Event, assemble_session_audit


def _event(
    index: int,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> Event:
    return Event.model_validate(
        {
            'event_id': f'evt-audit-{index}',
            'ordinal': f'producer-audit-{index:06d}',
            'type': event_type,
            'session_id': 'ses-audit',
            'root_event_id': 'evt-audit-root',
            'trigger_id': 'trg-audit',
            'trigger_chain_depth': 0,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'user:operator-7',
            'mode': 'hosted',
            'payload': payload or {},
            'ts': f'2026-07-15T12:00:{index:02d}Z',
        },
    )


def test_audit_entries_curate_security_events_with_safe_payload_fields() -> None:
    """Audit entries expose actions and safe identifiers, never source payloads."""
    audit = assemble_session_audit(
        [
            _event(
                1,
                'trigger.skipped',
                payload={
                    'trigger_id': 'trg-audit',
                    'reason_code': 'quota_exceeded',
                    'message': 'secret',
                },
            ),
            _event(
                2,
                'message_redaction_applied',
                payload={
                    'entity_count': 3,
                    'redaction_count': 3,
                    'values': ['never-expose'],
                },
            ),
        ],
        session_id='ses-audit',
    )

    assert [(entry.action, entry.resource, entry.outcome) for entry in audit.entries] == [
        ('trigger.skipped', 'trigger:trg-audit', 'denied'),
        ('privacy.redaction_applied', 'session:ses-audit', 'success'),
    ]
    assert audit.entries[0].reason_code == 'quota_exceeded'
    assert audit.entries[1].details == {'entity_count': 3, 'redaction_count': 3}
    assert 'secret' not in audit.model_dump_json()
    assert 'never-expose' not in audit.model_dump_json()


def test_redaction_audit_entry_carries_counts_and_never_values() -> None:
    """Privacy outcomes retain only redaction counts and safe outcome codes."""
    audit = assemble_session_audit(
        [
            _event(
                3,
                'message_redaction_applied',
                payload={
                    'redaction_count': 2,
                    'entity_count': 3,
                    'redacted_values': ['alice@example.test', '555-0100'],
                    'original_content': 'Contact Alice at alice@example.test',
                },
            ),
        ],
        session_id='ses-audit',
    )

    entry = audit.entries[0]
    assert entry.action == 'privacy.redaction_applied'
    assert entry.resource == 'session:ses-audit'
    assert entry.details == {'entity_count': 3, 'redaction_count': 2}
    rendered = audit.model_dump_json()
    assert 'alice@example.test' not in rendered
    assert '555-0100' not in rendered
    assert 'Contact Alice' not in rendered


def test_fire_trigger_request_audit_uses_only_server_request_identity() -> None:
    """A model-supplied target and caller payload never enter the audit projection."""
    audit = assemble_session_audit(
        [
            _event(
                4,
                'trigger.fire_requested',
                payload={
                    'request_id': 'evt-fire-trigger-safe',
                    'target_trigger_id': 'target-with-sensitive-label',
                    'payload': {'customer': 'never-expose'},
                },
            ),
        ],
        session_id='ses-audit',
    )

    entry = audit.entries[0]
    assert entry.action == 'trigger.requested'
    assert entry.resource == 'trigger_request:evt-fire-trigger-safe'
    assert entry.details == {'request_id': 'evt-fire-trigger-safe'}
    rendered = audit.model_dump_json()
    assert 'target-with-sensitive-label' not in rendered
    assert 'never-expose' not in rendered


@pytest.mark.parametrize('event_type', ['connection.event_received', 'email.received'])
def test_connected_source_audit_never_exposes_nested_provider_data(event_type: str) -> None:
    """Connection audit retains routing identifiers and drops customer content."""
    audit = assemble_session_audit(
        [
            _event(
                5,
                event_type,
                payload={
                    'connection_id': 'conn-safe',
                    'provider': 'email' if event_type == 'email.received' else 'salesforce',
                    'provider_event_id': 'customer-account-123',
                    'event_type': (
                        'message.received' if event_type == 'email.received' else 'contact.updated'
                    ),
                    'data': {
                        'customer_email': 'never-expose@example.test',
                        'body': 'private customer content',
                    },
                },
            ),
        ],
        session_id='ses-audit',
    )

    entry = audit.entries[0]
    assert entry.action == 'connection.event_received'
    assert entry.resource == 'connection:conn-safe'
    assert entry.details == {
        'connection_id': 'conn-safe',
        'event_type': ('message.received' if event_type == 'email.received' else 'contact.updated'),
        'provider': 'email' if event_type == 'email.received' else 'salesforce',
    }
    rendered = audit.model_dump_json()
    assert 'customer-account-123' not in rendered
    assert 'never-expose@example.test' not in rendered
    assert 'private customer content' not in rendered
