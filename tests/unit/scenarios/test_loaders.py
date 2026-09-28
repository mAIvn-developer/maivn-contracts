# pyright: strict
"""Unit tests for scenario and trigger contract loaders and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.scenarios import (
    load_scenario_schema,
    load_trigger_fire_schema,
    load_trigger_invocation_schema,
    load_trigger_schema,
    validate_scenario,
    validate_trigger,
    validate_trigger_fire,
    validate_trigger_invocation,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
CONCURRENCY_DEFAULT = 4
DEDUPE_WINDOW_SECONDS_DEFAULT = 86400
DEPTH_CAP_DEFAULT = 8
FANOUT_CAP_DEFAULT = 100
FIRE_BUDGET_DEFAULT = 5
LAYOUT_NODE_POSITIONS_CAP = 64
CONNECTION_ID_MAX_LENGTH = 200
EMAIL_SENDER_ALLOWLIST_MAX_LENGTH = 64
EMAIL_ADDRESS_MAX_LENGTH = 254
MAX_SLA_DEADLINE_SECONDS = 31536000
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]
SCENARIO_NOTES_MAX_LENGTH = 12000


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_validate_scenario_accepts_bounded_notes_and_rejects_invalid_notes() -> None:
    """Scenario Notes are optional, nonblank, and bounded in the canonical contract."""
    payload = _load_fixture('valid_scenarios.json')[0]
    payload['notes'] = 'Route escalations to the support lead.\n\nKeep customer context concise.'

    validated = validate_scenario(payload)

    assert validated.notes == payload['notes']
    assert validate_scenario({**payload, 'notes': None}).notes is None
    for invalid_notes in ('   \n\t', 'x' * (SCENARIO_NOTES_MAX_LENGTH + 1)):
        invalid = {**payload, 'notes': invalid_notes}
        with pytest.raises(ValidationError):
            validate_scenario(invalid)


def test_validate_scenario_accepts_a_closed_optional_flow_graph() -> None:
    """Carry canonical Flow topology while preserving graph-less legacy records."""
    scenario = _load_fixture('valid_scenarios.json')[0]
    flow_graph = _load_fixture('valid_flow_graphs.json')[0]

    validated = validate_scenario({**scenario, 'flow_graph': flow_graph})

    assert validated.flow_graph is not None
    assert validated.flow_graph.schema_version == 1
    assert validate_scenario(scenario).flow_graph is None


def test_validate_scenario_rejects_a_malformed_present_flow_graph() -> None:
    """Never replace corrupt canonical topology with a guessed legacy graph."""
    scenario = _load_fixture('valid_scenarios.json')[0]
    invalid_graph = _load_fixture('invalid_flow_graphs.json')[0]

    with pytest.raises(ValidationError):
        validate_scenario({**scenario, 'flow_graph': invalid_graph})


def test_load_trigger_schema_exposes_implemented_sources_and_guard_defaults() -> None:
    """Expose implemented source variants, reserved kind names, and guard defaults."""
    schema = load_trigger_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'trigger_id',
        'project_id',
        'name',
        'status',
        'source',
        'filter',
        'binding',
        'agent',
        'options',
        'scenario_id',
        'created_at',
        'updated_at',
    }
    assert {entry['$ref'] for entry in schema['$defs']['triggerSource']['oneOf']} == {
        '#/$defs/scheduleSource',
        '#/$defs/webhookSource',
        '#/$defs/manualSource',
        '#/$defs/chainedEventSource',
        '#/$defs/externalConnectionEventSource',
        '#/$defs/emailToInvokeSource',
        '#/$defs/slaTimerSource',
        '#/$defs/memoryEventSource',
        '#/$defs/storageEventSource',
        '#/$defs/replyConversationSource',
        '#/$defs/fireTriggerToolSource',
    }
    assert set(schema['$defs']['sourceKind']['enum']) == {
        'schedule',
        'webhook',
        'manual',
        'external_connection_event',
        'email_to_invoke',
        'memory_event',
        'storage_event',
        'chained_event',
        'sla_timer',
        'reply_conversation',
        'fire_trigger_tool',
    }
    assert (
        schema['$defs']['triggerOptions']['properties']['concurrency']['default']
        == CONCURRENCY_DEFAULT
    )
    dedupe_window = schema['$defs']['triggerOptions']['properties']['dedupe_window_seconds']
    assert dedupe_window['default'] == DEDUPE_WINDOW_SECONDS_DEFAULT
    assert (
        schema['$defs']['triggerOptions']['properties']['depth_cap']['default'] == DEPTH_CAP_DEFAULT
    )
    assert (
        schema['$defs']['triggerOptions']['properties']['fanout_cap']['default']
        == FANOUT_CAP_DEFAULT
    )
    assert (
        schema['$defs']['triggerOptions']['properties']['fire_budget']['default']
        == FIRE_BUDGET_DEFAULT
    )
    chained = schema['$defs']['chainedEventSource']
    assert chained['required'] == ['kind', 'phase', 'event_type']
    assert chained['properties']['event_type']['enum'] == [
        'session.completed',
        'tool.dispatch_completed',
    ]


def test_load_trigger_schema_exposes_connection_and_data_event_sources() -> None:
    """Expose connection, email, memory, storage, tool, and reply source contracts."""
    schema = load_trigger_schema()

    connection = schema['$defs']['externalConnectionEventSource']
    assert connection['required'] == [
        'kind',
        'phase',
        'connection_id',
        'event_type',
    ]
    assert connection['properties']['kind']['const'] == 'external_connection_event'
    assert connection['properties']['phase']['const'] == 'phase_2'
    assert connection['properties']['connection_id']['maxLength'] == CONNECTION_ID_MAX_LENGTH
    assert (
        connection['properties']['connection_id']['pattern']
        == '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
    )
    assert connection['properties']['event_type']['pattern'] == '^[a-z][a-z0-9_.-]{0,127}$'
    email = schema['$defs']['emailToInvokeSource']
    assert email['additionalProperties'] is False
    assert email['required'] == ['kind', 'phase', 'connection_id', 'sender_allowlist']
    assert email['properties']['kind']['const'] == 'email_to_invoke'
    assert email['properties']['phase']['const'] == 'phase_2'
    assert email['properties']['connection_id']['maxLength'] == CONNECTION_ID_MAX_LENGTH
    assert email['properties']['connection_id']['pattern'] == '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
    sender_allowlist = email['properties']['sender_allowlist']
    assert sender_allowlist['minItems'] == 1
    assert sender_allowlist['maxItems'] == EMAIL_SENDER_ALLOWLIST_MAX_LENGTH
    assert sender_allowlist['uniqueItems'] is True
    assert sender_allowlist['items']['maxLength'] == EMAIL_ADDRESS_MAX_LENGTH
    assert sender_allowlist['items']['pattern'].startswith('^(?:')
    memory = schema['$defs']['memoryEventSource']
    assert memory['required'] == ['kind', 'phase', 'record_kind', 'operation']
    assert memory['properties']['record_kind']['enum'] == [
        'skill',
        'insight',
        'resource_pointer',
        'thread_message',
    ]
    assert memory['properties']['operation']['enum'] == ['inserted', 'updated']
    storage = schema['$defs']['storageEventSource']
    assert storage['required'] == [
        'kind',
        'phase',
        'bucket',
        'object_kind',
        'operation',
    ]
    assert storage['properties']['bucket']['const'] == 'memory-resources'
    assert storage['properties']['object_kind']['enum'] == ['source', 'artifact']
    assert storage['properties']['operation']['enum'] == ['inserted', 'updated']
    fire_trigger = schema['$defs']['fireTriggerToolSource']
    assert fire_trigger['additionalProperties'] is False
    assert fire_trigger['required'] == ['kind', 'phase']
    assert fire_trigger['properties']['kind']['const'] == 'fire_trigger_tool'
    assert fire_trigger['properties']['phase']['const'] == 'phase_4'
    reply = schema['$defs']['replyConversationSource']
    assert reply['additionalProperties'] is False
    assert reply['required'] == ['kind', 'phase']
    assert reply['properties']['kind']['const'] == 'reply_conversation'
    assert reply['properties']['phase']['const'] == 'phase_4'


def test_validate_trigger_accepts_exact_reply_conversation_source() -> None:
    """Accept the selector-free project-scoped Phase 4 reply source."""
    trigger = _load_fixture('valid_triggers.json')[0]
    trigger['source'] = {
        'kind': 'reply_conversation',
        'phase': 'phase_4',
    }

    validated = validate_trigger(trigger)

    assert validated.source.model_dump(mode='json') == trigger['source']


@pytest.mark.parametrize(
    'source',
    [
        {'kind': 'reply_conversation', 'phase': 'phase_3'},
        {'kind': 'reply_conversation'},
        {
            'kind': 'reply_conversation',
            'phase': 'phase_4',
            'thread_id': 'caller-selected-thread',
        },
        {
            'kind': 'reply_conversation',
            'phase': 'phase_4',
            'project_id': 'caller-selected-project',
        },
    ],
)
def test_validate_trigger_rejects_malformed_reply_conversation_sources(
    source: dict[str, Any],
) -> None:
    """Reject wrong, incomplete, thread-selecting, and tenant-selecting reply sources."""
    trigger = _load_fixture('valid_triggers.json')[0]
    trigger['source'] = source

    with pytest.raises(ValidationError):
        validate_trigger(trigger)


def test_load_trigger_schema_exposes_strict_sla_timer_source() -> None:
    """Expose the exact Phase 4 named-condition timer policy."""
    sla_timer = load_trigger_schema()['$defs']['slaTimerSource']

    assert sla_timer['additionalProperties'] is False
    assert sla_timer['required'] == [
        'kind',
        'phase',
        'condition',
        'fire_when',
        'deadline_seconds',
    ]
    assert sla_timer['properties']['kind']['const'] == 'sla_timer'
    assert sla_timer['properties']['phase']['const'] == 'phase_4'
    assert sla_timer['properties']['condition']['pattern'] == '^[a-z][a-z0-9_.-]{0,127}$'
    assert sla_timer['properties']['fire_when']['enum'] == [
        'condition_met',
        'condition_missing',
    ]
    assert sla_timer['properties']['deadline_seconds']['minimum'] == 1
    assert sla_timer['properties']['deadline_seconds']['maximum'] == MAX_SLA_DEADLINE_SECONDS


@pytest.mark.parametrize(
    'source',
    [
        {
            'kind': 'external_connection_event',
            'phase': 'phase_2',
            'connection_id': 'conn-salesforce-primary',
            'event_type': 'contact.updated',
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
            'connection_id': 'conn-project-dropzone',
            'sender_allowlist': ['alice@example.com', '*@trusted.example'],
        },
    ],
)
def test_validate_trigger_accepts_connected_source_variants(source: dict[str, Any]) -> None:
    """Accept the two exact provider-neutral connected-source variants."""
    trigger = _load_fixture('valid_triggers.json')[0]
    trigger['source'] = source

    validated = validate_trigger(trigger)

    assert validated.source.model_dump(mode='json') == source


@pytest.mark.parametrize(
    'source',
    [
        {
            'kind': 'external_connection_event',
            'phase': 'phase_3',
            'connection_id': 'conn-salesforce-primary',
            'event_type': 'contact.updated',
        },
        {
            'kind': 'external_connection_event',
            'phase': 'phase_2',
            'connection_id': '',
            'event_type': 'contact.updated',
        },
        {
            'kind': 'external_connection_event',
            'phase': 'phase_2',
            'connection_id': '!caller-selected-project',
            'event_type': 'contact.updated',
        },
        {
            'kind': 'external_connection_event',
            'phase': 'phase_2',
            'connection_id': 'conn-salesforce-primary',
            'event_type': 'Contact Updated',
        },
        {
            'kind': 'external_connection_event',
            'phase': 'phase_2',
            'connection_id': 'conn-salesforce-primary',
            'event_type': 'contact.updated',
            'provider': 'salesforce',
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_3',
            'connection_id': 'conn-project-dropzone',
            'sender_allowlist': ['alice@example.com'],
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
            'connection_id': 'c' * 201,
            'sender_allowlist': ['alice@example.com'],
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
            'connection_id': 'conn-project-dropzone',
            'sender_allowlist': ['alice@example.com'],
            'recipient': 'private@example.test',
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
            'connection_id': 'conn-project-dropzone',
            'sender_allowlist': [],
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
            'connection_id': 'conn-project-dropzone',
            'sender_allowlist': ['Alice@Example.com'],
        },
        {
            'kind': 'email_to_invoke',
            'phase': 'phase_2',
            'connection_id': 'conn-project-dropzone',
            'sender_allowlist': ['alice@example.com', 'alice@example.com'],
        },
    ],
)
def test_validate_trigger_rejects_malformed_connected_sources(source: dict[str, Any]) -> None:
    """Reject wrong phases, missing selectors, invalid identifiers, and extra fields."""
    trigger = _load_fixture('valid_triggers.json')[0]
    trigger['source'] = source

    with pytest.raises(ValidationError):
        validate_trigger(trigger)


@pytest.mark.parametrize('fire_when', ['condition_met', 'condition_missing'])
def test_validate_trigger_accepts_sla_timer_source(fire_when: str) -> None:
    """Accept both exact durable SLA condition outcomes."""
    trigger = _load_fixture('valid_triggers.json')[0]
    trigger['source'] = {
        'kind': 'sla_timer',
        'phase': 'phase_4',
        'condition': 'customer_reply',
        'fire_when': fire_when,
        'deadline_seconds': 3600,
    }

    validated = validate_trigger(trigger)

    assert validated.source.model_dump(mode='json') == trigger['source']


@pytest.mark.parametrize(
    'source',
    [
        {
            'kind': 'sla_timer',
            'phase': 'phase_3',
            'condition': 'customer_reply',
            'fire_when': 'condition_missing',
            'deadline_seconds': 3600,
        },
        {
            'kind': 'sla_timer',
            'phase': 'phase_4',
            'condition': 'Customer Reply',
            'fire_when': 'condition_missing',
            'deadline_seconds': 3600,
        },
        {
            'kind': 'sla_timer',
            'phase': 'phase_4',
            'condition': 'customer_reply',
            'fire_when': 'unknown',
            'deadline_seconds': 3600,
        },
        {
            'kind': 'sla_timer',
            'phase': 'phase_4',
            'condition': 'customer_reply',
            'fire_when': 'condition_met',
            'deadline_seconds': 0,
        },
        {
            'kind': 'sla_timer',
            'phase': 'phase_4',
            'condition': 'customer_reply',
            'fire_when': 'condition_met',
            'deadline_seconds': 31536001,
        },
        {
            'kind': 'sla_timer',
            'phase': 'phase_4',
            'condition': 'customer_reply',
            'fire_when': 'condition_met',
            'deadline_seconds': 3600,
            'project_id': 'caller-project',
        },
    ],
)
def test_validate_trigger_rejects_malformed_sla_timer_source(source: dict[str, Any]) -> None:
    """Reject unsafe, ambiguous, out-of-range, and tenant-selecting SLA sources."""
    trigger = _load_fixture('valid_triggers.json')[0]
    trigger['source'] = source

    with pytest.raises(ValidationError):
        validate_trigger(trigger)


def test_load_trigger_fire_schema_exposes_outbox_fields() -> None:
    """Expose the durable trigger outbox row field set."""
    schema = load_trigger_fire_schema()

    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'fire_id',
        'trigger_id',
        'dedupe_key',
        'priority',
        'shadow',
        'status',
        'available_at',
        'attempt',
        'payload',
        'root_event_id',
        'parent_session_id',
        'parent_trigger_id',
        'trigger_chain_depth',
        'conversation',
    }
    assert schema['properties']['priority']['enum'] == ['interactive', 'triggered', 'retry']
    assert schema['properties']['status']['enum'] == [
        'pending',
        'claimed',
        'completed',
        'failed',
        'dead',
    ]
    conversation = schema['$defs']['conversation']
    assert conversation['additionalProperties'] is False
    assert conversation['required'] == ['conversation_id', 'sequence']
    assert conversation['properties']['sequence']['minimum'] == 1


@pytest.mark.parametrize('sequence', [1, 2])
def test_validate_trigger_fire_accepts_strict_conversation_context(sequence: int) -> None:
    """Carry only the database-owned conversation id and positive order."""
    fire = _load_fixture('valid_trigger_fires.json')[0]
    fire['conversation'] = {
        'conversation_id': 'conv-00000000-0000-4000-8000-000000000001',
        'sequence': sequence,
    }

    validated = validate_trigger_fire(fire)

    assert validated.conversation is not None
    assert validated.conversation.sequence == sequence


@pytest.mark.parametrize(
    'conversation',
    [
        {'conversation_id': '', 'sequence': 1},
        {'conversation_id': 'conv-1', 'sequence': 0},
        {'conversation_id': 'conv-1', 'sequence': 1, 'thread_id': 'forged-root'},
    ],
)
def test_validate_trigger_fire_rejects_malformed_conversation_context(
    conversation: dict[str, Any],
) -> None:
    """Reject blank ids, non-positive order, and caller-selected roots."""
    fire = _load_fixture('valid_trigger_fires.json')[0]
    fire['conversation'] = conversation

    with pytest.raises(ValidationError):
        validate_trigger_fire(fire)


def test_load_trigger_invocation_schema_exposes_reserved_outcome() -> None:
    """Expose terminal invocation history fields and the reserved outcome field."""
    schema = load_trigger_invocation_schema()

    assert schema['additionalProperties'] is False
    assert schema['properties']['status']['enum'] == ['completed', 'failed', 'dead']
    assert schema['properties']['outcome']['enum'] == ['success', 'failure', 'escalation', None]
    assert 'future outcome-based pricing' in schema['properties']['outcome']['description']


def test_validate_trigger_invocation_accepts_explicit_null_outcome() -> None:
    """Accept explicit null for the reserved outcome field without pinning roundtrip wire."""
    invocation = {
        'invocation_id': 'inv-support-webhook-0001',
        'fire_id': 'fire-support-webhook-0001',
        'trigger_id': 'trg-support-webhook',
        'session_id': 'ses-support-webhook-0001',
        'status': 'completed',
        'outcome': None,
        'started_at': '2026-07-01T18:15:01Z',
        'finished_at': '2026-07-01T18:15:08Z',
        'root_event_id': 'evt-trigger-root-0001',
        'parent_trigger_id': 'trg-support-webhook',
        'trigger_chain_depth': 1,
    }

    assert validate_trigger_invocation(invocation).outcome is None


def test_load_scenario_schema_exposes_single_trigger_shape() -> None:
    """Expose the single-trigger scenario field set and JSON canonical note."""
    schema = load_scenario_schema()

    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'scenario_id',
        'project_id',
        'name',
        'notes',
        'trigger_id',
        'revision',
        'agent',
        'subworkflow',
        'output_binding',
        'layout',
        'flow_graph',
        'created_at',
        'updated_at',
    }
    assert set(schema['required']) == set(schema['properties']) - {
        'flow_graph',
        'notes',
        'subworkflow',
    }
    assert 'canonical form is JSON' in schema['description']
    assert (
        schema['$defs']['layout']['properties']['node_positions']['maxProperties']
        == LAYOUT_NODE_POSITIONS_CAP
    )


def test_validate_scenario_accepts_an_exact_pinned_subworkflow() -> None:
    """Accept one immutable same-project child selector as authoring metadata."""
    pinned_version = 7
    scenario = _load_fixture('valid_scenarios.json')[0]
    scenario['subworkflow'] = {
        'scenario_id': 'scn-child',
        'version': pinned_version,
    }

    parsed = validate_scenario(scenario)

    assert parsed.subworkflow is not None
    assert parsed.subworkflow.scenario_id == 'scn-child'
    assert parsed.subworkflow.version == pinned_version


@pytest.mark.parametrize(
    'subworkflow',
    [
        {},
        {'scenario_id': '', 'version': 1},
        {'scenario_id': 'scn-child', 'version': 0},
        {'scenario_id': 'scn-child', 'version': 'latest'},
        {'scenario_id': 'scn-child', 'version': 1, 'extra': True},
    ],
)
def test_validate_scenario_rejects_malformed_subworkflow(subworkflow: object) -> None:
    """Reject ambiguous, mutable, and open child selectors."""
    scenario = _load_fixture('valid_scenarios.json')[0]
    scenario['subworkflow'] = subworkflow

    with pytest.raises(ValidationError):
        validate_scenario(scenario)


@pytest.mark.parametrize('revision', [0, -1, True, '1'])
def test_validate_scenario_rejects_invalid_revision(revision: object) -> None:
    """Require a strict positive scenario revision at the canonical boundary."""
    scenario = _load_fixture('valid_scenarios.json')[0]
    scenario['revision'] = revision

    with pytest.raises(ValidationError):
        validate_scenario(scenario)


def test_validate_scenario_requires_revision() -> None:
    """Reject legacy scenario payloads that omit optimistic revision state."""
    scenario = _load_fixture('valid_scenarios.json')[0]
    scenario.pop('revision', None)

    with pytest.raises(ValidationError):
        validate_scenario(scenario)


def test_load_scenario_schema_exposes_every_live_output_binding_kind() -> None:
    """Expose every live output binding kind and its target requirements.

    Discord and GitHub comment joined the family so a trigger fired by a Discord
    or GitHub event has somewhere to put its answer other than the app UI.
    """
    schema = load_scenario_schema()

    assert {entry['$ref'] for entry in schema['$defs']['outputBinding']['oneOf']} == {
        '#/$defs/displayInAppOutput',
        '#/$defs/webhookOutput',
        '#/$defs/slackMessageOutput',
        '#/$defs/emailReplyOutput',
        '#/$defs/databaseRecordOutput',
        '#/$defs/eventEmissionOutput',
        '#/$defs/discordMessageOutput',
        '#/$defs/gitHubCommentOutput',
        '#/$defs/fileOutput',
    }
    assert schema['$defs']['displayInAppOutput']['required'] == ['kind']
    assert 'target' not in schema['$defs']['displayInAppOutput']['properties']
    assert schema['$defs']['webhookOutput']['properties']['target']['required'] == [
        'endpoint_ref',
    ]


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('valid_triggers.json', validate_trigger),
        ('valid_trigger_fires.json', validate_trigger_fire),
        ('valid_trigger_invocations.json', validate_trigger_invocation),
        ('valid_scenarios.json', validate_scenario),
    ],
)
def test_validators_accept_valid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Accept every valid golden scenario fixture."""
    for fixture in _load_fixture(fixture_name):
        assert validator(fixture).model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('invalid_triggers.json', validate_trigger),
        ('invalid_trigger_fires.json', validate_trigger_fire),
        ('invalid_trigger_invocations.json', validate_trigger_invocation),
        ('invalid_scenarios.json', validate_scenario),
    ],
)
def test_validators_reject_invalid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Reject every invalid golden scenario fixture."""
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)
