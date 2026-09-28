# pyright: strict
"""Isolated eval for the owned tools contract."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from jsonschema import Draft202012Validator

from maivn_contracts.tools import (
    ErrorToolOutcome,
    FunctionToolSpec,
    MCPToolSpec,
    OkToolOutcome,
    SystemToolSpec,
    ToolCall,
    ToolOutcome,
    ToolSpec,
    validate_tool_call,
    validate_tool_outcome,
    validate_tool_spec,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

ConcreteToolSpec: TypeAlias = FunctionToolSpec | MCPToolSpec | SystemToolSpec
EvalModel: TypeAlias = ConcreteToolSpec | ToolCall | OkToolOutcome | ErrorToolOutcome
ModelValidator: TypeAlias = Callable[[dict[str, Any]], EvalModel]
_EVAL_TS = datetime(2026, 7, 3, 15, 0, tzinfo=timezone.utc)


def _function_tool_spec() -> dict[str, Any]:
    return {
        'tool_id': 'tool-lookup-case',
        'kind': 'function',
        'namespace': 'support',
        'version': '2026-07-03',
        'idempotency': 'idempotent',
        'timeout_ms': 5000,
        'name': 'lookup_case',
        'description': 'Look up a support case by id.',
        'input_schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {'case_id': {'type': 'string'}},
            'required': ['case_id'],
        },
        'output_schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {'priority': {'type': 'string'}},
            'required': ['priority'],
        },
    }


def _mcp_tool_spec() -> dict[str, Any]:
    return {
        'tool_id': 'tool-gmail-send',
        'kind': 'mcp',
        'namespace': 'connectors.gmail',
        'version': '2026-07-03',
        'idempotency': 'non_idempotent',
        'timeout_ms': 10000,
        'auth': {
            'scheme': 'oauth',
            'secret_ref': 'vault://projects/prj-support/connections/gmail',
        },
        'server_ref': {'kind': 'registry', 'name': 'gmail'},
        'tool_name': 'send_email',
        'schema_policy': 'passthrough',
        'input_schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'to': {'type': 'string'},
                'subject': {'type': 'string'},
                'body': {'type': 'string'},
            },
            'required': ['to', 'subject', 'body'],
        },
    }


def _tool_call() -> dict[str, Any]:
    return {
        'call_id': 'call-lookup-001',
        'spec_ref': {
            'tool_id': 'tool-lookup-case',
            'namespace': 'support',
            'version': '2026-07-03',
        },
        'arguments': {'case_id': 'case-1001'},
        'lineage': {
            'session_id': 'ses-support-001',
            'invocation_id': 'inv-support-001',
            'message_id': 'msg-assistant-tool-use-001',
            'root_call_id': 'call-lookup-001',
        },
    }


def _ok_outcome() -> dict[str, Any]:
    return {
        'call_id': 'call-lookup-001',
        'status': 'ok',
        'duration_ms': 42,
        'result': {'priority': 'high'},
        'artifact_refs': [
            {
                'artifact_id': 'art-case-brief-001',
                'logical_output_id': 'out-case-brief-001',
                'revision': 1,
                'kind': 'document',
                'mime_type': 'application/pdf',
                'custody': 'ordinary',
                'state': 'available',
                'created_at': '2026-07-03T15:00:00Z',
                'effective_retention': {
                    'policy_snapshot_id': 'policy-case-brief-001',
                    'retention_class': 'invocation_artifact_30d',
                    'expires_at': '2026-08-02T15:00:00Z',
                },
                'producer': {
                    'producer_class': 'hosted_tool',
                    'producer_id': 'producer-case-brief-001',
                    'root_invocation_id': 'inv-support-001',
                },
                'display_filename': 'case-brief.pdf',
                'size_bytes': 4096,
                'sha256': 'a' * 64,
                'validation_receipt': {
                    'receipt_id': 'receipt-case-brief-001',
                    'status': 'validated',
                    'validator_profile': 'document-default',
                    'validator_version': '1.0.0',
                },
                'safe_preview': {'kind': 'document', 'page_count': 1},
                'retrieval_action': {'relation': 'artifact.download_authorization'},
            },
        ],
    }


def _error_outcome() -> dict[str, Any]:
    return {
        'call_id': 'call-gmail-send-001',
        'status': 'error',
        'duration_ms': 250,
        'error': {
            'code': 'rate_limited',
            'message': 'Gmail returned a retryable rate-limit response.',
            'retryable': True,
        },
    }


def _dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode='json', exclude_none=True)


def _stable_bytes(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _input_schema(spec: ToolSpec) -> dict[str, Any]:
    if isinstance(spec, FunctionToolSpec | MCPToolSpec | SystemToolSpec):
        return spec.input_schema
    message = f'unsupported tool spec variant: {type(spec).__name__}'
    raise TypeError(message)


def _validate_model(
    label: str,
    payload: dict[str, Any],
    validator: ModelValidator,
    errors: list[str],
) -> EvalModel | None:
    try:
        model = validator(payload)
        if _dump_model(model) != payload:
            errors.append(f'{label} model dump changed the wire payload')
        if _stable_bytes(_dump_model(model)) != _stable_bytes(payload):
            errors.append(f'{label} round-trip was not byte-stable')
    except Exception as exc:  # noqa: BLE001
        # Keep the eval collecting all contract failures in one run.
        errors.append(f'{label} failed validation: {exc}')
        return None
    else:
        return model


def _evaluate() -> tuple[int, list[str], dict[str, float]]:
    errors: list[str] = []
    function_spec = _validate_model(
        'function tool spec',
        _function_tool_spec(),
        validate_tool_spec,
        errors,
    )
    mcp_spec = _validate_model('mcp tool spec', _mcp_tool_spec(), validate_tool_spec, errors)
    call = _validate_model('tool call', _tool_call(), validate_tool_call, errors)
    ok_outcome = _validate_model('ok outcome', _ok_outcome(), validate_tool_outcome, errors)
    error_outcome = _validate_model(
        'error outcome',
        _error_outcome(),
        validate_tool_outcome,
        errors,
    )

    if isinstance(function_spec, ToolSpec) and isinstance(call, ToolCall):
        try:
            argument_validator = cast(
                'Callable[[object], None]',
                Draft202012Validator(_input_schema(function_spec)).validate,
            )
            argument_validator(call.arguments)
        except Exception as exc:  # noqa: BLE001
            # Keep the eval collecting all contract failures in one run.
            errors.append(f'tool call arguments failed referenced spec schema: {exc}')

    specs_validated = [
        spec.kind
        for spec in (function_spec, mcp_spec)
        if isinstance(spec, FunctionToolSpec | MCPToolSpec | SystemToolSpec)
    ]
    artifact_count = (
        len(ok_outcome.artifact_refs)
        if isinstance(ok_outcome, ToolOutcome) and ok_outcome.artifact_refs is not None
        else 0
    )
    retryable = 'false'
    if isinstance(error_outcome, ErrorToolOutcome):
        retryable = str(error_outcome.error.retryable).lower()

    if errors:
        lines = ['FAIL tools contract eval', *[f'- {error}' for error in errors]]
        return 1, lines, {'tool_specs': float(len(specs_validated))}

    lines = [
        'PASS tools contract eval',
        f'tool_specs_validated={",".join(specs_validated)}',
        'tool_call_validated=call-lookup-001',
        f'ok_outcome_artifacts={artifact_count}',
        f'error_outcome_retryable={retryable}',
        'round_trip=byte-stable',
    ]
    return 0, lines, {'tool_specs': 2.0, 'artifact_refs': float(artifact_count)}


def run_eval() -> dict[str, object]:
    """Run the owned tools contract eval for the harness."""
    exit_status, lines, metrics = _evaluate()
    return {
        'name': 'contracts.tools',
        'status': 'pass' if exit_status == 0 else 'fail',
        'grade': 'A' if exit_status == 0 else 'F',
        'metrics': metrics,
        'details': '\n'.join(lines),
        'artifacts': [],
        'ts': _EVAL_TS,
    }


def main() -> int:
    """Run the owned tools contract eval."""
    exit_status, lines, _metrics = _evaluate()
    for line in lines:
        print(line)
    return exit_status


if __name__ == '__main__':
    sys.exit(main())
