# pyright: strict
"""PII whitelist validation is complete at the wire boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maivn_contracts.messages import PIIWhitelist, PIIWhitelistEntry
from maivn_contracts.messages.model import HIPAA_SAFE_HARBOR_CATEGORIES


@pytest.mark.parametrize('pattern', ['.*', '['])
def test_pattern_must_be_safe_to_compile(pattern: str) -> None:
    """Reject unusable or trivially permissive patterns on wire intake."""
    with pytest.raises(ValidationError):
        PIIWhitelistEntry(
            pattern=pattern,
            justification='Public values approved by legal.',
        )


def test_entity_type_is_normalized_at_wire_intake() -> None:
    """Keep category matching stable across every whitelist consumer."""
    entry = PIIWhitelistEntry(
        entity_type='  DateTime  ',
        justification='Scheduling dates are application data.',
    )

    assert entry.entity_type == 'datetime'


@pytest.mark.parametrize(
    ('selector', 'justification'),
    [
        ({'value': '  x  '}, 'Public value approved by legal.'),
        ({'entity_type': 'url'}, '        '),
    ],
)
def test_lengths_are_checked_after_whitespace_is_removed(
    selector: dict[str, str],
    justification: str,
) -> None:
    """Whitespace cannot satisfy the value or audit-justification floors."""
    with pytest.raises(ValidationError):
        PIIWhitelistEntry(**selector, justification=justification)


JUSTIFICATION = 'Approved by the compliance team.'


@pytest.mark.parametrize(
    'selectors',
    [
        {},
        {'entity_type': 'url', 'value': 'example.com'},
        {'pattern': r'\d{3}-\d{4}', 'value': '555-0100'},
    ],
)
def test_entry_names_exactly_one_selector(selectors: dict[str, str]) -> None:
    """An entry is exactly one of entity_type, pattern or value."""
    with pytest.raises(
        ValidationError,
        match='requires exactly one of entity_type, pattern, or value',
    ):
        PIIWhitelistEntry(**selectors, justification=JUSTIFICATION)


@pytest.mark.parametrize(
    ('selector', 'message'),
    [
        ({'entity_type': '   '}, 'entity_type cannot be blank'),
        ({'pattern': '   '}, 'pattern cannot be blank'),
        ({'pattern': '(unclosed'}, 'invalid regex pattern'),
        ({'pattern': '.*'}, 'pattern is too permissive'),
        ({'pattern': '(?i)A*'}, 'pattern is too permissive'),
        ({'pattern': 'A+|^$'}, 'pattern is too permissive'),
        ({'pattern': '^(a|)$'}, 'pattern is too permissive'),
        ({'value': ' ab '}, 'value must be at least 3 characters after stripping'),
    ],
)
def test_selectors_refuse_blank_invalid_and_match_everything_patterns(
    selector: dict[str, str],
    message: str,
) -> None:
    """Blank selectors, uncompilable regexes and match-everything patterns are refused."""
    with pytest.raises(ValidationError, match=message):
        PIIWhitelistEntry(**selector, justification=JUSTIFICATION)


def test_value_and_justification_are_stored_stripped() -> None:
    """Accepted values and justifications keep no surrounding whitespace."""
    entry = PIIWhitelistEntry(value='  ACME Corp  ', justification=f'  {JUSTIFICATION}  ')
    assert (entry.value, entry.justification) == ('ACME Corp', JUSTIFICATION)
    assert PIIWhitelistEntry(pattern=r'ACME-\d+', justification=JUSTIFICATION).pattern == (
        r'ACME-\d+'
    )


def test_phi_mode_forbids_safe_harbor_entity_types_only() -> None:
    """With phi_mode on, Safe Harbor categories cannot be whitelisted; others can."""
    safe_harbor = PIIWhitelistEntry(entity_type='Email', justification=JUSTIFICATION)
    ordinary = PIIWhitelistEntry(entity_type='product_code', justification=JUSTIFICATION)
    literal = PIIWhitelistEntry(value='email', justification=JUSTIFICATION)

    assert PIIWhitelist(entries=[safe_harbor], phi_mode=False).entries == [safe_harbor]
    assert PIIWhitelist(entries=[ordinary, literal], phi_mode=True).phi_mode is True
    assert PIIWhitelist(entries=None, phi_mode=True).entries is None
    with pytest.raises(ValidationError, match=r"Safe Harbor categories: \['email', 'url'\]"):
        PIIWhitelist(
            entries=[
                safe_harbor,
                PIIWhitelistEntry(entity_type='url', justification=JUSTIFICATION),
                safe_harbor,
            ],
            phi_mode=True,
        )


def test_safe_harbor_categories_are_pinned() -> None:
    """The HIPAA Safe Harbor category set is part of the contract."""
    assert (
        frozenset(
            {
                'person',
                'ssn',
                'phone',
                'fax',
                'email',
                'credit_card',
                'iban',
                'swift',
                'account_id',
                'medical_record_number',
                'health_plan_id',
                'certificate_id',
                'license_id',
                'vehicle_id',
                'device_id',
                'biometric_id',
                'ip_address',
                'url',
                'date',
                'datetime',
            },
        )
        == HIPAA_SAFE_HARBOR_CATEGORIES
    )


@pytest.mark.parametrize(
    'pattern',
    ['.+', '.', r'\w+', '[a-z]+', '^$', '[A-Z]', r'\d+', '[-_.]', r'\S'],
)
def test_pattern_matching_empty_or_any_single_character_is_too_permissive(pattern: str) -> None:
    """One broad pattern would exempt every detected value from redaction."""
    with pytest.raises(ValidationError, match='too permissive'):
        PIIWhitelistEntry(
            pattern=pattern,
            justification='Public values approved by legal.',
        )


@pytest.mark.parametrize(
    'pattern',
    [r'\d{4}-\d{1,2}-\d{1,2}', r'\d{4}-\d{4}-\d{4}', r'\b(?:May)\b', '^item-[0-9]+$'],
)
def test_narrow_patterns_are_still_accepted(pattern: str) -> None:
    """Shape-specific patterns suggested by the over-redaction guidance stay valid."""
    entry = PIIWhitelistEntry(pattern=pattern, justification='Benign values with this shape.')

    assert entry.pattern == pattern
