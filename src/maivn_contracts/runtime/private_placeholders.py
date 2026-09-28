"""Canonical private-data placeholder syntax, shared by the brain and the SDK.

# pyright: strict

A private value never reaches the server. The brain substitutes the real value
with a `{_{key}_}` token, reasons over the token, and hands any resulting tool
call back with the token still in it. Whoever executes that call inside the
developer's own process - the SDK - has to turn the token back into the value.

Both halves therefore have to agree, exactly, on what a placeholder looks like.
They used to agree by coincidence: the brain owned the only copy of the pattern
and the SDK had none at all, so the SDK never substituted anything and an MCP
fetch tool was handed the literal string `{_{alpha_url}_}` to parse as a URL.
The definition lives here, in the package both sides already depend on, so a
change to the syntax cannot land on one side only.
"""

from __future__ import annotations

import re

# A placeholder is `{_{key}_}`. The inner key cannot itself contain braces, which
# is what keeps a placeholder from swallowing an adjacent one.
PLACEHOLDER_PATTERN = re.compile(r'\{_\{([^{}]+)\}_\}')

_MAX_UNWRAP_PASSES = 2


def normalize_placeholder_key(raw_key: str) -> str:
    """Normalize placeholder key spellings to the raw private-data key.

    Models reproduce a placeholder approximately: they add quotes, double the
    braces, or prefix the key with `$`. Each of those spellings names the same
    private value, so all of them have to normalize to the same key or the value
    silently fails to resolve.
    """
    key = raw_key.strip()

    for _ in range(_MAX_UNWRAP_PASSES):
        if key.startswith('"') and key.endswith('"'):
            key = key[1:-1].strip()
            continue
        if key.startswith('{') and key.endswith('}'):
            key = key[1:-1].strip()
            continue
        break

    if key.startswith('"') and key.endswith('"'):
        key = key[1:-1].strip()

    if key.startswith('$'):
        key = key[1:].strip()

    return key


#: Prefix the server puts on a key derived from a name the CALLER supplied, so a
#: caller-chosen name can never squat a slot the auto-allocator will hand out.
CALLER_NAMED_KEY_PREFIX = 'user_'

_NON_KEY_CHARACTERS = re.compile(r'[^a-z0-9_]')
_FALLBACK_KEY_NAME = 'custom'


def sanitize_private_key_name(name: str) -> str:
    """Reduce a caller-supplied private-value name to its canonical key spelling.

    The server turns a name the caller attached to a private value into a key by
    lowercasing it, replacing anything outside `[a-z0-9_]`, and prefixing
    `user_`. The caller then gets tool calls naming that key - `{_{user_claim_id}_}`
    for a value it supplied as `claim_id` - and has to recognise it to substitute
    the value back. Both halves therefore have to spell the derivation the same
    way, which is why it lives here beside the placeholder pattern rather than in
    either one.
    """
    sanitized = _NON_KEY_CHARACTERS.sub('_', name.strip().lower()).strip('_')
    return sanitized or _FALLBACK_KEY_NAME


def caller_named_key_candidates(key: str) -> tuple[str, ...]:
    """Return the spellings of ``key`` a caller-side private map might hold.

    Ordered most literal first: an exact key always wins over a derived one, so a
    caller whose own map genuinely contains `user_claim_id` keeps that value.
    """
    candidates = [key]
    if key.startswith(CALLER_NAMED_KEY_PREFIX):
        stripped = key[len(CALLER_NAMED_KEY_PREFIX) :]
        if stripped:
            candidates.append(stripped)
    return tuple(dict.fromkeys(candidates))


__all__ = [
    'CALLER_NAMED_KEY_PREFIX',
    'PLACEHOLDER_PATTERN',
    'caller_named_key_candidates',
    'normalize_placeholder_key',
    'sanitize_private_key_name',
]
