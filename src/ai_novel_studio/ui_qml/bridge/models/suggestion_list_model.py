"""Mock AI suggestion list for the AI drawer vertical slice."""

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

from ai_novel_studio.ui_qml.bridge.dtos import SuggestionDto

ROLE_LABEL = Qt.ItemDataRole.UserRole + 1
ROLE_BODY = Qt.ItemDataRole.UserRole + 2
ROLE_KIND = Qt.ItemDataRole.UserRole + 3

_INVALID_INDEX = QModelIndex()


class SuggestionListModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[SuggestionDto] = []

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
        if role == ROLE_LABEL:
            return item.label
        if role == ROLE_BODY:
            return item.body
        if role == ROLE_KIND:
            return item.kind
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            ROLE_LABEL: QByteArray(b"label"),
            ROLE_BODY: QByteArray(b"body"),
            ROLE_KIND: QByteArray(b"kind"),
        }

    def add_item(self, item: SuggestionDto) -> None:
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()

    def item_at_row(self, row: int) -> SuggestionDto | None:
        if not (0 <= row < len(self._items)):
            return None
        return self._items[row]

    def remove_item(self, row: int) -> None:
        if not (0 <= row < len(self._items)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._items[row]
        self.endRemoveRows()

    def items(self) -> Sequence[SuggestionDto]:
        return tuple(self._items)
