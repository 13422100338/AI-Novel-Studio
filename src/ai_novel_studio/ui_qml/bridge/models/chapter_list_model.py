"""Flat volume/chapter list model for the context sidebar."""

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

from ai_novel_studio.ui_qml.bridge.dtos import ChapterDto, VolumeDto
from ai_novel_studio.ui_qml.bridge.text_utils import format_word_count

ROLE_CHAPTER_ID = Qt.ItemDataRole.UserRole + 1
ROLE_TITLE = Qt.ItemDataRole.UserRole + 2
ROLE_KIND = Qt.ItemDataRole.UserRole + 3
ROLE_WORD_COUNT_TEXT = Qt.ItemDataRole.UserRole + 4
ROLE_REVISION = Qt.ItemDataRole.UserRole + 5
ROLE_STATUS = Qt.ItemDataRole.UserRole + 6

_INVALID_INDEX = QModelIndex()


class ChapterListModel(QAbstractListModel):
    """Exposes volume headers and chapter rows as one flat list.

    Rows have ``kind`` ``"volume"`` (non-selectable header) or ``"chapter"``.
    Model mutations happen on the UI thread; background workers return DTOs only.
    """

    def __init__(
        self,
        volumes: Sequence[VolumeDto] = (),
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._filter_query = ""
        self._rows: list[tuple[VolumeDto | None, ChapterDto | None]] = []
        self.set_volumes(volumes)

    def set_volumes(self, volumes: Sequence[VolumeDto]) -> None:
        self.beginResetModel()
        self._volumes = tuple(volumes)
        self._rebuild_rows()
        self.endResetModel()

    def set_filter(self, query: str) -> None:
        normalized = query.strip()
        if normalized == self._filter_query:
            return
        self.beginResetModel()
        self._filter_query = normalized
        self._rebuild_rows()
        self.endResetModel()

    def _rebuild_rows(self) -> None:
        query = self._filter_query.casefold()
        self._rows = []
        for volume in self._volumes:
            if not query:
                self._rows.append((volume, None))
                self._rows.extend((None, chapter) for chapter in volume.chapters)
                continue
            matches = [chapter for chapter in volume.chapters if query in chapter.title.casefold()]
            if matches:
                self._rows.append((volume, None))
                self._rows.extend((None, chapter) for chapter in matches)

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX
    ) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        volume, chapter = self._rows[index.row()]
        if role == ROLE_CHAPTER_ID:
            return chapter.id if chapter is not None else ""
        if role == ROLE_TITLE:
            if volume is not None:
                return volume.title
            return chapter.title if chapter is not None else ""
        if role == ROLE_KIND:
            return "volume" if volume is not None else "chapter"
        if role == ROLE_WORD_COUNT_TEXT:
            return format_word_count(chapter.word_count) if chapter is not None else ""
        if role == ROLE_REVISION:
            return chapter.revision if chapter is not None else 0
        if role == ROLE_STATUS:
            return chapter.status if chapter is not None else ""
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            ROLE_CHAPTER_ID: QByteArray(b"chapterId"),
            ROLE_TITLE: QByteArray(b"title"),
            ROLE_KIND: QByteArray(b"kind"),
            ROLE_WORD_COUNT_TEXT: QByteArray(b"wordCountText"),
            ROLE_REVISION: QByteArray(b"revision"),
            ROLE_STATUS: QByteArray(b"status"),
        }

    def chapter_at_row(self, row: int) -> ChapterDto | None:
        if not (0 <= row < len(self._rows)):
            return None
        _, chapter = self._rows[row]
        return chapter

    def chapter_rows(self) -> list[int]:
        """Return flat model row indices for chapter rows only."""
        return [row for row, (_, chapter) in enumerate(self._rows) if chapter is not None]
