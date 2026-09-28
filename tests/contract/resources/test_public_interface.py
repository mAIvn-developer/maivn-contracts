# pyright: strict
"""Contract tests for the resources module public interface."""

from __future__ import annotations

import pytest

from maivn_contracts import resources
from maivn_contracts.resources import (
    ArtifactStorageRef,
    DerivedArtifact,
    ProcessingState,
    ResourcePolicy,
    VersionStamps,
    load_derived_artifact_schema,
    load_processing_state_schema,
    load_resource_policy_schema,
)


def test_public_interface_exports_are_pinned() -> None:
    """Expose the pinned public resources module exports."""
    assert set(resources.__all__) == {
        'ArtifactKind',
        'ArtifactStorageRef',
        'DerivedArtifact',
        'ProcessingState',
        'ProcessingStatus',
        'ResourcePolicy',
        'ResourceTier',
        'ResourceTierDowngradeError',
        'ResourceTierResolutionError',
        'UnknownResourceTierError',
        'VersionStamps',
        'load_derived_artifact_schema',
        'load_processing_state_schema',
        'load_resource_policy_schema',
        'resource_mutation_lock_key',
        'resolve_tier',
        'validate_derived_artifact',
        'validate_processing_state',
        'validate_resource_policy',
    }

    for exported_name in resources.__all__:
        assert hasattr(resources, exported_name)


@pytest.mark.parametrize(
    ('resource_id', 'expected'),
    [
        ('resource-http-1', -2132028717310979540),
        ('resource-contended', -6502609886124362937),
        ('resource-private-933b2b326151bf3d2146af69813ebb5c', -4999675326739373657),
    ],
)
def test_resource_mutation_lock_key_matches_existing_cross_plane_vectors(
    resource_id: str,
    expected: int,
) -> None:
    """Every plane must remain in the existing SHA-256 signed-bigint lock domain."""
    assert resources.resource_mutation_lock_key(resource_id) == expected


def test_resource_policy_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the ResourcePolicy model and JSON Schema field sets aligned."""
    schema = load_resource_policy_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(ResourcePolicy.model_fields)
    required_model_fields = {
        name for name, field in ResourcePolicy.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_processing_state_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the ProcessingState model and JSON Schema field sets aligned."""
    schema = load_processing_state_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(ProcessingState.model_fields)
    required_model_fields = {
        name for name, field in ProcessingState.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_derived_artifact_model_and_json_schema_agree_field_for_field() -> None:
    """Keep the DerivedArtifact model and JSON Schema field sets aligned."""
    schema = load_derived_artifact_schema()

    schema_fields = set(schema['properties'])
    model_fields = set(DerivedArtifact.model_fields)
    required_model_fields = {
        name for name, field in DerivedArtifact.model_fields.items() if field.is_required()
    }

    assert model_fields == schema_fields
    assert required_model_fields == set(schema['required'])


def test_shared_nested_models_and_json_schema_agree_field_for_field() -> None:
    """Keep nested artifact and version models aligned with schema definitions."""
    state_schema = load_processing_state_schema()
    artifact_schema = load_derived_artifact_schema()

    assert set(VersionStamps.model_fields) == set(
        state_schema['$defs']['versionStamps']['properties'],
    )
    assert set(VersionStamps.model_fields) == set(
        artifact_schema['$defs']['versionStamps']['properties'],
    )
    assert set(ArtifactStorageRef.model_fields) == set(
        artifact_schema['$defs']['storageRef']['properties'],
    )
