# pyright: strict
"""Unit tests for the payload-safe billing projection assembly."""

from __future__ import annotations

from typing import Any

from maivn_contracts.events import Event, assemble_billing


def _event(
    index: int,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> Event:
    return Event.model_validate(
        {
            'event_id': f'evt-billing-{index}',
            'ordinal': f'producer-billing-{index:06d}',
            'type': event_type,
            'session_id': 'ses-billing',
            'root_event_id': 'evt-billing-root',
            'trigger_id': 'trg-billing',
            'trigger_chain_depth': 0,
            'job_depth': 0,
            'job_index': 0,
            'actor': 'agent:billing-test',
            'mode': 'hosted',
            'payload': payload or {},
            'ts': f'2026-07-15T12:00:{index:02d}Z',
        },
    )


def test_billing_assembly_emits_fires_runs_tokens_and_redaction_units() -> None:
    """Billable events retain only quantities and canonical lineage."""
    billing = assemble_billing(
        [
            _event(1, 'trigger.fired', payload={'trigger_id': 'trg-billing'}),
            _event(2, 'assignment_received', payload={'assignment_uuid': 'assign-billing'}),
            _event(
                3,
                'final',
                payload={
                    'message': {'content': 'private response content'},
                    'usage': {
                        'input_tokens': 13,
                        'output_tokens': 7,
                        'cache_read_input_tokens': 5,
                        'cache_creation_input_tokens': 3,
                    },
                },
            ),
            _event(
                4,
                'message_redaction_applied',
                payload={
                    'entity_count': 4,
                    'redaction_count': 3,
                    'original_content': 'alice@example.test',
                },
            ),
        ],
        org_id='org-billing',
        project_id='project-billing',
    )

    assert [
        (entry.unit_kind, entry.quantity, entry.source_event_id) for entry in billing.entries
    ] == [
        ('fires', 1, 'evt-billing-1'),
        ('requests', 1, 'evt-billing-2'),
        ('tokens', 28, 'evt-billing-3'),
        ('redaction', 3, 'evt-billing-4'),
    ]
    assert billing.entries[0].lineage.org_id == 'org-billing'
    assert billing.entries[0].lineage.project_id == 'project-billing'
    assert billing.entries[0].lineage.session_id == 'ses-billing'

    rendered = billing.model_dump_json()
    assert 'private response content' not in rendered
    assert 'alice@example.test' not in rendered
    assert 'original_content' not in rendered


def test_billing_assembly_drops_non_billable_events() -> None:
    """Operational and content-bearing events never become billing entries."""
    billing = assemble_billing(
        [
            _event(4, 'trigger.skipped', payload={'reason_code': 'quota_exceeded'}),
            _event(5, 'model_routing', payload={'model': 'private-model-name'}),
            _event(6, 'status_message_chunk', payload={'content_delta': 'secret'}),
        ],
        org_id='org-billing',
        project_id='project-billing',
    )

    assert billing.entries == []
    assert 'private-model-name' not in billing.model_dump_json()
    assert 'secret' not in billing.model_dump_json()
