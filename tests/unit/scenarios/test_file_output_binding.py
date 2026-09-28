# pyright: strict
"""Scenario file-output binding contract tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PydanticValidationError

from maivn_contracts import scenarios
from maivn_contracts.scenarios import (
    FileOutputBinding,
    Scenario,
    load_scenario_schema,
    validate_scenario,
)

_FIXTURES = Path(__file__).resolve().parents[2] / 'fixtures'
_IDEMPOTENCY_TEMPLATE = '{scenario_revision}:{invocation_id}:{artifact_id}:{destination_revision}'


def _scenario() -> dict[str, Any]:
    loaded = json.loads((_FIXTURES / 'valid_scenarios.json').read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    fixture = cast('dict[str, Any]', loaded[0])
    return deepcopy(fixture)


def _policy() -> dict[str, object]:
    return {
        'max_size_bytes': 10_485_760,
        'authorization_ttl_seconds': 900,
        'max_attempts': 3,
        'initial_retry_delay_seconds': 5,
    }


def _file_binding(
    *,
    selector_type: str = 'logical_output',
    required_kind: str = 'document',
    allowed_mime_types: list[object] | None = None,
    delivery: tuple[str, str, object] = ('ordinary', 'attachment', False),
) -> dict[str, object]:
    required_custody, mode, private_export_authorization_required = delivery
    selector: dict[str, object]
    if selector_type == 'logical_output':
        selector = {
            'selector_type': 'logical_output',
            'logical_output_name': 'case_brief',
        }
    else:
        selector = {
            'selector_type': 'explicit_selection',
            'selection_rule_ref': 'final_customer_artifact',
        }
    return {
        'kind': 'file',
        'selector': selector,
        'required_kind': required_kind,
        'allowed_mime_types': (
            ['application/pdf'] if allowed_mime_types is None else allowed_mime_types
        ),
        'required_custody': required_custody,
        'destination_connection_ref': 'connection-support-export',
        'mode': mode,
        'delivery_policy': _policy(),
        'private_export_authorization_required': private_export_authorization_required,
        'idempotency_key_template': _IDEMPOTENCY_TEMPLATE,
    }


def _parse(binding: dict[str, object]) -> Scenario:
    payload = _scenario()
    payload['output_binding'] = binding
    return validate_scenario(payload)


def _assert_rejected(binding: dict[str, object]) -> None:
    payload = _scenario()
    payload['output_binding'] = binding
    with pytest.raises(ValidationError):
        validate_scenario(payload)
    with pytest.raises(PydanticValidationError):
        Scenario.model_validate(payload)


@pytest.mark.parametrize(
    ('selector_type', 'selector_field'),
    [
        ('logical_output', 'logical_output_name'),
        ('explicit_selection', 'selection_rule_ref'),
    ],
)
def test_file_output_binding_accepts_both_closed_selectors(
    selector_type: str,
    selector_field: str,
) -> None:
    """A missing selector variant would prevent authors from naming the output policy."""
    binding = _file_binding(selector_type=selector_type)

    parsed = _parse(binding)

    assert isinstance(parsed.output_binding, FileOutputBinding)
    assert parsed.output_binding.model_dump(mode='json') == binding
    selector = parsed.output_binding.selector
    assert set(type(selector).model_fields) == {'selector_type', selector_field}


@pytest.mark.parametrize(
    ('required_custody', 'mode', 'authorization_required'),
    [
        ('ordinary', 'attachment', False),
        ('ordinary', 'authenticated_reference', False),
        ('vault_private', 'vault_retrieval', False),
        ('vault_private', 'attachment', True),
        ('vault_private', 'authenticated_reference', True),
    ],
)
def test_file_output_binding_accepts_every_authorized_custody_delivery_branch(
    required_custody: str,
    mode: str,
    authorization_required: object,
) -> None:
    """Removing an approved custody branch would reject a safe authored delivery policy."""
    binding = _file_binding(
        delivery=(required_custody, mode, authorization_required),
    )

    assert _parse(binding).output_binding.model_dump(mode='json') == binding


@pytest.mark.parametrize(
    ('required_custody', 'mode', 'authorization_required'),
    [
        ('ordinary', 'vault_retrieval', False),
        ('ordinary', 'attachment', True),
        ('ordinary', 'authenticated_reference', True),
        ('vault_private', 'vault_retrieval', True),
        ('vault_private', 'attachment', False),
        ('vault_private', 'authenticated_reference', False),
    ],
)
def test_file_output_binding_rejects_unsafe_custody_delivery_combinations(
    required_custody: str,
    mode: str,
    authorization_required: object,
) -> None:
    """Weakening custody rules could export private artifacts without independent authorization."""
    _assert_rejected(
        _file_binding(
            delivery=(required_custody, mode, authorization_required),
        )
    )


@pytest.mark.parametrize(
    ('required_kind', 'allowed_mime_types'),
    [
        (
            'document',
            [
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ],
        ),
        (
            'spreadsheet',
            ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
        ),
        ('image', ['image/png', 'image/jpeg']),
        ('audio', ['audio/mpeg', 'audio/wav']),
        ('other', ['application/octet-stream']),
    ],
)
def test_file_output_binding_accepts_only_kind_matching_canonical_mime_types(
    required_kind: str,
    allowed_mime_types: list[object],
) -> None:
    """Changing the canonical MIME matrix would admit a renderer-incompatible artifact."""
    binding = _file_binding(
        required_kind=required_kind,
        allowed_mime_types=allowed_mime_types,
    )

    parsed = _parse(binding)

    assert parsed.output_binding.model_dump(mode='json') == binding


@pytest.mark.parametrize(
    ('required_kind', 'allowed_mime_types'),
    [
        ('document', ['image/png']),
        ('spreadsheet', ['application/pdf']),
        ('image', ['audio/mpeg']),
        ('audio', ['application/octet-stream']),
        ('other', ['image/jpeg']),
        ('document', ['application/zip']),
        ('document', []),
        ('document', ['application/pdf', 'application/pdf']),
        ('document', ['application/pdf'] * 9),
    ],
)
def test_file_output_binding_rejects_mismatched_unknown_empty_or_duplicate_mime_lists(
    required_kind: str,
    allowed_mime_types: list[object],
) -> None:
    """Weakening MIME bounds or agreement would make artifact selection ambiguous."""
    _assert_rejected(
        _file_binding(
            required_kind=required_kind,
            allowed_mime_types=allowed_mime_types,
        )
    )


@pytest.mark.parametrize(
    ('field', 'invalid_value'),
    [
        ('max_size_bytes', 0),
        ('max_size_bytes', 1_073_741_825),
        ('max_size_bytes', True),
        ('authorization_ttl_seconds', 59),
        ('authorization_ttl_seconds', 3601),
        ('authorization_ttl_seconds', True),
        ('max_attempts', 0),
        ('max_attempts', 11),
        ('max_attempts', True),
        ('initial_retry_delay_seconds', 0),
        ('initial_retry_delay_seconds', 3601),
        ('initial_retry_delay_seconds', True),
    ],
)
def test_file_delivery_policy_rejects_non_strict_or_out_of_range_integers(
    field: str,
    invalid_value: object,
) -> None:
    """Weakening a bounded policy integer could create unbounded delivery work."""
    binding = _file_binding()
    policy = cast('dict[str, object]', binding['delivery_policy'])
    policy[field] = invalid_value

    _assert_rejected(binding)


@pytest.mark.parametrize('invalid_flag', [0, 1, 'false', None])
def test_file_output_binding_requires_a_strict_private_export_boolean(
    invalid_flag: object,
) -> None:
    """Boolean coercion could silently authorize or suppress a private export gate."""
    _assert_rejected(_file_binding(delivery=('ordinary', 'attachment', invalid_flag)))


@pytest.mark.parametrize(
    'selector',
    [
        {'selector_type': 'logical_output'},
        {
            'selector_type': 'logical_output',
            'logical_output_name': 'case_brief',
            'selection_rule_ref': 'final',
        },
        {
            'selector_type': 'explicit_selection',
            'selection_rule_ref': 'final',
            'artifact_id': 'artifact-selected-at-runtime',
        },
        {
            'selector_type': 'explicit_selection',
            'selection_rule_ref': 'final',
            'revision': 2,
        },
        {'selector_type': 'logical_output', 'logical_output_name': 'https://example.com'},
        {'selector_type': 'unknown', 'logical_output_name': 'case_brief'},
    ],
)
def test_file_output_binding_rejects_ambiguous_or_runtime_selected_selectors(
    selector: dict[str, object],
) -> None:
    """Authored scenarios must not freeze invocation-selected artifact identity."""
    binding = _file_binding()
    binding['selector'] = selector

    _assert_rejected(binding)


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('artifact_id', 'artifact-runtime-001'),
        ('revision', 1),
        ('url', 'https://example.com/file'),
        ('path', '/private/file.pdf'),
        ('provider_config', {'provider': 'external'}),
        ('storage_ref', {'bucket': 'private'}),
        ('capability', 'download-token'),
        ('grant', 'vault-grant'),
    ],
)
def test_file_output_binding_rejects_runtime_identity_and_destination_capabilities(
    field: str,
    value: object,
) -> None:
    """Adding storage or capability fields would turn authored policy into a bearer grant."""
    binding = _file_binding()
    binding[field] = value

    _assert_rejected(binding)


def test_file_output_binding_requires_opaque_destination_and_exact_idempotency_template() -> None:
    """A raw destination or mutable template would bypass deterministic outbox routing."""
    raw_destination = _file_binding()
    raw_destination['destination_connection_ref'] = 'https://example.com/upload'
    _assert_rejected(raw_destination)

    wrong_template = _file_binding()
    wrong_template['idempotency_key_template'] = '{invocation_id}:{artifact_id}'
    _assert_rejected(wrong_template)


def test_file_output_binding_models_and_schema_have_the_exact_field_inventory() -> None:
    """Adding optional fields would expand the authored boundary without a contract decision."""
    binding = _file_binding(selector_type='explicit_selection')
    parsed = _parse(binding)
    assert isinstance(parsed.output_binding, FileOutputBinding)
    file_output = parsed.output_binding
    schema = load_scenario_schema()

    expected_binding_fields = {
        'kind',
        'selector',
        'required_kind',
        'allowed_mime_types',
        'required_custody',
        'destination_connection_ref',
        'mode',
        'delivery_policy',
        'private_export_authorization_required',
        'idempotency_key_template',
    }
    expected_policy_fields = {
        'max_size_bytes',
        'authorization_ttl_seconds',
        'max_attempts',
        'initial_retry_delay_seconds',
    }
    assert set(type(file_output).model_fields) == expected_binding_fields
    assert set(type(file_output.delivery_policy).model_fields) == expected_policy_fields
    assert set(schema['$defs']['fileOutput']['properties']) == expected_binding_fields
    assert set(schema['$defs']['fileOutput']['required']) == expected_binding_fields
    assert set(schema['$defs']['fileDeliveryPolicy']['properties']) == expected_policy_fields
    assert set(schema['$defs']['fileDeliveryPolicy']['required']) == expected_policy_fields


def test_file_output_binding_uses_external_artifact_authorities_without_mutating_schema() -> None:
    """Duplicating artifact enums or mutating the loaded schema would create contract drift."""
    schema = load_scenario_schema()
    before = deepcopy(schema)
    file_output = schema['$defs']['fileOutput']

    assert file_output['properties']['required_kind']['$ref'] == (
        'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json#/$defs/artifactKind'
    )
    assert file_output['properties']['allowed_mime_types']['items']['$ref'] == (
        'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json#/$defs/mimeType'
    )
    _parse(_file_binding())
    assert schema == before


def test_file_output_binding_sequences_and_nested_policy_are_immutable() -> None:
    """Post-validation mutation must not bypass MIME bounds or delivery policy checks."""
    parsed = _parse(_file_binding())
    assert isinstance(parsed.output_binding, FileOutputBinding)
    file_output = parsed.output_binding

    assert isinstance(file_output.allowed_mime_types, tuple)
    with pytest.raises(AttributeError):
        cast('Any', file_output.allowed_mime_types).append('image/png')
    with pytest.raises(PydanticValidationError):
        file_output.delivery_policy.max_attempts = 11


def test_file_output_binding_public_models_are_exported() -> None:
    """Missing named exports would force consumers to depend on private union internals."""
    expected = {
        'ExplicitSelectionFileSelector',
        'FileDeliveryPolicy',
        'FileOutputBinding',
        'FileOutputSelector',
        'LogicalOutputFileSelector',
    }

    assert expected <= set(scenarios.__all__)
    for name in expected:
        assert hasattr(scenarios, name)
