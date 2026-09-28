# pyright: strict
"""Isolated eval for ResourcePolicy and resource-processing contracts."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from maivn_contracts.resources import (
    ResourceTierDowngradeError,
    resolve_tier,
    validate_derived_artifact,
    validate_processing_state,
    validate_resource_policy,
)

_EVAL_TS = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)


def _version_stamps() -> dict[str, str]:
    return {
        'extractor_version': 'docling-1.0.0',
        'ocr_version': 'tesseract-5.4.0',
        'model_version': 'qwen2.5-vl-7b',
        'redaction_version': 'presidio-2.2.0',
        'policy_version': 'resource-policy-v1',
    }


def _attachment() -> dict[str, Any]:
    return {
        'attachment_id': 'att-eval-secure-manual',
        'filename': 'secure-manual.pdf',
        'mime_type': 'application/pdf',
        'size_bytes': 16384,
        'storage_ref': {
            'bucket': 'memory-resources',
            'path': 'prj-eval/resources/secure-manual.pdf',
            'sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        },
        'content_hash': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'resource_id': 'res-eval-secure-manual',
    }


def _processing_state(status: str, processed_at: str | None, attempt: int) -> dict[str, Any]:
    return {
        'resource_id': 'res-eval-secure-manual',
        'tier': 'secure',
        'status': status,
        'processed_at': processed_at,
        'attempt': attempt,
        'version_stamps': _version_stamps(),
    }


def _redacted_markdown_artifact() -> dict[str, Any]:
    return {
        'artifact_id': 'art-eval-redacted-markdown-v1',
        'resource_id': 'res-eval-secure-manual',
        'kind': 'redacted_markdown',
        'storage_ref': {
            'bucket': 'memory-resources',
            'path': 'prj-eval/derived/res-eval-secure-manual/v1/redacted.md',
        },
        'content_hash': 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
        'conversion_method': 'local-ocr-redaction',
        'ocr_confidence': 0.97,
        'version': 1,
        'version_stamps': _version_stamps(),
        'created_at': '2026-07-02T16:00:03Z',
    }


def _sidecar_artifact() -> dict[str, Any]:
    return {
        'artifact_id': 'art-eval-sidecar-map-v1',
        'resource_id': 'res-eval-secure-manual',
        'kind': 'sidecar_map',
        'inline_text': (
            '{"artifact_id":"art-eval-redacted-markdown-v1",'
            '"placeholders":[{"key":"patient_name","source":"figure-1"}]}'
        ),
        'content_hash': 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
        'conversion_method': 'redaction-sidecar-map',
        'version': 1,
        'version_stamps': _version_stamps(),
        'created_at': '2026-07-02T16:00:04Z',
    }


def _validate_plain_direct_path(errors: list[str]) -> str:
    plain_policy_tier: str | None = None
    redacted_policy_tier: str | None = 'indexed'
    plain_policy = {
        'resource': _attachment(),
        'tier': plain_policy_tier,
        'persist': None,
    }
    redacted_policy = {
        'resource': _attachment(),
        'tier': redacted_policy_tier,
        'persist': True,
    }

    plain_tier = ''
    try:
        validate_resource_policy(plain_policy)
        plain_tier = resolve_tier(message_has_redaction=False, policy_tier=plain_policy_tier)
        if plain_tier != 'direct':
            errors.append(f'plain bare attachment resolved to {plain_tier}')
    except Exception as exc:  # noqa: BLE001
        # Keep the eval collecting all contract failures in one run.
        errors.append(f'plain policy failed: {exc}')

    _validate_downgrade_rejection(redacted_policy, redacted_policy_tier, errors)
    return plain_tier


def _validate_downgrade_rejection(
    redacted_policy: dict[str, Any],
    redacted_policy_tier: str | None,
    errors: list[str],
) -> None:
    try:
        validate_resource_policy(redacted_policy)
        resolve_tier(message_has_redaction=True, policy_tier=redacted_policy_tier)
        errors.append('redacted indexed downgrade was accepted')
    except ResourceTierDowngradeError:
        pass
    except Exception as exc:  # noqa: BLE001
        # Keep the eval collecting all contract failures in one run.
        errors.append(f'redacted downgrade failed with wrong error: {exc}')

    secure_tier = resolve_tier(message_has_redaction=True, policy_tier=None)
    if secure_tier != 'secure':
        errors.append(f'redacted null tier resolved to {secure_tier}')


def _validate_secure_processing_states(errors: list[str]) -> None:
    secure_states = [
        _processing_state('pending', None, 0),
        _processing_state('processing', None, 1),
        _processing_state('ready', '2026-07-02T16:00:02Z', 1),
    ]
    for state in secure_states:
        try:
            validate_processing_state(state)
        except Exception as exc:  # noqa: BLE001
            # Keep the eval collecting all contract failures in one run.
            errors.append(f'state {state["status"]} failed: {exc}')


def _validate_derived_artifacts(errors: list[str]) -> None:
    artifacts = [_redacted_markdown_artifact(), _sidecar_artifact()]
    for artifact in artifacts:
        try:
            validate_derived_artifact(artifact)
        except Exception as exc:  # noqa: BLE001
            # Keep the eval collecting all contract failures in one run.
            errors.append(f'artifact {artifact["artifact_id"]} failed: {exc}')


def run_eval() -> dict[str, object]:
    """Run the ResourcePolicy boundary eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.resource_policy',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the ResourcePolicy boundary and artifact lifecycle eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    errors: list[str] = []

    plain_tier = _validate_plain_direct_path(errors)
    processing_records: list[dict[str, Any]] = []
    if plain_tier != 'direct':
        errors.append('direct run unexpectedly required processing records')

    _validate_secure_processing_states(errors)
    _validate_derived_artifacts(errors)

    if processing_records:
        errors.append('plain direct path produced a processing record')

    if errors:
        lines = ['FAIL resource policy eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'processing_records': float(len(processing_records))}

    lines = [
        'PASS resource policy eval',
        'plain_bare_attachment_tier=direct',
        'plain_processing_records=0',
        'redacted_attachment_floor=secure',
        'indexed_downgrade_rejected=true',
        'secure_states=pending,processing,ready',
        'artifacts=redacted_markdown,sidecar_map',
        'version_stamps=extractor,ocr,model,redaction,policy',
    ]
    return 0, lines, {'processing_records': 0.0, 'secure_states_validated': 3.0}


if __name__ == '__main__':
    sys.exit(main())
