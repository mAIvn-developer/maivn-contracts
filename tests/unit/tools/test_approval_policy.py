"""Approval policy is additive and cannot be confused with a wire grant."""

from typing import Literal

import pytest
from pydantic import ValidationError

from maivn_contracts.tools import ToolCall, validate_tool_spec
from maivn_contracts.tools.authorization import ToolSafetyLabels


@pytest.mark.parametrize('policy', ['deny', 'ask', 'allow'])
def test_policy_survives_schema_validation(policy: Literal['deny', 'ask', 'allow']) -> None:
    """Every authored policy crosses the strict schema boundary without dropping labels."""
    spec = validate_tool_spec(
        {
            'kind': 'function',
            'tool_id': 'erase',
            'namespace': 'sdk',
            'version': 'v1',
            'idempotency': 'non_idempotent',
            'timeout_ms': 1000,
            'name': 'erase',
            'description': 'Erase a record.',
            'input_schema': {'type': 'object'},
            'destructive': True,
            'approval_policy': policy,
        }
    )
    assert spec.approval_policy == policy
    assert spec.requires_approval
    assert spec.model_dump()['approval_policy'] == policy


def test_legacy_labels_keep_their_wire_shape_and_json_cannot_supply_a_grant() -> None:
    """An omitted policy preserves old serialization; a private grant is never a field."""
    labels = ToolSafetyLabels(destructive=True)
    assert labels.model_dump() == {'permissions': None, 'destructive': True}
    with pytest.raises(ValidationError, match='extra_forbidden'):
        ToolCall.model_validate(
            {
                'call_id': 'call',
                'spec_ref': {'tool_id': 'erase', 'namespace': 'sdk', 'version': 'v1'},
                'arguments': {},
                'lineage': {'session_id': 'session', 'invocation_id': 'invocation'},
                '_authorization': True,
            }
        )
