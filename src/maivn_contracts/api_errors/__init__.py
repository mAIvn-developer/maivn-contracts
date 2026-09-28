"""The one error envelope every public mAIvn API reply carries."""

from __future__ import annotations

from maivn_contracts.api_errors.envelope import (
    ERROR_CODE_PATTERN,
    MAX_ERROR_FIELDS,
    ApiErrorBody,
    ApiErrorField,
    coerce_code,
    default_error,
    error_body,
    is_error_body,
    public_field_path,
    public_sentence,
    render_error_body,
    validation_fields,
)

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
