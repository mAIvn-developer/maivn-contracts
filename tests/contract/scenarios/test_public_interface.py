# pyright: strict
"""Contract tests for the scenarios module public interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, get_args

from maivn_contracts import scenarios
from maivn_contracts.scenarios import (
    OutputBinding,
    Scenario,
    ScenarioSubworkflowBinding,
    Trigger,
    TriggerFire,
    TriggerInvocation,
    load_scenario_schema,
    load_trigger_fire_schema,
    load_trigger_invocation_schema,
    load_trigger_schema,
)

if TYPE_CHECKING:
    from pydantic import BaseModel


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public scenarios module exports."""
    assert set(scenarios.__all__) == {
        'matches_connection_selector',
        'LocalFileConnectionSelector',
        'GitHubConnectionSelector',
        'FormConnectionSelector',
        'FormSubmittedEvent',
        'LocalFileEvent',
        'ConnectionEventSelector',
        'CallableMessageBinding',
        'CanvasLayout',
        'CanvasNodePosition',
        'ChainedEventSource',
        'DatabaseRecordOutputBinding',
        'DisplayInAppOutputBinding',
        'DiscordMessageOutputBinding',
        'DiscordMessageTarget',
        'EmailToInvokeSource',
        'EmailReplyOutputBinding',
        'EventEmissionOutputBinding',
        'ExternalConnectionEventSource',
        'ExplicitSelectionFileSelector',
        'FileDeliveryPolicy',
        'FileOutputBinding',
        'FileOutputSelector',
        'FireTriggerToolSource',
        'GitHubCommentOutputBinding',
        'GitHubCommentTarget',
        'LogicalOutputFileSelector',
        'ManualSource',
        'MemoryEventSource',
        'OutputBinding',
        'OutputConnectionSelector',
        'RetryPolicy',
        'ReplyConversationSource',
        'Scenario',
        'ScenarioAgentBinding',
        'ScenarioSubworkflowBinding',
        'ScheduleSource',
        'SLATimerSource',
        'SlackMessageOutputBinding',
        'StorageEventSource',
        'Trigger',
        'TriggerAgentBinding',
        'TriggerFire',
        'TriggerInvocation',
        # Modes A/B slice 1 (task 107): the internal trigger-launch envelope.
        'TriggerLaunch',
        'TriggerConversationContext',
        'TriggerOptions',
        'TriggerSource',
        'WebhookOutputBinding',
        'WebhookSource',
        'load_scenario_schema',
        'load_trigger_fire_schema',
        'load_trigger_invocation_schema',
        'load_trigger_launch_schema',
        'load_trigger_schema',
        'validate_scenario',
        'validate_trigger',
        'validate_trigger_fire',
        'validate_trigger_invocation',
        'validate_trigger_launch',
    }

    for exported_name in scenarios.__all__:
        assert hasattr(scenarios, exported_name)


def test_trigger_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the Trigger model and JSON Schema field sets aligned."""
    schema = load_trigger_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(Trigger.model_fields)
    required_model_fields = {
        name for name, field in Trigger.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_trigger_fire_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the TriggerFire model and JSON Schema field sets aligned."""
    schema = load_trigger_fire_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(TriggerFire.model_fields)
    required_model_fields = {
        name for name, field in TriggerFire.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_trigger_invocation_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the TriggerInvocation model and JSON Schema field sets aligned."""
    schema = load_trigger_invocation_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(TriggerInvocation.model_fields)
    required_model_fields = {
        name for name, field in TriggerInvocation.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_scenario_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the Scenario model and JSON Schema field sets aligned."""
    schema = load_scenario_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(Scenario.model_fields)
    required_model_fields = {
        name for name, field in Scenario.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_scenario_subworkflow_type_is_public() -> None:
    """Expose the immutable child selector to contract consumers."""
    selector = ScenarioSubworkflowBinding(scenario_id='scn-child', version=2)

    assert selector.model_dump(mode='json') == {
        'scenario_id': 'scn-child',
        'version': 2,
    }


def test_every_output_binding_member_round_trips_its_json_dump() -> None:
    """A union member without a round-trip specimen would leave its wire shape untested."""
    payloads: dict[str, dict[str, object]] = {
        'display_in_app': {'kind': 'display_in_app'},
        'webhook': {
            'kind': 'webhook',
            'target': {'endpoint_ref': 'connection-webhook'},
        },
        'slack_message': {
            'kind': 'slack_message',
            'target': {'channel_ref': 'connection-slack-channel'},
        },
        'email_reply': {
            'kind': 'email_reply',
            'target': {'thread_ref': 'connection-email-thread'},
        },
        'database_record': {
            'kind': 'database_record',
            'target': {'table_ref': 'connection-database-table'},
        },
        'event_emission': {
            'kind': 'event_emission',
            'target': {'event_type': 'summary.completed'},
        },
        'discord_message': {
            'kind': 'discord_message',
            'target': {'channel_ref': 'connection-discord-channel'},
        },
        'github_comment': {
            'kind': 'github_comment',
            'target': {
                'repository_ref': 'connection-github-repository',
                'issue_ref': 'connection-github-issue',
            },
        },
        'file': {
            'kind': 'file',
            'selector': {
                'selector_type': 'logical_output',
                'logical_output_name': 'summary',
            },
            'required_kind': 'document',
            'allowed_mime_types': ['application/pdf'],
            'required_custody': 'ordinary',
            'destination_connection_ref': 'connection-file-destination',
            'mode': 'attachment',
            'delivery_policy': {
                'max_size_bytes': 10_485_760,
                'authorization_ttl_seconds': 900,
                'max_attempts': 3,
                'initial_retry_delay_seconds': 5,
            },
            'private_export_authorization_required': False,
            'idempotency_key_template': (
                '{scenario_revision}:{invocation_id}:{artifact_id}:{destination_revision}'
            ),
        },
    }
    binding_models = cast(
        'tuple[type[BaseModel], ...]',
        get_args(get_args(OutputBinding)[0]),
    )
    models_by_kind = {
        cast('str', get_args(model.model_fields['kind'].annotation)[0]): model
        for model in binding_models
    }

    assert set(models_by_kind) == set(payloads)
    for kind, model in models_by_kind.items():
        binding = model.model_validate(payloads[kind])

        assert model.model_validate(binding.model_dump(mode='json')) == binding


def test_the_json_schema_admits_exactly_the_output_kinds_the_models_do() -> None:
    """Pin the scenario JSON schema's output kinds to the Python union's.

    They are two hand-maintained statements of one contract, and until this test
    nothing connected them. They can disagree silently, and the disagreement is
    not symmetric: the JSON
    schema is what `validate_scenario` enforces and what the TypeScript and Go
    projections are generated from. So a kind added to the Python union alone is
    a binding an app can build, the SDK will happily post, and the schema will
    then reject - while every model test stays green. This asserts the two sets
    are equal so that gap closes at the moment it opens, in either direction.
    """
    binding_models = cast(
        'tuple[type[BaseModel], ...]',
        get_args(get_args(OutputBinding)[0]),
    )
    model_kinds = {
        cast('str', get_args(model.model_fields['kind'].annotation)[0]) for model in binding_models
    }

    definitions = cast('dict[str, Any]', load_scenario_schema()['$defs'])
    members = cast('list[dict[str, str]]', definitions['outputBinding']['oneOf'])
    schema_kinds: set[str] = set()
    for reference in members:
        member = cast('dict[str, Any]', definitions[reference['$ref'].rsplit('/', 1)[-1]])
        schema_kinds.add(cast('str', member['properties']['kind']['const']))

    assert schema_kinds == model_kinds
