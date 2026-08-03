"""QAbstractListModel adapters for the three read-only page lists."""

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

from ai_novel_studio.ui_qml.bridge.readonly_views import (
    AuditViewDto,
    CharacterJourneyViewDto,
    CharacterViewDto,
    MemoryViewDto,
)

_INVALID_INDEX = QModelIndex()


class CharacterListModel(QAbstractListModel):
    ROLE_ID = Qt.ItemDataRole.UserRole + 1
    ROLE_NAME = Qt.ItemDataRole.UserRole + 2
    ROLE_PROFILE = Qt.ItemDataRole.UserRole + 3
    ROLE_MOTIVATION = Qt.ItemDataRole.UserRole + 4
    ROLE_GOAL = Qt.ItemDataRole.UserRole + 5
    ROLE_RECENT = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[CharacterViewDto] = []

    def character_at_row(self, row: int) -> CharacterViewDto | None:
        if not (0 <= row < len(self._items)):
            return None
        return self._items[row]

    def set_items(self, items: Sequence[CharacterViewDto]) -> None:
        self.beginResetModel()
        self._items = list(items)
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
        if role == self.ROLE_ID:
            return item.id
        if role == self.ROLE_NAME:
            return item.name
        if role == self.ROLE_PROFILE:
            return item.profile
        if role == self.ROLE_MOTIVATION:
            return item.motivation
        if role == self.ROLE_GOAL:
            return item.goal
        if role == self.ROLE_RECENT:
            return item.recent
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.ROLE_ID: QByteArray(b"characterId"),
            self.ROLE_NAME: QByteArray(b"name"),
            self.ROLE_PROFILE: QByteArray(b"profile"),
            self.ROLE_MOTIVATION: QByteArray(b"motivation"),
            self.ROLE_GOAL: QByteArray(b"goal"),
            self.ROLE_RECENT: QByteArray(b"recent"),
        }


class CharacterJourneyListModel(QAbstractListModel):
    ROLE_STATE_ID = Qt.ItemDataRole.UserRole + 1
    ROLE_CHAPTER_ID = Qt.ItemDataRole.UserRole + 2
    ROLE_MOTIVATION = Qt.ItemDataRole.UserRole + 3
    ROLE_PSYCHOLOGY = Qt.ItemDataRole.UserRole + 4
    ROLE_GOAL = Qt.ItemDataRole.UserRole + 5
    ROLE_RELATIONSHIPS = Qt.ItemDataRole.UserRole + 6
    ROLE_RECENT = Qt.ItemDataRole.UserRole + 7

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[CharacterJourneyViewDto] = []

    def set_items(self, items: Sequence[CharacterJourneyViewDto]) -> None:
        self.beginResetModel()
        self._items = list(items)
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
        if role == self.ROLE_STATE_ID:
            return item.state_id
        if role == self.ROLE_CHAPTER_ID:
            return item.chapter_id
        if role == self.ROLE_MOTIVATION:
            return item.motivation
        if role == self.ROLE_PSYCHOLOGY:
            return item.psychology
        if role == self.ROLE_GOAL:
            return item.goal
        if role == self.ROLE_RELATIONSHIPS:
            return item.relationships
        if role == self.ROLE_RECENT:
            return item.recent_activity
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.ROLE_STATE_ID: QByteArray(b"stateId"),
            self.ROLE_CHAPTER_ID: QByteArray(b"chapterId"),
            self.ROLE_MOTIVATION: QByteArray(b"motivation"),
            self.ROLE_PSYCHOLOGY: QByteArray(b"psychology"),
            self.ROLE_GOAL: QByteArray(b"goal"),
            self.ROLE_RELATIONSHIPS: QByteArray(b"relationships"),
            self.ROLE_RECENT: QByteArray(b"recent"),
        }


class MemoryListModel(QAbstractListModel):
    ROLE_ID = Qt.ItemDataRole.UserRole + 1
    ROLE_CATEGORY = Qt.ItemDataRole.UserRole + 2
    ROLE_TITLE = Qt.ItemDataRole.UserRole + 3
    ROLE_CONTENT = Qt.ItemDataRole.UserRole + 4
    ROLE_SOURCE_TYPE = Qt.ItemDataRole.UserRole + 5
    ROLE_REVIEW = Qt.ItemDataRole.UserRole + 6
    ROLE_STATUS = Qt.ItemDataRole.UserRole + 7
    ROLE_REVISION = Qt.ItemDataRole.UserRole + 8

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[MemoryViewDto] = []

    def set_items(self, items: Sequence[MemoryViewDto]) -> None:
        self.beginResetModel()
        self._items = list(items)
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
        if role == self.ROLE_ID:
            return item.id
        if role == self.ROLE_CATEGORY:
            return item.category
        if role == self.ROLE_TITLE:
            return item.title
        if role == self.ROLE_CONTENT:
            return item.content
        if role == self.ROLE_SOURCE_TYPE:
            return item.source_type
        if role == self.ROLE_REVIEW:
            return str(item.review_status)
        if role == self.ROLE_STATUS:
            return str(item.status)
        if role == self.ROLE_REVISION:
            return item.revision
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.ROLE_ID: QByteArray(b"memoryId"),
            self.ROLE_CATEGORY: QByteArray(b"category"),
            self.ROLE_TITLE: QByteArray(b"title"),
            self.ROLE_CONTENT: QByteArray(b"content"),
            self.ROLE_SOURCE_TYPE: QByteArray(b"sourceType"),
            self.ROLE_REVIEW: QByteArray(b"review"),
            self.ROLE_STATUS: QByteArray(b"status"),
            self.ROLE_REVISION: QByteArray(b"revision"),
        }


class AuditListModel(QAbstractListModel):
    ROLE_ID = Qt.ItemDataRole.UserRole + 1
    ROLE_CATEGORY = Qt.ItemDataRole.UserRole + 2
    ROLE_SEVERITY = Qt.ItemDataRole.UserRole + 3
    ROLE_EVIDENCE = Qt.ItemDataRole.UserRole + 4
    ROLE_EXPLANATION = Qt.ItemDataRole.UserRole + 5
    ROLE_CONFIDENCE = Qt.ItemDataRole.UserRole + 6
    ROLE_STATUS = Qt.ItemDataRole.UserRole + 7

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[AuditViewDto] = []

    def set_items(self, items: Sequence[AuditViewDto]) -> None:
        self.beginResetModel()
        self._items = list(items)
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
        if role == self.ROLE_ID:
            return item.id
        if role == self.ROLE_CATEGORY:
            return item.category
        if role == self.ROLE_SEVERITY:
            return item.severity
        if role == self.ROLE_EVIDENCE:
            return item.evidence
        if role == self.ROLE_EXPLANATION:
            return item.explanation
        if role == self.ROLE_CONFIDENCE:
            return item.confidence
        if role == self.ROLE_STATUS:
            return item.status
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.ROLE_ID: QByteArray(b"findingId"),
            self.ROLE_CATEGORY: QByteArray(b"category"),
            self.ROLE_SEVERITY: QByteArray(b"severity"),
            self.ROLE_EVIDENCE: QByteArray(b"evidence"),
            self.ROLE_EXPLANATION: QByteArray(b"explanation"),
            self.ROLE_CONFIDENCE: QByteArray(b"confidence"),
            self.ROLE_STATUS: QByteArray(b"status"),
        }
