"""Typed protocol for owned runtime implementations and consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from maivn_contracts.runtime.model import (
        CancelCommand,
        Command,
        RunConfig,
        RunState,
        StreamMode,
        StreamPart,
    )


@runtime_checkable
class RuntimeProtocol(Protocol):
    """Boundary interface for thread management, execution, streaming, and cancellation."""

    async def create_thread(self) -> RunState:
        """Create a runtime thread and return its initial state snapshot."""
        ...

    async def get_state(self, thread_id: str) -> RunState:
        """Return the current state snapshot for a thread."""
        ...

    async def wait(self, command: Command, config: RunConfig) -> RunState:
        """Run or resume until the runtime reaches a queryable state."""
        ...

    def stream(
        self,
        command: Command,
        config: RunConfig,
        stream_modes: Sequence[StreamMode] = ('updates',),
    ) -> AsyncIterator[StreamPart]:
        """Stream runtime parts for a start or resume command."""
        ...

    async def cancel(self, command: CancelCommand, config: RunConfig) -> RunState:
        """Cancel a running invocation and return the resulting state."""
        ...
