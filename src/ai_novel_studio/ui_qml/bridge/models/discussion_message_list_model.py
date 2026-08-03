"""QAbstractListModel for the plot-discussion message history."""

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

from ai_novel_studio.ui_qml.bridge.dtos import DiscussionMessageDto

ROLE_MESSAGE_ID = Qt.ItemDataRole.UserRole + 1
ROLE_ROLE = Qt.ItemDataRole.UserRole + 2
ROLE_TEXT = Qt.ItemDataRole.UserRole + 3

_INVALID_INDEX = QModelIndex()


class DiscussionMessageListModel(QAbstractListModel):
    """Exposes discussion bubbles to QML; mutated on the UI thread."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[DiscussionMessageDto] = []

    def set_items(self, items: Sequence[DiscussionMessageDto]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def add_message(self, message: DiscussionMessageDto) -> None:
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(message)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX
    ) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == ROLE_MESSAGE_ID:
            return item.id
        if role == ROLE_ROLE:
            return item.role
        if role == ROLE_TEXT:
            return item.text
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            ROLE_MESSAGE_ID: QByteArray(b"messageId"),
            ROLE_ROLE: QByteArray(b"role"),
            ROLE_TEXT: QByteArray(b"text"),
        }

    def messages(self) -> tuple[DiscussionMessageDto, ...]:
        return tuple(self._items)
