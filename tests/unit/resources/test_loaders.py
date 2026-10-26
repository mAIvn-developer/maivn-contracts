# pyright: strict
"""Unit tests for resource contract loaders, validation, and tier resolution."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from maivn_contracts.resources import (
    DerivedArtifact,
    ResourceTierDowngradeError,
    ResourceTierResolutionError,
    UnknownResourceTierError,
    load_derived_artifact_schema,
    load_processing_state_schema,
    load_resource_policy_schema,
    resolve_tier,
    validate_derived_artifact,
    validate_processing_state,
    validate_resource_policy,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ARTIFACT_BODY_VARIANT_COUNT = 2
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def _dump_like_fixture(model: BaseModel, fixture: dict[str, Any]) -> dict[str, Any]:
    dumped = model.model_dump(mode='json', exclude_none=True)
    return _restore_explicit_nulls(dumped, fixture)


def _restore_explicit_nulls(dumped: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    for key, value in fixture.items():
        if value is None:
            dumped[key] = None
        elif isinstance(value, dict) and isinstance(dumped.get(key), dict):
            nested_dump: dict[str, Any] = cast('dict[str, Any]', dumped[key])
            nested_fixture: dict[str, Any] = cast('dict[str, Any]', value)
            dumped[key] = _restore_explicit_nulls(nested_dump, nested_fixture)
        elif isinstance(value, list) and isinstance(dumped.get(key), list):
            nested_dump_list: list[Any] = cast('list[Any]', dumped[key])
            nested_fixture_list: list[Any] = cast('list[Any]', value)
            dumped[key] = _restore_explicit_nulls_in_list(
                nested_dump_list,
                nested_fixture_list,
            )
    return dumped


def _restore_explicit_nulls_in_list(dumped: list[Any], fixture: list[Any]) -> list[Any]:
    restored: list[Any] = []
    for dumped_item, fixture_item in zip(dumped, fixture, strict=True):
        if isinstance(dumped_item, dict) and isinstance(fixture_item, dict):
            restored.append(
                _restore_explicit_nulls(
                    cast('dict[str, Any]', dumped_item),
                    cast('dict[str, Any]', fixture_item),
                ),
            )
        else:
            restored.append(dumped_item)
    return restored


def _schema_property_names(schema_fragment: object) -> set[str]:
    property_names: set[str] = set()

    if isinstance(schema_fragment, dict):
        schema_mapping: dict[str, object] = cast('dict[str, object]', schema_fragment)
        properties = schema_mapping.get('properties')
        if isinstance(properties, dict):
            property_map: dict[str, object] = cast('dict[str, object]', properties)
            property_names.update(property_map)
        for value in schema_mapping.values():
            property_names.update(_schema_property_names(value))
    elif isinstance(schema_fragment, list):
        schema_items: list[object] = cast('list[object]', schema_fragment)
        for value in schema_items:
            property_names.update(_schema_property_names(value))

    return property_names


def test_load_resource_policy_schema_exposes_intent_only_fields() -> None:
    """Expose only the intent-level ResourcePolicy fields."""
    schema = load_resource_policy_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {'resource', 'tier', 'persist'}
    assert set(schema['required']) == {'resource', 'tier', 'persist'}
    property_names = _schema_property_names(schema)
    assert 'ocr_engine' not in property_names
    assert 'chunking' not in property_names
    assert 'cache_control' not in property_names


def test_load_processing_state_schema_exposes_fail_closed_statuses() -> None:
    """Expose the processing lifecycle including terminal fail-closed statuses."""
    schema = load_processing_state_schema()

    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'resource_id',
        'tier',
        'status',
        'processed_at',
        'attempt',
        'error',
        'version_stamps',
    }
    assert set(schema['properties']['status']['enum']) == {
        'pending',
        'processing',
        'ready',
        'failed',
        'quarantined',
        'redaction_failed',
    }


def test_load_derived_artifact_schema_exposes_storage_or_inline_body() -> None:
    """Expose exactly one artifact body source plus version stamps."""
    schema = load_derived_artifact_schema()

    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'artifact_id',
        'resource_id',
        'kind',
        'storage_ref',
        'inline_text',
        'content_hash',
        'conversion_method',
        'ocr_confidence',
        'version',
        'supersedes_artifact_id',
        'version_stamps',
        'created_at',
    }
    assert len(schema['oneOf']) == ARTIFACT_BODY_VARIANT_COUNT


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('valid_resource_policies.json', validate_resource_policy),
        ('valid_processing_states.json', validate_processing_state),
        ('valid_derived_artifacts.json', validate_derived_artifact),
    ],
)
def test_validators_accept_valid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Accept every valid resource-contract fixture."""
    for fixture in _load_fixture(fixture_name):
        validated = validator(fixture)
        assert _dump_like_fixture(validated, fixture) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('invalid_resource_policies.json', validate_resource_policy),
        ('invalid_processing_states.json', validate_processing_state),
        ('invalid_derived_artifacts.json', validate_derived_artifact),
    ],
)
def test_validators_reject_invalid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Reject every invalid resource-contract fixture at the schema boundary."""
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)


@pytest.mark.parametrize(
    ('message_has_redaction', 'policy_tier', 'expected'),
    [
        (False, None, 'direct'),
        (False, 'direct', 'direct'),
        (False, 'indexed', 'indexed'),
        (False, 'secure', 'secure'),
        (True, None, 'secure'),
        (True, 'secure', 'secure'),
    ],
)
def test_resolve_tier_accepts_all_valid_tier_paths(
    message_has_redaction: bool,  # noqa: FBT001
    policy_tier: str | None,
    expected: str,
) -> None:
    """Resolve every allowed message/policy tier combination."""
    assert resolve_tier(message_has_redaction, policy_tier) == expected


@pytest.mark.parametrize('policy_tier', ['direct', 'indexed'])
def test_resolve_tier_rejects_redacted_message_downgrades(policy_tier: str) -> None:
    """Reject explicit lower tiers on redacted messages."""
    with pytest.raises(ResourceTierDowngradeError, match='secure floor'):
        resolve_tier(message_has_redaction=True, policy_tier=policy_tier)


@pytest.mark.parametrize('message_has_redaction', [True, False])
def test_resolve_tier_refuses_unknown_tiers_before_any_floor(
    message_has_redaction: bool,  # noqa: FBT001
) -> None:
    """An unknown tier is refused as unknown, redaction or not."""
    with pytest.raises(UnknownResourceTierError, match="Unknown resource tier: 'Secure'") as caught:
        resolve_tier(message_has_redaction, 'Secure')
    assert isinstance(caught.value, ResourceTierResolutionError)


@pytest.mark.parametrize(
    'bodies',
    [{}, {'inline_text': '# Policy', 'storage_ref': {'bucket': 'b', 'path': 'p.md'}}],
)
def test_derived_artifact_carries_exactly_one_body(bodies: dict[str, object]) -> None:
    """A derived artifact stores its body in storage or inline, never both or neither."""
    fixture = _load_fixture('valid_derived_artifacts.json')[0]
    payload = {
        key: value for key, value in fixture.items() if key not in {'storage_ref', 'inline_text'}
    }
    with pytest.raises(PydanticValidationError, match='exactly one of storage_ref or inline_text'):
        DerivedArtifact.model_validate({**payload, **bodies})
