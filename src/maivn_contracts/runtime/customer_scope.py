"""Developer-asserted customer subjects within an authenticated project."""

from __future__ import annotations

import unicodedata

_MAX_SUBJECT_LENGTH = 256


def memory_owner_user_id(user_id: str | None) -> str | None:
    """Validate an opaque case-sensitive subject; absent/default subjects own no memory.

    This is a developer assertion, never independently verified end-user authentication.
    Derive it from an authenticated customer session on a trusted developer backend.
    """
    if user_id is None:
        return None
    if len(user_id) > _MAX_SUBJECT_LENGTH or any(
        unicodedata.category(char).startswith('C') for char in user_id
    ):
        message = 'user_id must be at most 256 characters and contain no control characters'
        raise ValueError(message)
    if not user_id.strip():
        return None
    if user_id != user_id.strip():
        message = 'user_id must not contain surrounding whitespace'
        raise ValueError(message)
    return None if user_id == 'sdk-user' else user_id
