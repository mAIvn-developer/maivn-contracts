# pyright: strict
"""Contract tests for the runtime module public interface."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

from maivn_contracts import runtime
from maivn_contracts.runtime import (
    CancelCommand,
    Interrupt,
    ResumeCommand,
    RunConfig,
    RunState,
    RuntimeProtocol,
    StartCommand,
    StreamPart,
    load_command_schema,
    load_run_config_schema,
    load_run_state_schema,
    load_stream_part_schema,
)


def _param_names(method: Callable[..., object]) -> list[str]:
    return list(inspect.signature(method).parameters)


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public runtime module exports."""
    assert set(runtime.__all__) == {
        'ExpenseCeilingUsd',
        'CancelCommand',
        'ChildRunKind',
        'Command',
        'Durability',
        'BooleanInterruptResponse',
        'FreeTextInterruptResponse',
        'Interrupt',
        'InterruptKind',
        'InterruptResponse',
        'ModelDirective',
        'MultipleChoiceInterruptResponse',
        'PromptSource',
        'ResumeCommand',
        'RoutingPreference',
        'RunConfig',
        'RunState',
        'RunStatus',
        'SystemModelChoices',
        'RuntimeProtocol',
        'StartCommand',
        'StreamMode',
        'StreamPart',
        'SingleChoiceInterruptResponse',
        'StructuredInterruptResponse',
        # The private-data placeholder syntax is a contract between the brain, which
        # emits the token, and the SDK, which resolves it in the developer's process.
        # It is exported here so neither side can keep a private copy that drifts.
        'PLACEHOLDER_PATTERN',
        'normalize_placeholder_key',
        # The key derivation is the same contract: the server names a caller-supplied
        # value `user_<sanitized name>`, and only the caller's own process can turn
        # that key back into the value it supplied.
        'CALLER_NAMED_KEY_PREFIX',
        'caller_named_key_candidates',
        'sanitize_private_key_name',
        'load_command_schema',
        'load_run_config_schema',
        'load_run_state_schema',
        'load_stream_part_schema',
        'validate_command',
        'validate_run_config',
        'validate_run_state',
        'validate_stream_part',
    }

    for exported_name in runtime.__all__:
        assert hasattr(runtime, exported_name)


def test_run_config_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the RunConfig model and JSON Schema field sets aligned."""
    schema = load_run_config_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(RunConfig.model_fields)
    required_model_fields = {
        name for name, field in RunConfig.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_command_variants_and_json_schema_agree_field_for_field() -> None:
    """Keep Command variants and JSON Schema field sets aligned."""
    schema = load_command_schema()

    assert set(StartCommand.model_fields) == set(
        schema['$defs']['startCommand']['properties'],
    )
    assert set(CancelCommand.model_fields) == set(
        schema['$defs']['cancelCommand']['properties'],
    )
    assert set(ResumeCommand.model_fields) == set(
        schema['$defs']['resumeCommand']['properties'],
    )
    assert set(schema['$defs']['startCommand']['required']) == {'kind', 'messages'}
    assert set(schema['$defs']['resumeCommand']['required']) == {
        'kind',
        'checkpoint_id',
        'value',
    }
    assert set(schema['$defs']['cancelCommand']['required']) == {'kind', 'reason'}


def test_stream_part_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the StreamPart model and JSON Schema field sets aligned."""
    schema = load_stream_part_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(StreamPart.model_fields)
    required_model_fields = {
        name for name, field in StreamPart.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_run_state_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the RunState model and JSON Schema field sets aligned."""
    schema = load_run_state_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(RunState.model_fields)
    required_model_fields = {
        name for name, field in RunState.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_interrupt_additive_fields_and_defaults_are_pinned() -> None:
    """Keep historical interrupts valid while exposing the canonical interrupt plane."""
    historical = Interrupt(
        checkpoint_id='chk-approval-001',
        reason='approval_required',
        payload={'question': 'Send the drafted support reply?'},
    )

    assert historical.kind == 'tool_approval'
    assert historical.prompt_source == 'authored'
    assert historical.question == ''
    assert historical.response_schema == {}
    assert historical.thread_id is None
    assert historical.session_id is None

    schema = load_run_state_schema()['$defs']['interrupt']
    assert set(Interrupt.model_fields) == set(schema['properties'])
    assert set(schema['required']) == {'checkpoint_id', 'reason', 'payload'}


@pytest.mark.parametrize(
    ('payload', 'expected'),
    [
        ({'kind': 'free_text', 'value': 'us-east-1'}, 'us-east-1'),
        ({'kind': 'boolean', 'value': True}, True),
        ({'kind': 'single_choice', 'value': 'us-west-2'}, 'us-west-2'),
        (
            {'kind': 'multiple_choice', 'value': ['us-east-1', 'us-west-2']},
            ['us-east-1', 'us-west-2'],
        ),
        ({'kind': 'structured', 'value': {'region': 'us-east-1'}}, {'region': 'us-east-1'}),
    ],
)
def test_interrupt_response_envelope_is_discriminated_and_typed(
    payload: dict[str, Any],
    expected: object,
) -> None:
    """Reject answers whose value does not match the declared response kind."""
    response_type = cast('Any', getattr(runtime, 'InterruptResponse', None))
    assert response_type is not None
    response = TypeAdapter(response_type).validate_python(payload)

    assert response.value == expected


@pytest.mark.parametrize(
    'payload',
    [
        {'kind': 'boolean', 'value': 'yes'},
        {'kind': 'single_choice', 'value': ['us-east-1']},
        {'kind': 'multiple_choice', 'value': 'us-east-1'},
        {'kind': 'structured', 'value': 'us-east-1'},
    ],
)
def test_interrupt_response_envelope_rejects_mismatched_values(
    payload: dict[str, Any],
) -> None:
    """Reject answers whose value does not match the declared response kind."""
    response_type = cast('Any', getattr(runtime, 'InterruptResponse', None))
    assert response_type is not None

    with pytest.raises(ValidationError):
        TypeAdapter(response_type).validate_python(payload)


def test_runtime_protocol_method_signatures_are_pinned() -> None:
    """Pin the owned runtime protocol method names and parameter surfaces."""
    assert _param_names(RuntimeProtocol.create_thread) == ['self']
    assert _param_names(RuntimeProtocol.get_state) == ['self', 'thread_id']
    assert _param_names(RuntimeProtocol.wait) == ['self', 'command', 'config']
    assert _param_names(RuntimeProtocol.stream) == [
        'self',
        'command',
        'config',
        'stream_modes',
    ]
    assert _param_names(RuntimeProtocol.cancel) == ['self', 'command', 'config']
