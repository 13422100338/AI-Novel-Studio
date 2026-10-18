"""Reserved streaming buffer for the Agent timeline.

Real model streams are high-frequency token events. To keep QML layouts
stable, chunks are buffered here and merged into the timeline model every
33-50ms with a precise ``dataChanged`` update instead of appending or resetting
the whole list (ideal-UI spec 10.3/10.4/18.7).

Contract for the future backend wiring point:

1. The backend emits discrete events (``append_item``) for structure and
   token chunks (``accept_chunk``) for running assistant text.
2. Every event carries ``run_id``, ``item_id`` and a monotonic
   ``sequence_number`` so late chunks from an old run are dropped.
3. The buffer belongs to one ``run_id``; a new run creates a new buffer and
   calls ``drop_run()`` on the old one after cancel or chapter switch.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer

from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import (
    AgentTimelineModel,
)


@dataclass(slots=True)
class _PendingText:
    buffer: str = ""
    last_sequence: int = 0
    dirty: bool = False


class StreamingTimelineBuffer(QObject):
    """Accumulates token chunks and flushes them into one timeline item."""

    def __init__(
        self,
        model: AgentTimelineModel,
        run_id: str,
        *,
        flush_interval_ms: int = 40,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._run_id = run_id
        self._flush_interval_ms = flush_interval_ms
        self._pending: dict[str, _PendingText] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(flush_interval_ms)
        self._timer.timeout.connect(self.flush)
        self._timer.start()

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def flush_interval_ms(self) -> int:
        return self._flush_interval_ms

    def accept_chunk(
        self,
        run_id: str,
        item_id: str,
        sequence_number: int,
        text: str,
    ) -> bool:
        """Buffer one token chunk; False when stale or from another run."""
        if run_id != self._run_id or not text:
            return False
        pending = self._pending.get(item_id)
        if pending is None:
            pending = _PendingText(last_sequence=sequence_number - 1)
            self._pending[item_id] = pending
        if sequence_number <= pending.last_sequence:
            # Stale or out-of-order chunk from an old/duplicated emission.
            return False
        pending.last_sequence = sequence_number
        pending.buffer += text
        pending.dirty = True
        return True

    def flush(self) -> int:
        """Merge buffered chunks into the model; returns updated item count."""
        updated = 0
        for item_id, pending in list(self._pending.items()):
            if not pending.dirty:
                continue
            if self._model.update_item(item_id, text=pending.buffer):
                # The buffer stays cumulative; the model now mirrors it.
                pending.dirty = False
                updated += 1
            else:
                # The item vanished (run ended/cleared): drop the rest too.
                self._pending.pop(item_id, None)
        return updated

    def drop_run(self) -> None:
        """Discard pending chunks for a cancelled or superseded run."""
        self._pending.clear()

    def pending_count(self) -> int:
        return sum(1 for pending in self._pending.values() if pending.dirty)
