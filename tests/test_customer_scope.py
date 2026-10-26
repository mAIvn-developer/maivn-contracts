"""Opaque asserted customer subject contract."""

import pytest

from maivn_contracts.runtime.customer_scope import memory_owner_user_id


@pytest.mark.parametrize('value', [None, '', ' ', 'sdk-user'])
def test_subjectless(value: str | None) -> None:
    """Subjectless."""
    assert memory_owner_user_id(value) is None


@pytest.mark.parametrize('value', [' A', 'A ', 'a\x00b', 'a\nb', 'x' * 257])
def test_invalid(value: str) -> None:
    """Invalid."""
    with pytest.raises(ValueError, match='user_id'):
        memory_owner_user_id(value)


def test_subject_is_opaque() -> None:
    """Subject is opaque."""
    assert memory_owner_user_id('Customer-A') == 'Customer-A'
    assert memory_owner_user_id('customer-a') == 'customer-a'
