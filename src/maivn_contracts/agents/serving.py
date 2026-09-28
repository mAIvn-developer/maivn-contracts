"""What a running process announces about itself, and how alive it is.

Owner ruling 2026-09-04: we do not host agents. Triggers are monitored by the
platform and invoke agents running in the developer's own environment, which
must be running for triggers to work. "Publishing a version" is a running SDK
process announcing itself, never uploading a definition.

**Why this is a separate contract from ``AgentVersion``.** The obvious move -
adding a digest variant to ``Instructions`` - was built and reverted: the data
plane requires ``InlineInstructions`` and raises on anything else, and the event
plane's generated struct has no digest field, so it would have been silently
discarded. It was also too narrow, because ``AgentVersion`` carries model
settings, tool schemas, skills and agent rosters *including nested prompts* -
digesting the prompt alone would not have met the ruling anyway.

So the two are split. ``AgentVersion`` remains the executable snapshot for the
later hosting product. A :class:`ServingManifest` is what a local process
announces: identity, an algorithm-tagged fingerprint of the whole runnable
definition, transport, and a deliberately small display subset. The platform can
tell *that* a running agent has drifted from what registered, and never what it
says.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictStr

PositiveStrictInt: TypeAlias = Annotated[int, Field(ge=1, strict=True)]


# How the platform reaches a serving process. `hosted_only` is deliberately
# absent: it belongs to the later hosting product, and a process announcing
# itself is by definition not hosted.
#
# A Literal rather than a StrEnum: this package holds a Python 3.10 floor
# (`requires-python = ">=3.10"`), StrEnum is 3.11+, and every other closed set
# in these contracts is spelled this way.
ServingTransport: TypeAlias = Literal['worker', 'webhook']

# How alive a served version is. `stale` and `absent` are kept apart because
# they are different problems for a developer: one process was started and
# stopped, the other was never started. Collapsing them into "not running"
# hides the more useful half.
ServingState: TypeAlias = Literal['serving', 'stale', 'absent']


class DefinitionDigest(BaseModel):
    """An algorithm-tagged fingerprint of one runnable definition.

    Tagged rather than a bare string so the algorithm can change without every
    agent silently appearing to drift: a digest computed under a different
    algorithm is recognisably different rather than merely unequal.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    algorithm: Literal['sha256-canonical-v1'] = Field(
        ...,
        description='Fingerprint algorithm. Covers instructions, model settings and tools.',
    )
    value: StrictStr = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r'^[0-9a-f]{64}$',
        description=(
            'Lowercase hex digest. Opaque to the platform, which compares it and '
            'can never resolve it back to a definition.'
        ),
    )


class ServingManifest(BaseModel):
    """One running process announcing the version it serves.

    The display fields are a deliberately small, explicitly chosen subset: a
    name, a description, and tool *names*. Not tool schemas, not instructions,
    not model settings - those are the definition, and the whole point is that
    the platform does not hold it. Anything added here should be justified as
    something a person needs to read in Studio.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(..., min_length=1, description='Stable deployed-agent id.')
    version: PositiveStrictInt = Field(..., description='Version this process serves.')
    name: StrictStr = Field(..., min_length=1, description='Human-readable agent name.')
    description: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='Optional human-readable description.',
    )
    transport: ServingTransport = Field(..., description='How the platform reaches it.')
    definition_digest: DefinitionDigest = Field(
        ...,
        description='Fingerprint of the runnable definition, for drift detection only.',
    )
    tool_names: tuple[StrictStr, ...] = Field(
        default=(),
        max_length=256,
        description='Tool names for display. Never schemas - those are definition material.',
    )
    endpoint_url: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='HTTPS endpoint for webhook transport; absent for worker transport.',
    )
    sdk_version: StrictStr | None = Field(
        default=None,
        min_length=1,
        description='SDK version of the announcing process, for support and compatibility.',
    )


class ServedVersion(BaseModel):
    """One version of one agent, and whether anything is serving it."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    version: PositiveStrictInt = Field(..., description='The agent version.')
    serving: ServingState = Field(..., description='Whether a process is alive for it.')
    last_seen_at: StrictStr | None = Field(
        default=None,
        description='RFC3339 of the last heartbeat. Null only when never announced.',
    )
    transport: ServingTransport | None = Field(
        default=None,
        description='Transport of the announcing process, when there was one.',
    )
    drifted: bool = Field(
        default=False,
        description=(
            'Whether the running definition differs from what registered. A digest can '
            'say that it differs, never what differs.'
        ),
    )


class ServedAgent(BaseModel):
    """One agent in a project, with every version anything has served."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    agent_id: StrictStr = Field(..., min_length=1)
    name: StrictStr = Field(..., min_length=1)
    versions: tuple[ServedVersion, ...] = Field(
        default=(),
        description='May be empty: an agent known to the project but never served.',
    )


__all__ = [
    'DefinitionDigest',
    'ServedAgent',
    'ServedVersion',
    'ServingManifest',
    'ServingState',
    'ServingTransport',
]
