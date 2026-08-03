"""QAbstractListModel for paragraph diff blocks."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from ai_novel_studio.ui_qml.bridge.paragraph_diff import ParagraphDiffBlock

ROLE_BLOCK_ID = Qt.ItemDataRole.UserRole + 1
ROLE_KIND = Qt.ItemDataRole.UserRole + 2
ROLE_CURRENT_TEXT = Qt.ItemDataRole.UserRole + 3
ROLE_DRAFT_TEXT = Qt.ItemDataRole.UserRole + 4

_INVALID_INDEX = QModelIndex()


class DraftDiffModel(QAbstractListModel):
    """Exposes diff blocks to QML; rebuilt on each accept/reject action."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._blocks: list[ParagraphDiffBlock] = []

    def set_blocks(self, blocks: Sequence[ParagraphDiffBlock]) -> None:
        self.beginResetModel()
        self._blocks = list(blocks)
        self.endResetModel()

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX
    ) -> int:
        return 0 if parent.isValid() else len(self._blocks)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._blocks)):
            return None
        block = self._blocks[index.row()]
        if role == ROLE_BLOCK_ID:
            return block.block_id
        if role == ROLE_KIND:
            return block.kind
        if role == ROLE_CURRENT_TEXT:
            return block.current_text
        if role == ROLE_DRAFT_TEXT:
            return block.draft_text
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            ROLE_BLOCK_ID: QByteArray(b"blockId"),
            ROLE_KIND: QByteArray(b"kind"),
            ROLE_CURRENT_TEXT: QByteArray(b"currentText"),
            ROLE_DRAFT_TEXT: QByteArray(b"draftText"),
        }

    def blocks(self) -> tuple[ParagraphDiffBlock, ...]:
        return tuple(self._blocks)

