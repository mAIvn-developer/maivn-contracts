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
