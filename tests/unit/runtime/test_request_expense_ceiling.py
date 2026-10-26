"""Exact optional request expense ceilings agree across both wire validators."""

from __future__ import annotations

import pytest
from jsonschema import ValidationError as SchemaValidationError
from pydantic import ValidationError

from maivn_contracts.runtime import RunConfig, validate_run_config


@pytest.mark.parametrize(
    'ceiling', ['0.000000000001', '1', '1.25', '999999999999999999.999999999999']
)
def test_exact_expense_ceiling_is_preserved(ceiling: str) -> None:
    """Verify exact expense ceiling is preserved."""
    payload = {'user_id': 'user', 'thread_id': 'thread', 'max_expense_usd': ceiling}
    assert RunConfig.model_validate(payload).max_expense_usd == ceiling
    validate_run_config(payload)


@pytest.mark.parametrize(
    'ceiling',
    [
        True,
        1,
        0.1,
        '',
        '0',
        '0.000',
        '-1',
        'NaN',
        'Infinity',
        '1e1',
        '01',
        ' 1',
        '1.0000000000001',
        '1000000000000000000',
    ],
)
def test_expense_ceiling_rejects_lossy_or_invalid_values(ceiling: object) -> None:
    """Verify expense ceiling rejects lossy or invalid values."""
    payload = {'user_id': 'user', 'thread_id': 'thread', 'max_expense_usd': ceiling}
    with pytest.raises(ValidationError):
        RunConfig.model_validate(payload)
    with pytest.raises(SchemaValidationError):
        validate_run_config(payload)


def test_omitted_expense_ceiling_preserves_wire_shape() -> None:
    """Verify omitted expense ceiling preserves wire shape."""
    payload = {'user_id': 'user', 'thread_id': 'thread'}
    assert RunConfig.model_validate(payload).model_dump(exclude_unset=True) == payload
