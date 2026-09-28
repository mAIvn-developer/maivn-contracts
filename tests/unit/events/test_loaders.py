# pyright: strict
"""Unit tests for canonical event contract loaders and validation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError

from maivn_contracts.events import load_event_schema, validate_event
from maivn_contracts.events import loaders as loaders_module

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'

HOT_READ_EVENT_COUNT = 200
HOT_READ_BUDGET_SECONDS = 2.0


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_validate_event_prepares_the_constant_event_schema_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prepare and metaschema-check the Event contract once, not per validated event.

    The Event schema is a fixed contract file, but preparing it per call also re-ran
    `Draft202012Validator.check_schema`, which dominated every durable-log read: each
    event read back from Postgres cost ~74ms, so a 453-event session trace burned ~33s
    of CPU on the data plane's event loop and starved every other request on it.
    """
    event = _load_fixture('valid_events.json')[0]
    validate_event(event)

    def fail_preparation(_schema: dict[str, Any]) -> dict[str, Any]:
        message = 'the constant Event schema must be prepared once, not per event'
        raise AssertionError(message)

    def fail_metaschema_check(_schema: dict[str, Any]) -> None:
        message = 'the Event schema metaschema check must not run per event'
        raise AssertionError(message)

    monkeypatch.setattr(loaders_module, '_schema_for_validation', fail_preparation)
    monkeypatch.setattr(loaders_module, '_check_event_schema', fail_metaschema_check)

    for _ in range(25):
        validate_event(event)


def test_validate_event_stays_fast_enough_for_durable_log_reads() -> None:
    """Keep whole-session event reads off the pathological per-event schema rebuild."""
    event = _load_fixture('valid_events.json')[0]

    started = time.perf_counter()
    for _ in range(HOT_READ_EVENT_COUNT):
        validate_event(event)
    elapsed = time.perf_counter() - started

    assert elapsed < HOT_READ_BUDGET_SECONDS


def test_load_event_schema_exposes_strict_canonical_event_fields() -> None:
    """Expose the strict canonical Event schema field set."""
    schema = load_event_schema()

    expected_fields = {
        'event_id',
        'ordinal',
        'type',
        'session_id',
        'scenario_id',
        'trigger_id',
        'root_event_id',
        'parent_session_id',
        'parent_trigger_id',
        'trigger_chain_depth',
        'parent_assignment_uuid',
        'job_depth',
        'job_index',
        'actor',
        'mode',
        'correlation_id',
        'trace_id',
        'payload',
        'latency_ms',
        'ts',
    }

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == expected_fields
    for field_name in expected_fields:
        assert schema['properties'][field_name]['description']
    assert 'connection.event_received' in schema['properties']['type']['enum']
    assert 'email.received' in schema['properties']['type']['enum']
    assert 'trigger.fire_requested' in schema['properties']['type']['enum']
    assert 'conversation.reply_received' in schema['properties']['type']['enum']


@pytest.mark.parametrize(
    ('event_type', 'provider', 'source_type'),
    [
        ('connection.event_received', 'salesforce', 'contact.updated'),
        ('email.received', 'email', 'message.received'),
    ],
)
def test_validate_event_accepts_connected_source_receipts(
    event_type: str,
    provider: str,
    source_type: str,
) -> None:
    """Accept canonical normalized connection events without provider credentials."""
    event = {
        'event_id': 'connection-event-00000000-0000-4000-8000-000000000001',
        'ordinal': '1',
        'type': event_type,
        'session_id': 'connection:conn-primary:00000000-0000-4000-8000-000000000001',
        'root_event_id': 'connection-event-00000000-0000-4000-8000-000000000001',
        'trigger_chain_depth': 0,
        'job_depth': 0,
        'job_index': 0,
        'actor': f'integration:{provider}',
        'mode': 'hosted',
        'payload': {
            'connection_id': 'conn-primary',
            'provider': provider,
            'provider_event_id': 'provider-event-1',
            'event_type': source_type,
            'data': {'record_id': 'record-7'},
        },
        'ts': '2026-07-17T12:00:00Z',
    }

    validated = validate_event(event)

    assert validated.type == event_type
    assert validated.model_dump(mode='json', exclude_none=True) == event


def test_validate_event_accepts_fire_trigger_request() -> None:
    """Accept the durable same-project fire-trigger system-tool request."""
    event = {
        'event_id': 'evt-fire-trigger-request-0001',
        'ordinal': 'producer-agent-000001',
        'type': 'trigger.fire_requested',
        'session_id': 'ses-agent-0001',
        'trigger_id': 'trg-parent',
        'root_event_id': 'evt-root-0001',
        'parent_trigger_id': 'trg-upstream',
        'trigger_chain_depth': 2,
        'job_depth': 0,
        'job_index': 0,
        'actor': 'agent:invoke',
        'mode': 'hosted',
        'correlation_id': 'call-fire-trigger-0001',
        'payload': {
            'request_id': 'req-fire-trigger-0001',
            'target_trigger_id': 'trg-follow-up',
            'payload': {'reason': 'customer requested a callback'},
        },
        'ts': '2026-07-17T12:00:00Z',
    }

    validated = validate_event(event)

    assert validated.type == 'trigger.fire_requested'
    assert validated.model_dump(mode='json', exclude_none=True) == event


def test_validate_event_accepts_normalized_conversation_reply() -> None:
    """Accept one content-bearing reply rooted in its database-owned conversation."""
    event = {
        'event_id': 'conversation-reply-00000000-0000-4000-8000-000000000002',
        'ordinal': '2',
        'type': 'conversation.reply_received',
        'session_id': 'conversation:00000000-0000-4000-8000-000000000001',
        'trigger_id': 'trg-conversation-owner',
        'root_event_id': 'conversation-root-00000000-0000-4000-8000-000000000001',
        'trigger_chain_depth': 0,
        'job_depth': 0,
        'job_index': 0,
        'actor': 'integration:conversation',
        'mode': 'hosted',
        'payload': {
            'conversation_id': '00000000-0000-4000-8000-000000000001',
            'reply_id': 'provider-reply-2',
            'sequence': 2,
            'message': {
                'message_id': 'msg-provider-reply-2',
                'role': 'user',
                'content': 'I have one more question.',
                'ts': '2026-07-17T12:00:00Z',
            },
        },
        'ts': '2026-07-17T12:00:00Z',
    }

    validated = validate_event(event)

    assert validated.type == 'conversation.reply_received'
    assert validated.model_dump(mode='json', exclude_none=True) == event


def test_validate_event_accepts_valid_golden_fixtures() -> None:
    """Accept every valid golden event fixture."""
    for event in _load_fixture('valid_events.json'):
        validated = validate_event(event)
        assert validated.event_id == event['event_id']
        assert validated.model_dump(mode='json', exclude_none=True) == event


def test_validate_event_keeps_enrichment_phases_open() -> None:
    """An enrichment phase is payload data, not a new canonical event type."""
    event = _load_fixture('valid_events.json')[0]
    event['type'] = 'enrichment'
    event['payload'] = {'phase': 'plan_warning'}

    validated = validate_event(event)

    assert validated.type == 'enrichment'
    assert validated.payload['phase'] == 'plan_warning'


def test_validate_event_accepts_optional_otel_trace_id() -> None:
    """Accept and round-trip a valid non-zero lowercase OTel trace identifier."""
    event = _load_fixture('valid_events.json')[0]
    event['trace_id'] = '4bf92f3577b34da6a3ce929d0e0e4736'

    validated = validate_event(event)

    assert validated.trace_id == event['trace_id']
    assert validated.model_dump(mode='json', exclude_none=True) == event


def test_validate_event_parent_session_lineage_accepts_null_string_or_legacy_omission() -> None:
    """A wire event may make the root edge explicit without rejecting older omission."""
    base = _load_fixture('valid_events.json')[0]
    explicit_root = {**base, 'parent_session_id': None}
    child = {**base, 'parent_session_id': 'ses-parent'}
    legacy = dict(base)

    assert validate_event(explicit_root).parent_session_id is None
    assert validate_event(child).parent_session_id == 'ses-parent'
    assert validate_event(legacy).parent_session_id is None

    with pytest.raises(ValidationError):
        validate_event({**base, 'parent_session_id': ''})


@pytest.mark.parametrize(
    'trace_id',
    [
        '4BF92F3577B34DA6A3CE929D0E0E4736',
        '4bf92f3577b34da6a3ce929d0e0e473',
        '4bf92f3577b34da6a3ce929d0e0e47360',
        '4bf92f3577b34da6a3ce929d0e0e473g',
        '00000000000000000000000000000000',
    ],
)
def test_validate_event_rejects_invalid_otel_trace_id(trace_id: str) -> None:
    """Reject trace identifiers that W3C/OpenTelemetry cannot correlate."""
    event = _load_fixture('valid_events.json')[0]
    event['trace_id'] = trace_id

    with pytest.raises(ValidationError):
        validate_event(event)


def test_validate_event_rejects_invalid_golden_fixtures() -> None:
    """Reject every invalid golden event fixture."""
    for event in _load_fixture('invalid_events.json'):
        with pytest.raises(ValidationError):
            validate_event(event)
