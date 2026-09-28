"""The one error body every public mAIvn API reply carries.

Every non-2xx JSON reply, whichever service answered it, is one object:

    {"detail": "<human message>", "code": "<machine_code>",
     "fields": [...], "retry_after": 30, "context": {...}, "request_id": "..."}

`detail` and `code` are always present. The rest appear only when they carry
something: `fields` for request validation, `retry_after` beside a Retry-After
header, `context` for public, per-code data (a plan-limit refusal names its
meter and ceiling), `request_id` when a request id exists.

The rendered bytes are part of the contract: keys in the order above, compact
separators, UTF-8, `context` keys sorted. Two services rendering the same error
produce the same bytes, so nothing about an error says which one answered.
`tests/fixtures/api_error_vectors.json` pins those bytes for every renderer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

ERROR_CODE_PATTERN = r'^[a-z][a-z0-9_]*$'
"""A stable machine code: lower snake case, never free text."""

MAX_ERROR_FIELDS = 50
"""Validation replies name at most this many fields; the rest add nothing."""

_CODE = re.compile(ERROR_CODE_PATTERN)
_ENVELOPE_KEYS = ('detail', 'code', 'fields', 'retry_after', 'context', 'request_id')
_REQUEST_SOURCES = frozenset({'body'})
_TERMINAL_PUNCTUATION = frozenset('.!?')


class ApiErrorField(BaseModel):
    """One request field that failed validation, named by its public path."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    field: StrictStr = Field(..., description='Dotted path of the field in the request.')
    message: StrictStr = Field(..., min_length=1, description='What is wrong with it.')


class ApiErrorBody(BaseModel):
    """The typed error body shared by every public API reply."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    detail: StrictStr = Field(..., min_length=1, description='Human-readable message.')
    code: StrictStr = Field(
        ...,
        pattern=ERROR_CODE_PATTERN,
        description='Stable machine-readable code.',
    )
    fields: tuple[ApiErrorField, ...] | None = Field(
        default=None,
        description='Request fields that failed validation.',
    )
    retry_after: StrictInt | None = Field(
        default=None,
        ge=0,
        description='Seconds to wait before retrying; mirrors the Retry-After header.',
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description='Public, code-specific data a client can act on.',
    )
    request_id: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Opaque id of the request, for support.',
    )

    def to_json_dict(self) -> dict[str, Any]:
        """Return the body as a JSON-ready dict in canonical key order."""
        return error_body(
            code=self.code,
            detail=self.detail,
            fields=self.fields,
            retry_after=self.retry_after,
            context=self.context,
            request_id=self.request_id,
        )


_DEFAULTS: Mapping[int, tuple[str, str]] = {
    400: ('bad_request', 'Bad request.'),
    401: ('authentication_failed', 'Authentication required.'),
    403: ('authorization_failed', 'You do not have access to this resource.'),
    404: ('not_found', 'Not found.'),
    405: ('method_not_allowed', 'Method not allowed.'),
    406: ('not_acceptable', 'The requested representation is not available.'),
    408: ('timeout', 'The request timed out. Try again.'),
    409: ('conflict', 'The request conflicts with the current state.'),
    410: ('gone', 'This resource is no longer available.'),
    411: ('length_required', 'A Content-Length header is required.'),
    413: ('request_too_large', 'Request body too large.'),
    414: ('request_too_large', 'Request URI too long.'),
    415: ('unsupported_media_type', 'Unsupported content type.'),
    416: ('range_not_satisfiable', 'The requested range is not available.'),
    422: ('validation_failed', 'Request validation failed.'),
    426: ('upgrade_required', 'Upgrade required.'),
    429: ('rate_limited', 'Too many requests. Try again shortly.'),
    500: ('internal_error', 'Internal error.'),
    501: ('not_implemented', 'Not implemented.'),
    502: ('service_unavailable', 'Service temporarily unavailable. Try again shortly.'),
    503: ('service_unavailable', 'Service temporarily unavailable. Try again shortly.'),
    504: ('timeout', 'The request timed out. Try again.'),
}


def default_error(status_code: int) -> tuple[str, str]:
    """Return the generic `(code, detail)` for an HTTP status."""
    known = _DEFAULTS.get(status_code)
    if known is not None:
        return known
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return _DEFAULTS[500]
    return _DEFAULTS[400]


def coerce_code(code: object, status_code: int) -> str:
    """Return `code` as a machine code, or the status's generic code.

    Codes that reach a reply at runtime (a diagnostic's code, an upstream
    reason) are folded to lower snake case rather than trusted; anything that
    still is not a code becomes the generic code for the status, so a reply is
    never refused for its code.
    """
    if isinstance(code, str):
        if _CODE.fullmatch(code):
            return code
        folded = re.sub(r'[^a-z0-9_]+', '_', code.strip().lower()).strip('_')
        if _CODE.fullmatch(folded):
            return folded
    return default_error(status_code)[0]


def error_body(  # noqa: PLR0913 - every envelope member is an explicit keyword.
    *,
    code: str,
    detail: str,
    fields: Iterable[ApiErrorField | Mapping[str, str]] | None = None,
    retry_after: int | None = None,
    context: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the canonical error body as a JSON-ready dict.

    Key order is the contract's: detail, code, then whichever optional members
    carry something. `context` keys are sorted at every depth so the rendered
    bytes never depend on how a caller happened to build the mapping.
    """
    if not _CODE.fullmatch(code):
        message = f'error code must match {ERROR_CODE_PATTERN}'
        raise ValueError(message)
    detail = public_sentence(detail)
    if not detail:
        message = 'error detail must be a non-empty string'
        raise ValueError(message)
    body: dict[str, Any] = {'detail': detail, 'code': code}
    if fields is not None:
        rendered = [_field_dict(field) for field in fields]
        if rendered:
            body['fields'] = rendered[:MAX_ERROR_FIELDS]
    if retry_after is not None:
        body['retry_after'] = max(0, int(retry_after))
    if context:
        body['context'] = _sorted_json(dict(context))
    if request_id:
        body['request_id'] = request_id
    return body


def public_sentence(text: str) -> str:
    """Return `text` as one sentence: trimmed, capitalised, and punctuated.

    Services word their messages differently; a shared sentence form keeps the
    wording from sorting replies by service. Only a first word made purely of
    lower-case ASCII letters is capitalised, so a leading field path such as
    `run_config.project_id` is left exactly as the caller wrote it.
    """
    sentence = text.strip()
    if not sentence:
        return sentence
    first_word = sentence.split(' ', 1)[0]
    if first_word.isascii() and first_word.isalpha() and first_word.islower():
        sentence = sentence[0].upper() + sentence[1:]
    if sentence[-1] not in _TERMINAL_PUNCTUATION:
        sentence += '.'
    return sentence


def render_error_body(body: Mapping[str, Any]) -> bytes:
    """Render an error body to its canonical bytes."""
    return json.dumps(
        dict(body),
        ensure_ascii=False,
        allow_nan=False,
        separators=(',', ':'),
    ).encode('utf-8')


def is_error_body(value: object) -> bool:
    """Return whether a decoded JSON value is exactly a valid error body."""
    if not isinstance(value, dict):
        return False
    body = cast('dict[str, Any]', value)
    if tuple(key for key in _ENVELOPE_KEYS if key in body) != tuple(body):
        return False
    try:
        ApiErrorBody.model_validate_json(json.dumps(body), strict=True)
    except (TypeError, ValueError):
        return False
    return True


def validation_fields(errors: Iterable[Mapping[str, Any]]) -> tuple[ApiErrorField, ...]:
    """Name the failing request fields without exposing how the service models them.

    A validator's location path mixes the caller's own field names with the
    service's internals: union member model names, validator function tags,
    and the `body` segment the framework adds. Only the caller's field names
    and list indexes survive. Input values and validator context never do.
    """
    named: list[ApiErrorField] = []
    for error in errors:
        message = error.get('msg')
        if not isinstance(message, str) or not message:
            continue
        location: object = error.get('loc', ())
        parts: Sequence[object] = (
            cast('Sequence[object]', location) if isinstance(location, (list, tuple)) else ()
        )
        named.append(
            ApiErrorField(
                field=public_field_path(parts),
                message=message,
            )
        )
        if len(named) >= MAX_ERROR_FIELDS:
            break
    return tuple(named)


def public_field_path(location: Sequence[object]) -> str:
    """Join a validation location into the dotted path a caller wrote."""
    parts: list[str] = []
    for index, part in enumerate(location):
        if isinstance(part, bool):
            continue
        if isinstance(part, int):
            parts.append(str(part))
            continue
        if not isinstance(part, str) or not part:
            continue
        if index == 0 and part in _REQUEST_SOURCES:
            continue
        if _is_internal_segment(part):
            continue
        parts.append(part)
    return '.'.join(parts)


def _is_internal_segment(part: str) -> bool:
    # Validator tags look like `function-after[...]` or `tagged-union[...]`;
    # union members are named by their model class, which starts upper case.
    return (
        any(character in part for character in '[]()<> ,')
        or part[0].isupper()
        or part.startswith('_')
    )


def _field_dict(field: ApiErrorField | Mapping[str, str]) -> dict[str, str]:
    if isinstance(field, ApiErrorField):
        return {'field': field.field, 'message': field.message}
    parsed = ApiErrorField.model_validate(dict(field))
    return {'field': parsed.field, 'message': parsed.message}


def _sorted_json(value: object) -> Any:
    if isinstance(value, Mapping):
        mapping = cast('Mapping[object, object]', value)
        return {str(key): _sorted_json(mapping[key]) for key in sorted(mapping, key=str)}
    if isinstance(value, (list, tuple)):
        return [_sorted_json(item) for item in cast('Sequence[object]', value)]
    return value


__all__ = [
    'ERROR_CODE_PATTERN',
    'MAX_ERROR_FIELDS',
    'ApiErrorBody',
    'ApiErrorField',
    'coerce_code',
    'default_error',
    'error_body',
    'is_error_body',
    'public_field_path',
    'public_sentence',
    'render_error_body',
    'validation_fields',
]
