"""Resource-processing contract loaders, validators, models, and rules.

This module owns the public Python interface for `libraries/maivn-contracts/resources`.
It depends only on checked-in JSON contract files, the public Message attachment
contract, Pydantic, and jsonschema. It does not import any mAIvn runtime module.
"""

from __future__ import annotations

from maivn_contracts.resources.loaders import (
    load_derived_artifact_schema,
    load_processing_state_schema,
    load_resource_policy_schema,
    validate_derived_artifact,
    validate_processing_state,
    validate_resource_policy,
)
from maivn_contracts.resources.locking import resource_mutation_lock_key
from maivn_contracts.resources.model import (
    ArtifactKind,
    ArtifactStorageRef,
    DerivedArtifact,
    ProcessingState,
    ProcessingStatus,
    ResourcePolicy,
    ResourceTier,
    ResourceTierDowngradeError,
    ResourceTierResolutionError,
    UnknownResourceTierError,
    VersionStamps,
    resolve_tier,
)

__all__ = [
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
    'resolve_tier',
    'resource_mutation_lock_key',
    'validate_derived_artifact',
    'validate_processing_state',
    'validate_resource_policy',
]
