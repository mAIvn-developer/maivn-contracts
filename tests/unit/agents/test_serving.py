# pyright: strict
"""Unit contracts for what a running process announces about itself (TR1)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from maivn_contracts.agents import (
    FINGERPRINT_ALGORITHM,
    DefinitionDigest,
    ServedAgent,
    ServedVersion,
    ServingManifest,
    definition_digest,
    digests_differ,
)

_MODEL: dict[str, object] = {'response': {'tier': 'balanced'}}
_DIGEST_HEX_LENGTH = 64


def _digest(**overrides: object) -> DefinitionDigest:
    base: dict[str, object] = {
        'instructions': 'You triage support mail.',
        'model': _MODEL,
        'tool_names': ['classify', 'reply'],
    }
    base.update(overrides)
    return definition_digest(**base)  # pyright: ignore[reportArgumentType]


def test_the_same_definition_always_fingerprints_the_same() -> None:
    """Two sides compute this independently; disagreement would report drift that is not there."""
    assert _digest() == _digest()


def test_tool_order_is_not_drift_but_a_new_tool_is() -> None:
    """The order a developer declares tools in is not a change to what the agent can do.

    Adding one is. The owner asked for the whole runnable definition to be
    fingerprinted precisely so a tool added locally shows up.
    """
    assert _digest(tool_names=['reply', 'classify']) == _digest()
    assert _digest(tool_names=['classify', 'reply', 'escalate']) != _digest()


def test_an_edited_prompt_or_a_changed_model_is_drift() -> None:
    """Both change what the agent actually does, so both must show."""
    assert _digest(instructions='You triage support mail. Be terse.') != _digest()
    assert _digest(model={'response': {'tier': 'max'}}) != _digest()


def test_the_prompt_is_not_recoverable_from_the_digest() -> None:
    """The whole point: the platform holds this and can never read the instructions.

    Not a cryptographic proof - a hash is a hash - but it pins that the digest
    carries no prefix, no length, and nothing but 64 hex characters, so nothing
    of the prompt travels alongside it.
    """
    digest = _digest()

    assert digest.algorithm == FINGERPRINT_ALGORITHM
    assert len(digest.value) == _DIGEST_HEX_LENGTH
    assert set(digest.value) <= set('0123456789abcdef')
    assert 'triage' not in digest.model_dump_json()


def test_digests_under_different_algorithms_are_not_reported_as_drift() -> None:
    """An algorithm change is a migration, not every agent drifting on the same day.

    Reporting drift then would light up every row at once and teach the operator
    to ignore the signal, which costs more than the missed comparison.
    """
    left = _digest()
    right = left.model_copy(update={'algorithm': 'sha256-canonical-v0'})

    assert digests_differ(left, right) is False
    assert digests_differ(left, left.model_copy(update={'value': '0' * 64})) is True


def test_a_manifest_carries_display_metadata_but_never_the_definition() -> None:
    """Tool names are for a person to read; schemas and instructions are definition."""
    manifest = ServingManifest(
        agent_id='sample-agent',
        version=1,
        name='Sample agent',
        transport='worker',
        definition_digest=_digest(),
        tool_names=('classify', 'reply'),
    )

    dumped = manifest.model_dump()
    assert set(dumped) == {
        'agent_id',
        'version',
        'name',
        'description',
        'transport',
        'definition_digest',
        'tool_names',
        'endpoint_url',
        'sdk_version',
    }
    assert 'instructions' not in dumped
    assert 'tools_snapshot' not in dumped
    assert 'model' not in dumped


def test_a_manifest_refuses_a_malformed_digest() -> None:
    """Uppercase, short, and non-hex are all rejected at the boundary."""
    for bad in ('', 'not-hex', 'A' * 64, '0' * 63):
        with pytest.raises(ValidationError):
            _ = DefinitionDigest(algorithm=FINGERPRINT_ALGORITHM, value=bad)


def test_serving_state_keeps_stale_and_absent_apart() -> None:
    """Different problems: one process stopped, the other never started."""
    stale = ServedVersion(version=1, serving='stale', last_seen_at='2026-09-04T10:00:00Z')
    absent = ServedVersion(version=2, serving='absent')

    assert stale.last_seen_at is not None
    assert absent.last_seen_at is None
    assert stale.serving != absent.serving


def test_an_agent_may_be_known_but_never_served() -> None:
    """An agent record can exist with nothing ever having announced itself for it."""
    agent = ServedAgent(agent_id='sample-agent', name='Sample agent')

    assert agent.versions == ()


def test_the_serving_contracts_stay_within_the_python_310_floor() -> None:
    """Keep these modules inside the package's declared Python 3.10 floor.

    `requires-python = ">=3.10"`, and pyright targets 3.10.

    `StrEnum` is 3.11+, and the first draft of this module used it - caught by
    the type lane rather than by a test, and only because the floor happens to
    be configured. This asserts it directly, since the next person will reach
    for `StrEnum` too.
    """
    for name in ('serving.py', 'fingerprint.py'):
        module = Path(__file__).parents[3] / 'src' / 'maivn_contracts' / 'agents' / name
        source = module.read_text(encoding='utf-8')
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)

        assert 'StrEnum' not in imported, name
