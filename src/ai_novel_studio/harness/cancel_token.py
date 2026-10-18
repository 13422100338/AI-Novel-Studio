from __future__ import annotations

import threading

from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import HarnessRun, RunStage


class CancellationError(RuntimeError):
    """Raised when a cooperative checkpoint observes a cancellation request."""


class CancelToken:
    """Thread-safe cancellation flag for one run (design v0.3 §54).

    Cancellation is one-way and permanent: once requested it can never be
    reset, so a cancelled run cannot silently resurrect.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancellationError("run was cancelled")


def cancel_run(
    store: HarnessEventStore, run_id: str, token: CancelToken
) -> HarnessRun:
    """Cancel a run deterministically (design v0.3 §54).

    Requests the token first (streams observe it), then closes the run entry
    so the event store rejects late events and the permission gateway denies
    further tool calls. Idempotent for an already CANCELLED run.
    """
    token.request()
    return store.transition(run_id, RunStage.CANCELLED)
