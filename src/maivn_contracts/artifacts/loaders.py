"""Load and validate the canonical ArtifactRef JSON Schema."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Annotated, Any, Protocol, TypeAlias, TypeVar, cast

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import AfterValidator, TypeAdapter

from maivn_contracts._schema_root import SCHEMA_ROOT
from maivn_contracts.artifacts.lifecycle import (
    ArtifactLifecycleEventPayload,
    parse_artifact_lifecycle_event_payload,
)
from maivn_contracts.artifacts.model import (
    ArtifactError,
    ArtifactPatchContract,
    ArtifactPlanV1,
    ArtifactPlanV2,
    ArtifactRef,
    ArtifactReservation,
    OrdinaryExportDeletionReceipt,
    OrdinaryExportDeletionRequest,
    OrdinaryExportDeletionStatusRequest,
    PrivateArtifactLifecycleReceipt,
    PrivateWorkIntentStatus,
    RedactedArtifactPayload,
    VaultEffectAccepted,
    VaultValueMapHandle,
    VaultWorkRequest,
    VerifiedExportManifest,
    VerifiedExportPublicationOutcome,
    VerifiedExportPublicationRequest,
)
from maivn_contracts.artifacts.plans import ArtifactPlan, ArtifactPlanV3
from maivn_contracts.artifacts.vault_ordinary_export_protocol import (
    VaultOrdinaryExportServiceAssertion,
    VaultOrdinaryExportTrustDocument,
)
from maivn_contracts.artifacts.vault_protocol import VaultIntentStatusRequest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

_CONTRACTS_ROOT = SCHEMA_ROOT / 'artifacts'


class _JsonSchemaValidator(Protocol):
    def validate(self, instance: object) -> None:
        """Validate one JSON-like instance."""


class _ContractObjectTypeError(TypeError):
    def __init__(self, path: Path) -> None:
        super().__init__(f'Contract document must be a JSON object: {path}')


_ARTIFACT_REF_ADAPTER: TypeAdapter[ArtifactRef] = TypeAdapter(ArtifactRef)
_ARTIFACT_RESERVATION_ADAPTER = TypeAdapter(ArtifactReservation)
_PRIVATE_WORK_INTENT_STATUS_ADAPTER = TypeAdapter(PrivateWorkIntentStatus)
_PRIVATE_ARTIFACT_LIFECYCLE_RECEIPT_ADAPTER = TypeAdapter(PrivateArtifactLifecycleReceipt)
_VAULT_WORK_REQUEST_ADAPTER = TypeAdapter(VaultWorkRequest)
_VAULT_EFFECT_ACCEPTED_ADAPTER = TypeAdapter(VaultEffectAccepted)
_VAULT_VALUE_MAP_HANDLE_ADAPTER = TypeAdapter(VaultValueMapHandle)
_VAULT_INTENT_STATUS_REQUEST_ADAPTER = TypeAdapter(VaultIntentStatusRequest)
_VAULT_ORDINARY_EXPORT_SERVICE_ASSERTION_ADAPTER = TypeAdapter(VaultOrdinaryExportServiceAssertion)
_VAULT_ORDINARY_EXPORT_TRUST_DOCUMENT_ADAPTER = TypeAdapter(VaultOrdinaryExportTrustDocument)
_VERIFIED_EXPORT_MANIFEST_ADAPTER = TypeAdapter(VerifiedExportManifest)
_VERIFIED_EXPORT_PUBLICATION_REQUEST_ADAPTER = TypeAdapter(VerifiedExportPublicationRequest)
_VERIFIED_EXPORT_PUBLICATION_OUTCOME_ADAPTER = TypeAdapter(VerifiedExportPublicationOutcome)
_ORDINARY_EXPORT_DELETION_REQUEST_ADAPTER = TypeAdapter(OrdinaryExportDeletionRequest)
_ORDINARY_EXPORT_DELETION_STATUS_REQUEST_ADAPTER = TypeAdapter(OrdinaryExportDeletionStatusRequest)
_ORDINARY_EXPORT_DELETION_RECEIPT_ADAPTER = TypeAdapter(OrdinaryExportDeletionReceipt)
_REDACTED_ARTIFACT_PAYLOAD_ADAPTER = TypeAdapter(RedactedArtifactPayload)
_ARTIFACT_PLAN_V3_ADAPTER: TypeAdapter[ArtifactPlanV3] = TypeAdapter(ArtifactPlanV3)
_CURRENT_ARTIFACT_PLAN: TypeAlias = ArtifactPlanV2 | ArtifactPlanV3


def _require_ordinary_plan(plan: _CURRENT_ARTIFACT_PLAN) -> _CURRENT_ARTIFACT_PLAN:
    if plan.custody_request != 'ordinary':
        raise ValueError
    return plan


_CURRENT_ARTIFACT_PLAN_ADAPTER: TypeAdapter[_CURRENT_ARTIFACT_PLAN] = TypeAdapter(
    Annotated[_CURRENT_ARTIFACT_PLAN, AfterValidator(_require_ordinary_plan)],
)
_LEGACY_ARTIFACT_PLAN_V1_ADAPTER: TypeAdapter[ArtifactPlanV1] = TypeAdapter(ArtifactPlanV1)
_ARTIFACT_PATCH_ADAPTER: TypeAdapter[ArtifactPatchContract] = TypeAdapter(ArtifactPatchContract)
_ARTIFACT_ERROR_ADAPTER = TypeAdapter(ArtifactError)
_ARTIFACT_LIFECYCLE_EVENT_ADAPTER: TypeAdapter[ArtifactLifecycleEventPayload] = TypeAdapter(
    ArtifactLifecycleEventPayload
)
_ContractModel = TypeVar('_ContractModel')


def _load_schema(filename: str) -> dict[str, Any]:
    path = _CONTRACTS_ROOT / filename
    loaded = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(path)
    return cast('dict[str, Any]', loaded)


def _check_against_schema(schema: dict[str, Any], obj: Mapping[str, Any]) -> None:
    check_schema = cast('Callable[[object], None]', Draft202012Validator.check_schema)
    check_schema(schema)
    validator_factory = cast('Callable[..., _JsonSchemaValidator]', Draft202012Validator)
    validator_factory(schema, format_checker=FormatChecker()).validate(obj)


def _validate_schema_and_project(
    schema: dict[str, Any], obj: Mapping[str, Any], adapter: TypeAdapter[_ContractModel]
) -> _ContractModel:
    _check_against_schema(schema, obj)
    return adapter.validate_python(obj)


def load_artifact_ref_schema() -> dict[str, Any]:
    """Load the canonical immutable ArtifactRef schema."""
    return _load_schema('artifact_ref.schema.json')


def validate_artifact_ref(obj: Mapping[str, Any]) -> ArtifactRef:
    """Validate a mapping against schema authority and return its typed projection."""
    return _validate_schema_and_project(load_artifact_ref_schema(), obj, _ARTIFACT_REF_ADAPTER)


def _rewritten_schema(
    value: object,
    source: str,
    *replacements: tuple[str, str],
) -> dict[str, Any]:
    """Rewrite reference strings through the JSON text form of one schema object."""
    serialized = json.dumps(value)
    for old, new in replacements:
        serialized = serialized.replace(old, new)
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise _ContractObjectTypeError(_CONTRACTS_ROOT / source)
    return cast('dict[str, Any]', loaded)


def _inline_defs(schema: dict[str, Any], key: str, filename: str) -> dict[str, Any]:
    """Copy one stored schema's `$defs` under `key` and point its references there."""
    materialized = deepcopy(schema)
    materialized.setdefault('$defs', {})[key] = _rewritten_schema(
        _load_schema(filename)['$defs'],
        filename,
        ('"#/$defs/', f'"#/$defs/{key}/'),
    )
    return _rewritten_schema(
        materialized,
        filename,
        (f'https://schemas.maivn.dev/artifacts/{filename}#/$defs/', f'#/$defs/{key}/'),
    )


def _materialize_artifact_ref(schema: dict[str, Any]) -> dict[str, Any]:
    return _inline_defs(schema, 'artifactRef', 'artifact_ref.schema.json')


def _materialize_redacted_payload(schema: dict[str, Any]) -> dict[str, Any]:
    materialized = deepcopy(schema)
    materialized.setdefault('$defs', {})['redactedPayload'] = _embed_schema(
        load_redacted_artifact_payload_schema(),
        'redactedPayload',
    )
    return _rewritten_schema(
        materialized,
        'redacted_artifact_payload.schema.json',
        (
            'https://schemas.maivn.dev/artifacts/redacted_artifact_payload.schema.json',
            '#/$defs/redactedPayload',
        ),
    )


def _materialize_artifact_plan_defs(schema: dict[str, Any]) -> dict[str, Any]:
    return _inline_defs(schema, 'artifactPlan', 'artifact_plan.schema.json')


def _embed_schema(schema: dict[str, Any], key: str) -> dict[str, Any]:
    embedded = deepcopy(schema)
    embedded.pop('$id', None)
    embedded.pop('$schema', None)
    return _rewritten_schema(
        embedded,
        f'{key}.schema.json',
        ('"#/$defs/', f'"#/$defs/{key}/$defs/'),
    )


def _materialize_verified_export_manifest(schema: dict[str, Any]) -> dict[str, Any]:
    materialized = deepcopy(schema)
    materialized.setdefault('$defs', {})['verifiedExportManifest'] = _embed_schema(
        load_verified_export_manifest_schema(),
        'verifiedExportManifest',
    )
    return _rewritten_schema(
        materialized,
        'verified_export_publication_request.schema.json',
        (
            'https://schemas.maivn.dev/artifacts/verified_export_manifest.schema.json',
            '#/$defs/verifiedExportManifest',
        ),
    )


def _materialize_vault_work_request(schema: dict[str, Any]) -> dict[str, Any]:
    materialized = _materialize_artifact_ref(schema)
    plan = _embed_schema(_materialize_redacted_payload(load_artifact_plan_schema()), 'artifactPlan')
    plan_v3 = _embed_schema(load_artifact_plan_v3_schema(), 'artifactPlanV3')
    patch = _materialize_redacted_payload(load_artifact_patch_schema())
    defs = materialized.setdefault('$defs', {})
    defs['artifactPlan'] = plan
    defs['artifactPlanV3'] = plan_v3
    defs['artifactPatch'] = _embed_schema(patch, 'artifactPatch')
    defs['vaultValueMapHandle'] = _embed_schema(
        load_vault_value_map_handle_schema(),
        'vaultValueMapHandle',
    )
    root = 'https://schemas.maivn.dev/artifacts/'
    return _rewritten_schema(
        materialized,
        'vault_work_request.schema.json',
        (f'{root}artifact_plan.schema.json#/$defs/', '#/$defs/artifactPlan/$defs/'),
        (f'{root}artifact_plan.schema.json', '#/$defs/artifactPlan'),
        (f'{root}artifact_plan_v3.schema.json#/$defs/', '#/$defs/artifactPlanV3/$defs/'),
        (f'{root}artifact_plan_v3.schema.json', '#/$defs/artifactPlanV3'),
        (f'{root}artifact_patch.schema.json#/$defs/', '#/$defs/artifactPatch/$defs/'),
        (f'{root}artifact_patch.schema.json', '#/$defs/artifactPatch'),
        (f'{root}vault_value_map_handle.schema.json', '#/$defs/vaultValueMapHandle'),
    )


def load_artifact_reservation_schema() -> dict[str, Any]:
    """Load the canonical ordinary pre-commit reservation schema."""
    return _load_schema('artifact_reservation.schema.json')


def validate_artifact_reservation(obj: Mapping[str, Any]) -> ArtifactReservation:
    """Validate a reservation against schema authority and return its projection."""
    return _validate_schema_and_project(
        _materialize_artifact_ref(load_artifact_reservation_schema()),
        obj,
        _ARTIFACT_RESERVATION_ADAPTER,
    )


def load_private_work_intent_status_schema() -> dict[str, Any]:
    """Load the canonical private work-intent status schema."""
    return _load_schema('private_work_intent_status.schema.json')


def validate_private_work_intent_status(obj: Mapping[str, Any]) -> PrivateWorkIntentStatus:
    """Validate a private intent status and return its typed projection."""
    return _validate_schema_and_project(
        _materialize_artifact_ref(load_private_work_intent_status_schema()),
        obj,
        _PRIVATE_WORK_INTENT_STATUS_ADAPTER,
    )


def load_vault_work_request_schema() -> dict[str, Any]:
    """Load the canonical redacted private-vault work request schema."""
    return _load_schema('vault_work_request.schema.json')


def load_vault_value_map_handle_schema() -> dict[str, Any]:
    """Load the canonical opaque Vault value-map handle schema."""
    return _load_schema('vault_value_map_handle.schema.json')


def load_vault_effect_accepted_schema() -> dict[str, Any]:
    """Load the canonical value-free queued-effect response schema."""
    return _load_schema('vault_effect_accepted.schema.json')


def load_vault_intent_status_request_schema() -> dict[str, Any]:
    """Load the canonical fixed-path internal Vault status request schema."""
    return _load_schema('vault_intent_status_request.schema.json')


def validate_vault_effect_accepted(obj: Mapping[str, Any]) -> VaultEffectAccepted:
    """Validate a stable value-free queued-effect response."""
    return _validate_schema_and_project(
        load_vault_effect_accepted_schema(), obj, _VAULT_EFFECT_ACCEPTED_ADAPTER
    )


def validate_vault_intent_status_request(
    obj: Mapping[str, Any],
) -> VaultIntentStatusRequest:
    """Validate one closed value-free Vault status request."""
    return _validate_schema_and_project(
        load_vault_intent_status_request_schema(),
        obj,
        _VAULT_INTENT_STATUS_REQUEST_ADAPTER,
    )


def validate_vault_work_request(obj: Mapping[str, Any]) -> VaultWorkRequest:
    """Validate a non-authorizing vault request and return its typed projection."""
    return _validate_schema_and_project(
        _materialize_vault_work_request(load_vault_work_request_schema()),
        obj,
        _VAULT_WORK_REQUEST_ADAPTER,
    )


def validate_vault_value_map_handle(obj: Mapping[str, Any]) -> VaultValueMapHandle:
    """Validate one closed immutable value-map generation handle."""
    return _validate_schema_and_project(
        load_vault_value_map_handle_schema(),
        obj,
        _VAULT_VALUE_MAP_HANDLE_ADAPTER,
    )


def load_vault_ordinary_export_service_assertion_schema() -> dict[str, Any]:
    """Load the canonical Vault ordinary-export service assertion schema."""
    return _load_schema('vault_ordinary_export_service_assertion.schema.json')


def validate_vault_ordinary_export_service_assertion(
    obj: Mapping[str, Any],
) -> VaultOrdinaryExportServiceAssertion:
    """Validate one closed short-lived Vault workload assertion."""
    return _validate_schema_and_project(
        load_vault_ordinary_export_service_assertion_schema(),
        obj,
        _VAULT_ORDINARY_EXPORT_SERVICE_ASSERTION_ADAPTER,
    )


def load_vault_ordinary_export_trust_document_schema() -> dict[str, Any]:
    """Load the canonical mounted Vault workload trust document schema."""
    return _load_schema('vault_ordinary_export_trust_document.schema.json')


def validate_vault_ordinary_export_trust_document(
    obj: Mapping[str, Any],
) -> VaultOrdinaryExportTrustDocument:
    """Validate one closed unique Vault workload trust document."""
    return _validate_schema_and_project(
        load_vault_ordinary_export_trust_document_schema(),
        obj,
        _VAULT_ORDINARY_EXPORT_TRUST_DOCUMENT_ADAPTER,
    )


def load_verified_export_manifest_schema() -> dict[str, Any]:
    """Load the canonical bounded proven-export manifest schema."""
    return _load_schema('verified_export_manifest.schema.json')


def validate_verified_export_manifest(obj: Mapping[str, Any]) -> VerifiedExportManifest:
    """Validate one closed proof output for ordinary publication."""
    return _validate_schema_and_project(
        load_verified_export_manifest_schema(),
        obj,
        _VERIFIED_EXPORT_MANIFEST_ADAPTER,
    )


def load_verified_export_publication_request_schema() -> dict[str, Any]:
    """Load the canonical length-prefixed publication control schema."""
    return _load_schema('verified_export_publication_request.schema.json')


def validate_verified_export_publication_request(
    obj: Mapping[str, Any],
) -> VerifiedExportPublicationRequest:
    """Validate one exact publication operation and nested proven manifest."""
    return _validate_schema_and_project(
        _materialize_verified_export_manifest(load_verified_export_publication_request_schema()),
        obj,
        _VERIFIED_EXPORT_PUBLICATION_REQUEST_ADAPTER,
    )


def load_verified_export_publication_outcome_schema() -> dict[str, Any]:
    """Load the canonical internal ordinary-publication outcome schema."""
    return _load_schema('verified_export_publication_outcome.schema.json')


def validate_verified_export_publication_outcome(
    obj: Mapping[str, Any],
) -> VerifiedExportPublicationOutcome:
    """Validate a public receipt paired with one internal deletion reference."""
    return _validate_schema_and_project(
        _materialize_artifact_ref(load_verified_export_publication_outcome_schema()),
        obj,
        _VERIFIED_EXPORT_PUBLICATION_OUTCOME_ADAPTER,
    )


def load_ordinary_export_deletion_request_schema() -> dict[str, Any]:
    """Load the canonical ordinary-export deletion request schema."""
    return _load_schema('ordinary_export_deletion_request.schema.json')


def validate_ordinary_export_deletion_request(
    obj: Mapping[str, Any],
) -> OrdinaryExportDeletionRequest:
    """Validate an exact deletion reference and immutable manifest pair."""
    return _validate_schema_and_project(
        load_ordinary_export_deletion_request_schema(),
        obj,
        _ORDINARY_EXPORT_DELETION_REQUEST_ADAPTER,
    )


def load_ordinary_export_deletion_status_request_schema() -> dict[str, Any]:
    """Load the canonical ordinary-export deletion status request schema."""
    return _load_schema('ordinary_export_deletion_status_request.schema.json')


def validate_ordinary_export_deletion_status_request(
    obj: Mapping[str, Any],
) -> OrdinaryExportDeletionStatusRequest:
    """Validate one exact deletion reference and receipt pair."""
    return _validate_schema_and_project(
        load_ordinary_export_deletion_status_request_schema(),
        obj,
        _ORDINARY_EXPORT_DELETION_STATUS_REQUEST_ADAPTER,
    )


def load_ordinary_export_deletion_receipt_schema() -> dict[str, Any]:
    """Load the canonical value-free ordinary-export deletion receipt schema."""
    return _load_schema('ordinary_export_deletion_receipt.schema.json')


def validate_ordinary_export_deletion_receipt(
    obj: Mapping[str, Any],
) -> OrdinaryExportDeletionReceipt:
    """Validate one closed pending or terminal ordinary deletion receipt."""
    return _validate_schema_and_project(
        load_ordinary_export_deletion_receipt_schema(),
        obj,
        _ORDINARY_EXPORT_DELETION_RECEIPT_ADAPTER,
    )


def load_private_artifact_lifecycle_receipt_schema() -> dict[str, Any]:
    """Load the canonical value-free private artifact lifecycle receipt schema."""
    return _load_schema('private_artifact_lifecycle_receipt.schema.json')


def validate_private_artifact_lifecycle_receipt(
    obj: Mapping[str, Any],
) -> PrivateArtifactLifecycleReceipt:
    """Validate one private artifact lifecycle receipt and return its projection."""
    return _validate_schema_and_project(
        _materialize_artifact_ref(load_private_artifact_lifecycle_receipt_schema()),
        obj,
        _PRIVATE_ARTIFACT_LIFECYCLE_RECEIPT_ADAPTER,
    )


def load_redacted_artifact_payload_schema() -> dict[str, Any]:
    """Load the dependency-free structural redacted payload schema."""
    return _load_schema('redacted_artifact_payload.schema.json')


def validate_redacted_artifact_payload(obj: Mapping[str, Any]) -> RedactedArtifactPayload:
    """Validate closed fragment structure, not hydrated private values."""
    return _validate_schema_and_project(
        load_redacted_artifact_payload_schema(), obj, _REDACTED_ARTIFACT_PAYLOAD_ADAPTER
    )


def load_artifact_plan_schema() -> dict[str, Any]:
    """Load the canonical discriminated artifact-plan schema."""
    return _load_schema('artifact_plan.schema.json')


def load_artifact_plan_v3_schema() -> dict[str, Any]:
    """Load the canonical stored rich-plan schema."""
    return _load_schema('artifact_plan_v3.schema.json')


def validate_artifact_plan(obj: Mapping[str, Any]) -> ArtifactPlan:
    """Validate a current ordinary artifact plan against wire authority."""
    if obj.get('schema_version') == 'v3':
        return _validate_schema_and_project(
            load_artifact_plan_v3_schema(), obj, _CURRENT_ARTIFACT_PLAN_ADAPTER
        )
    return _validate_schema_and_project(
        _materialize_redacted_payload(load_artifact_plan_schema()),
        obj,
        _CURRENT_ARTIFACT_PLAN_ADAPTER,
    )


def validate_legacy_artifact_plan_v1_for_read_migration(
    obj: Mapping[str, Any],
) -> ArtifactPlanV1:
    """Load a legacy V1 plan only for an explicitly named read-migration path."""
    return _validate_schema_and_project(
        _materialize_redacted_payload(load_artifact_plan_schema()),
        obj,
        _LEGACY_ARTIFACT_PLAN_V1_ADAPTER,
    )


def load_artifact_patch_schema() -> dict[str, Any]:
    """Load the canonical exact-revision artifact-patch schema."""
    return _load_schema('artifact_patch.schema.json')


def validate_artifact_patch(obj: Mapping[str, Any]) -> ArtifactPatchContract:
    """Validate a typed artifact patch against wire authority."""
    return _validate_schema_and_project(
        _materialize_redacted_payload(
            _materialize_artifact_plan_defs(load_artifact_patch_schema()),
        ),
        obj,
        _ARTIFACT_PATCH_ADAPTER,
    )


def load_artifact_error_schema() -> dict[str, Any]:
    """Load the stable value-free artifact error schema."""
    return _load_schema('artifact_error.schema.json')


def load_artifact_lifecycle_event_schema() -> dict[str, Any]:
    """Load the closed payload-only artifact lifecycle event schema."""
    return _load_schema('artifact_lifecycle_event.schema.json')


def validate_artifact_lifecycle_event_payload(
    obj: Mapping[str, Any],
) -> ArtifactLifecycleEventPayload:
    """Validate one exact value-free artifact lifecycle payload variant."""
    _check_against_schema(_materialize_artifact_error(load_artifact_lifecycle_event_schema()), obj)
    return parse_artifact_lifecycle_event_payload(obj)


def materialize_artifact_lifecycle_event_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ArtifactError so event consumers need no external schema registry."""
    return _materialize_artifact_error(schema)


def _materialize_artifact_error(schema: dict[str, Any]) -> dict[str, Any]:
    materialized = deepcopy(schema)
    error_schema = load_artifact_error_schema()
    error_schema.pop('$id', None)
    error_schema.pop('$schema', None)
    materialized.setdefault('$defs', {})['artifactError'] = error_schema
    return _rewritten_schema(
        materialized,
        'artifact_lifecycle_event.schema.json',
        (
            '"https://schemas.maivn.dev/artifacts/artifact_error.schema.json"',
            '"#/$defs/artifactError"',
        ),
    )


def validate_artifact_error(obj: Mapping[str, Any]) -> ArtifactError:
    """Validate code-derived error class and retryability without details."""
    return _validate_schema_and_project(load_artifact_error_schema(), obj, _ARTIFACT_ERROR_ADAPTER)
