"""Cron expressions exactly as the event plane's five-field scheduler accepts them."""

from __future__ import annotations

import calendar
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class _CronExpressionError(ValueError):
    """Raised when a cron expression cannot be scheduled by the event plane."""

    def __init__(self, detail: str) -> None:
        """Build an actionable cron validation error."""
        super().__init__(f'Invalid cron expression: {detail}')


_CRON_FIELDS: tuple[tuple[int, int, dict[str, int]], ...] = (
    (0, 59, {}),
    (0, 23, {}),
    (1, 31, {}),
    (
        1,
        12,
        {
            name: index
            for index, name in enumerate(
                (
                    'jan',
                    'feb',
                    'mar',
                    'apr',
                    'may',
                    'jun',
                    'jul',
                    'aug',
                    'sep',
                    'oct',
                    'nov',
                    'dec',
                ),
                start=1,
            )
        },
    ),
    (
        0,
        6,
        {
            name: index
            for index, name in enumerate(
                ('sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'),
            )
        },
    ),
)
_CRON_DESCRIPTORS = frozenset(
    ('@yearly', '@annually', '@monthly', '@weekly', '@daily', '@midnight', '@hourly'),
)
_CRON_RANGE = re.compile(r'([*?]|[0-9]+|[a-zA-Z]{3})(?:-([0-9]+|[a-zA-Z]{3}))?(?:/([0-9]+))?')
_MAX_CRON_STEP = 2**63 - 1


def _cron_field_values(field: str, minimum: int, maximum: int, names: dict[str, int]) -> set[int]:
    values: set[int] = set()
    for part in field.split(','):
        match = _CRON_RANGE.fullmatch(part)
        if match is None:
            message = f'invalid field {field!r}'
            raise _CronExpressionError(message)
        low, high, stride = match.groups()
        step = int(stride) if stride is not None else 1
        if not 1 <= step <= _MAX_CRON_STEP:
            message = 'steps must be positive 64-bit integers'
            raise _CronExpressionError(message)
        if low in ('*', '?'):
            if high is not None:
                message = 'wildcards cannot start a range'
                raise _CronExpressionError(message)
            start, end = minimum, maximum
        else:
            start = names.get(low.lower(), -1) if low.isalpha() else int(low)
            end = start if stride is None else maximum
            if high is not None:
                end = names.get(high.lower(), -1) if high.isalpha() else int(high)
        if not minimum <= start <= end <= maximum:
            message = f'field {field!r} must be within {minimum}..{maximum}'
            raise _CronExpressionError(message)
        values.update(range(start, end + 1, step))
    return values


def validate_cron_expression(value: str) -> None:
    """Match the event plane's five-field cron parser, with no seconds or @every."""
    expression = value.strip()
    if expression.startswith(('CRON_TZ=', 'TZ=')):
        prefix, separator, expression = expression.partition(' ')
        timezone = prefix.split('=', maxsplit=1)[1]
        if not separator or not timezone:
            message = 'timezone prefix requires a zone and expression'
            raise _CronExpressionError(message)
        if timezone not in ('UTC', 'Local'):
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                message = f'unknown or unavailable timezone {timezone!r}'
                raise _CronExpressionError(message) from exc
        expression = expression.strip()
    if expression in _CRON_DESCRIPTORS:
        return
    fields = expression.split()
    if len(fields) != len(_CRON_FIELDS):
        message = 'expected five fields or a supported calendar descriptor'
        raise _CronExpressionError(message)
    parsed = [
        _cron_field_values(field, minimum, maximum, names)
        for field, (minimum, maximum, names) in zip(fields, _CRON_FIELDS, strict=True)
    ]
    # A restricted weekday is ORed with a restricted day of month by robfig/cron.
    weekday_wildcard = any(
        part.split('/')[0] in ('*', '?') and ('/' not in part or int(part.split('/')[1]) == 1)
        for part in fields[4].split(',')
    )
    if weekday_wildcard and not any(
        day <= calendar.monthrange(2000, month)[1] for month in parsed[3] for day in parsed[2]
    ):
        message = 'day of month never occurs in the selected months'
        raise _CronExpressionError(message)


__all__ = ['validate_cron_expression']
