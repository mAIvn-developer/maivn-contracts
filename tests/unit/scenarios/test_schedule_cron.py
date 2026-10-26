"""Cron validation at the canonical schedule contract boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from maivn_contracts.scenarios import validate_trigger
from maivn_contracts.scenarios.model import ScheduleSource


@pytest.mark.parametrize(
    'cron',
    [
        'not a cron',
        '   ',
        '* * * *',
        '* * * * * *',
        '60 * * * *',
        '* 24 * * *',
        '* * 0 * *',
        '* * 32 * *',
        '* * * 0 *',
        '* * * 13 *',
        '* * * * 7',
        '*/0 * * * *',
        '1-0 * * * *',
        '1-2-3 * * * *',
        '1/2/3 * * * *',
        ', * * * *',
        '* * * JANUARY *',
        '* * * * MONDAY',
        '0 0 31 FEB *',
        '0 0 31 FEB */01',
        '@reboot',
        '@every 1m',
        'CRON_TZ=UTC @every 1m',
        'CRON_TZ=UTC',
        'TZ=',
        'CRON_TZ=Missing/Zone * * * * *',
    ],
)
def test_schedule_source_rejects_invalid_cron(cron: str) -> None:
    """Reject malformed selectors before any writer can persist the source."""
    with pytest.raises(ValidationError, match='cron'):
        ScheduleSource(kind='schedule', phase='phase_1', cron=cron)


@pytest.mark.parametrize(
    'cron',
    [
        '* * * * *',
        '*/5 9-17 * * MON-FRI',
        '0,30 9-17/2 1,15 JAN,MAR MON',
        '5/10 * * * *',
        '0 0 29 FEB *',
        '0 0 31 FEB MON',
        '0 0 ? * MON',
        '  0\t0 * * *  ',
        'TZ=UTC 0 0 * * *',
        'CRON_TZ=UTC 0 0 * * *',
        '@yearly',
        '@annually',
        '@monthly',
        '@weekly',
        '@daily',
        '@midnight',
        '@hourly',
    ],
)
def test_schedule_source_accepts_supported_cron(cron: str) -> None:
    """Keep the scheduler's five-field syntax, names, descriptors, and UTC prefix."""
    source = ScheduleSource(kind='schedule', phase='phase_1', cron=cron)
    assert source.cron == cron


@pytest.mark.parametrize(
    'cron', ['TZ=America/Chicago 0 9 * * *', 'CRON_TZ=Europe/Berlin 0 9 * * *']
)
def test_schedule_source_accepts_named_time_zones_on_every_host(cron: str) -> None:
    """Named zones validate without relying on the host's time-zone database."""
    source = ScheduleSource(kind='schedule', phase='phase_1', cron=cron)
    assert source.cron == cron


def test_validate_trigger_rejects_invalid_cron() -> None:
    """The public contract loader applies semantic validation to nested sources."""
    fixtures = Path(__file__).resolve().parents[2] / 'fixtures' / 'valid_triggers.json'
    payload = json.loads(fixtures.read_text(encoding='utf-8'))[0]
    payload['source'] = {'kind': 'schedule', 'phase': 'phase_1', 'cron': 'not a cron'}
    with pytest.raises(ValidationError, match='cron'):
        validate_trigger(payload)


def test_schedule_source_keeps_interval_selector() -> None:
    """Cron validation leaves the fixed-interval alternative available."""
    source = ScheduleSource(kind='schedule', phase='phase_1', interval_seconds=60)
    assert source.cron is None


@pytest.mark.parametrize(
    ('cron', 'detail'),
    [
        ('*/9223372036854775808 * * * *', 'steps must be positive 64-bit integers'),
        ('*-5 * * * *', 'wildcards cannot start a range'),
        ('* * * XYZ *', "field 'XYZ' must be within 1..12"),
        ('* * * * MON-XYZ', "field 'MON-XYZ' must be within 0..6"),
        ('*/0 * * * *', 'steps must be positive 64-bit integers'),
        ('* * 32 * *', "field '32' must be within 1..31"),
        ('TZ= 0 0 * * *', 'timezone prefix requires a zone and expression'),
        ('0 0 31 FEB *', 'day of month never occurs in the selected months'),
    ],
)
def test_cron_errors_name_the_rule_that_failed(cron: str, detail: str) -> None:
    """Each refusal carries the exact actionable reason."""
    with pytest.raises(ValidationError) as caught:
        ScheduleSource(kind='schedule', phase='phase_1', cron=cron)
    assert caught.value.errors()[0]['msg'] == f'Value error, Invalid cron expression: {detail}'


@pytest.mark.parametrize(
    'cron',
    [
        '*/9223372036854775807 * * * *',
        'CRON_TZ=Local 0 0 * * *',
        '0 0 31 FEB */2',
        '0 0 30 FEB,APR *',
        '0 0 31 2/1 *',
    ],
)
def test_cron_accepts_largest_step_local_zone_and_restricted_weekdays(
    cron: str,
) -> None:
    """The 64-bit step maximum, the Local zone and ORed weekday rules are accepted."""
    assert ScheduleSource(kind='schedule', phase='phase_1', cron=cron).cron == cron
