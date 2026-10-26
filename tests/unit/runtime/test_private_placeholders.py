# pyright: strict
"""The placeholder syntax and key derivation the brain and the SDK must share exactly."""

from __future__ import annotations

import pytest

from maivn_contracts.runtime.private_placeholders import (
    CALLER_NAMED_KEY_PREFIX,
    PLACEHOLDER_PATTERN,
    caller_named_key_candidates,
    normalize_placeholder_key,
    sanitize_private_key_name,
)


def test_placeholder_pattern_finds_adjacent_tokens_and_rejects_braced_keys() -> None:
    """Keys cannot contain braces, so adjacent placeholders never merge."""
    assert PLACEHOLDER_PATTERN.findall('{_{a}_}{_{b}_} and {_{ c d }_}') == ['a', 'b', ' c d ']
    assert PLACEHOLDER_PATTERN.findall('{_{a{b}_} {_{}_} {{a}} {_a_}') == []


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('  key  ', 'key'),
        ('"key"', 'key'),
        ('" key "', 'key'),
        ('{key}', 'key'),
        ('{{key}}', 'key'),
        ('"{key}"', 'key'),
        ('{"key"}', 'key'),
        ('"{"key"}"', 'key'),
        ('{{{key}}}', '{key}'),
        ('$key', 'key'),
        ('"$ key"', 'key'),
        ('{ "$key" }', 'key'),
        ('$"key"', '"key"'),
        ('"', ''),
        ('{', '{'),
        ('', ''),
    ],
)
def test_normalize_placeholder_key_unwraps_model_spellings(raw: str, expected: str) -> None:
    """Quotes and braces unwrap at most twice, then one quote pair and a leading `$`."""
    assert normalize_placeholder_key(raw) == expected


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('claim_id', 'claim_id'),
        ('  Claim-ID  ', 'claim_id'),
        ('__x__', 'x'),
        ('a b.c', 'a_b_c'),
        ('Über Name', 'ber_name'),
        ('!!!', 'custom'),
        ('', 'custom'),
    ],
)
def test_sanitize_private_key_name_lowercases_and_replaces_non_key_characters(
    name: str,
    expected: str,
) -> None:
    """Names become `[a-z0-9_]`, trimmed of underscores, falling back to `custom`."""
    assert sanitize_private_key_name(name) == expected


@pytest.mark.parametrize(
    ('key', 'expected'),
    [
        (f'{CALLER_NAMED_KEY_PREFIX}claim_id', ('user_claim_id', 'claim_id')),
        ('user_user_x', ('user_user_x', 'user_x')),
        (CALLER_NAMED_KEY_PREFIX, ('user_',)),
        ('claim_id', ('claim_id',)),
        ('USER_claim', ('USER_claim',)),
    ],
)
def test_caller_named_key_candidates_try_the_literal_key_first(
    key: str,
    expected: tuple[str, ...],
) -> None:
    """The exact key wins; a `user_` key also offers the caller's original name."""
    assert caller_named_key_candidates(key) == expected
    assert CALLER_NAMED_KEY_PREFIX == 'user_'
