"""One canonical fingerprint of a runnable agent definition.

Two sides compute this - the SDK from what it is about to run, and the platform
from what it stored - and a fingerprint two implementations compute differently
is worse than none, because it reports drift that is not there. One writer, one
algorithm, both callers import it.

**Why the whole definition and not just the prompt.** Owner ruling 2026-09-04:
fingerprint instructions, model settings and the tool list together, so a tool
added locally shows as drift too. An edited prompt and an added tool both change
what the agent can actually do.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

from maivn_contracts.agents.serving import DefinitionDigest

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Bumping this makes every fingerprint change at once and visibly, rather than
# letting an algorithm change look like every agent drifting on the same day.
FINGERPRINT_ALGORITHM = 'sha256-canonical-v1'


def definition_digest(
    *,
    instructions: str,
    model: Mapping[str, object],
    tool_names: Iterable[str],
) -> DefinitionDigest:
    """Fingerprint one runnable definition.

    The instruction text is hashed here and immediately discarded: this function
    is the only place the prompt is touched, and only its digest leaves.

    Canonical JSON with sorted keys rather than concatenated fields, so two
    different definitions can never collide because one value happened to
    contain whatever separator a naive join picked - JSON's own escaping keeps
    the boundaries unambiguous whatever the content. Tool names are sorted, so
    the order a developer happens to declare them in is not itself drift.
    """
    canonical = json.dumps(
        {
            'algorithm': FINGERPRINT_ALGORITHM,
            'instructions': sha256(instructions.encode('utf-8')).hexdigest(),
            'model': model,
            'tools': sorted(tool_names),
        },
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return DefinitionDigest(
        algorithm=FINGERPRINT_ALGORITHM,
        value=sha256(canonical.encode('utf-8')).hexdigest(),
    )


def digests_differ(left: DefinitionDigest, right: DefinitionDigest) -> bool:
    """Whether two digests describe different definitions.

    Digests under different algorithms are treated as *not* differing, because
    they are not comparable: reporting drift on an algorithm change would light
    up every agent at once and teach the operator to ignore the signal. An
    algorithm change is a migration, not a drift event.
    """
    if left.algorithm != right.algorithm:
        return False
    return left.value != right.value


__all__ = [
    'FINGERPRINT_ALGORITHM',
    'definition_digest',
    'digests_differ',
]
