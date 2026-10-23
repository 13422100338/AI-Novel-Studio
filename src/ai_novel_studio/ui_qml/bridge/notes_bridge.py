"""Author notebook UI state and explicit per-writing selection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from ai_novel_studio.core.outline_markdown import apply_editor_edit, editor_text, outline_headings
from ai_novel_studio.domain.author_note import NOTE_KINDS, AuthorNote, NoteSelection
from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class NotesBridge(QObject):
    changed = Signal()
    selection_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._repository: NoteRepository | None = None
        self._key: tuple[Path, str] | None = None
        self._base: AuthorNote | None = None
        self._buffer = ""
        self._selection = NoteSelection()
        self._state = self._empty()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "available": False,
            "loaded": False,
            "documents": [],
            "currentId": "",
            "title": "",
            "text": "",
            "kind": "OTHER",
            "revision": 0,
            "dirty": False,
            "status": "请打开小说项目",
            "error": "",
            "headings": [],
            "versions": [],
            "previewText": "",
            "previewRevision": 0,
            "recoveries": [],
            "mode": "NONE",
            "selectedIds": [],
        }

    @Property(dict, notify=changed)
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    @property
    def current_selection(self) -> NoteSelection:
        return self._selection

    @property
    def editor_context(self) -> tuple[str, bool]:
        return self._state["currentId"], self._state["dirty"]

    def bind_project(self, project: ProjectRepository | None) -> None:
        key = (project.layout.root, project.project.id) if project else None
        if key == self._key:
            if project:
                self.refresh()
            return
        self._key = key
        self._repository = NoteRepository(project) if project else None
        self._base, self._buffer = None, ""
        self._selection = NoteSelection()
        self._state = self._empty()
        self._state.update(available=project is not None, status="新建笔记，或导入 Markdown")
        if project:
            self.refresh()
        self.changed.emit()
        self.selection_changed.emit()

    def _require(self) -> NoteRepository:
        if self._repository is None:
            raise ValueError("请先打开小说项目")
        return self._repository

    def _attempt(self, action: Callable[[], object]) -> bool:
        try:
            action()
        except ValueError as exc:
            self._state["error"] = str(exc)
        except FileExistsError:
            self._state["error"] = "目标文件或修订已存在，未覆盖；请选择新文件或重新载入"
        except OSError:
            self._state["error"] = "笔记操作失败，请检查文件权限；当前编辑保留"
        else:
            self._state["error"] = ""
            self.changed.emit()
            return True
        self.changed.emit()
        return False

    def _adopt(self, note: AuthorNote) -> None:
        self._base, self._buffer = note, note.content
        self._state.update(
            currentId=note.id,
            title=note.title,
            kind=note.kind,
            text=editor_text(note.content),
            revision=note.revision,
            dirty=False,
            loaded=True,
            status="已保存",
            headings=outline_headings(note.content),
            versions=list(range(1, note.revision + 1)),
        )

    @Slot(result=bool)
    def refresh(self) -> bool:
        def action() -> None:
            notes = self._require().list_notes()
            self._state["documents"] = [{**note.summary(), "id": note.id} for note in notes]
            self._state["recoveries"] = self._require().recoveries()
            current = next((n for n in notes if n.id == self._state["currentId"]), None)
            if self._base is None and notes:
                self._adopt(notes[0])
            elif current and not self._state["dirty"]:
                self._adopt(current)
            elif current and self._base and current.revision != self._base.revision:
                raise ValueError("笔记已有新修订，本地编辑保留；可导出副本或重新载入")

        return self._attempt(action)

    @Slot(str, str, result=bool)
    def createNote(self, title: str, kind: str = "OTHER") -> bool:
        if not self.flush():
            return False

        def action() -> None:
            self._adopt(self._require().create(title, "", kind=kind))

        return self._attempt(action) and self.refresh()

    @Slot(str, result=bool)
    def selectDocument(self, identity: str) -> bool:
        if not self.flush():
            return False
        return self._attempt(lambda: self._adopt(self._require().read(identity)))

    def _dirty(self) -> None:
        if self._base is None:
            return
        dirty = (self._buffer, self._state["title"], self._state["kind"]) != (
            self._base.content,
            self._base.title,
            self._base.kind,
        )
        self._state.update(dirty=dirty, status="未保存" if dirty else "已保存")
        self.changed.emit()

    @Slot(str)
    def edit(self, text: str) -> None:
        if self._base is None:
            return
        updated = apply_editor_edit(self._buffer, text)
        if updated == self._buffer:
            return
        self._buffer = updated
        self._state.update(text=editor_text(updated), headings=outline_headings(updated))
        self._dirty()

    @Slot(str)
    def setTitle(self, title: str) -> None:
        self._state["title"] = title
        self._dirty()

    @Slot(str)
    def setKind(self, kind: str) -> None:
        if kind in NOTE_KINDS:
            self._state["kind"] = kind
            self._dirty()

    @Slot(result=bool)
    def flush(self) -> bool:
        if not self._state["dirty"] or self._base is None:
            return True

        def action() -> None:
            assert self._base is not None
            note = self._require().save(
                self._base.id,
                self._buffer,
                expected_revision=self._base.revision,
                title=self._state["title"],
                kind=self._state["kind"],
            )
            self._adopt(note)

        return self._attempt(action) and self.refresh()

    @Slot(result=bool)
    def reload(self) -> bool:
        return self._attempt(lambda: self._adopt(self._require().read(self._state["currentId"])))

    def _select(self, selection: NoteSelection) -> None:
        self._selection = selection
        self._state.update(mode=selection.mode, selectedIds=list(selection.ids))
        self.selection_changed.emit()

    @Slot(str, bool, result=bool)
    def toggleSelected(self, identity: str, selected: bool) -> bool:
        def action() -> None:
            ids = list(self._selection.ids)
            if selected:
                self._require().read(identity)
                if identity not in ids:
                    ids.append(identity)
            elif identity in ids:
                ids.remove(identity)
            self._select(
                NoteSelection(
                    (self._selection.mode if self._selection.mode != "NONE" else "FULL")
                    if ids
                    else "NONE",
                    tuple(ids),
                )
            )

        return self._attempt(action)

    @Slot(str, result=bool)
    def setMode(self, mode: str) -> bool:
        return self._attempt(
            lambda: self._select(NoteSelection(mode, () if mode == "NONE" else self._selection.ids))
        )

    @staticmethod
    def _local(url: QUrl) -> Path:
        if not url.isLocalFile() or not url.toLocalFile():
            raise ValueError("请选择本地 Markdown 或文本文件")
        return Path(url.toLocalFile())

    @Slot(QUrl, result=bool)
    def importFile(self, url: QUrl) -> bool:
        if not self.flush():
            return False

        def action() -> None:
            path = self._local(url)
            if path.stat().st_size > 1_048_576:
                raise ValueError("导入笔记超过1MiB，未截断")
            raw = path.read_bytes().decode("utf-8")
            self._adopt(self._require().create(path.stem, raw))

        return self._attempt(action) and self.refresh()

    @Slot(QUrl, result=bool)
    def exportFile(self, url: QUrl) -> bool:
        def action() -> None:
            if self._base is None:
                raise ValueError("请先选择笔记")
            with self._local(url).open("xb") as stream:
                stream.write(self._buffer.encode("utf-8"))

        return self._attempt(action)

    @Slot(int, result=bool)
    def previewVersion(self, revision: int) -> bool:
        def action() -> None:
            note = self._require().read(self._state["currentId"], revision=revision)
            self._state.update(previewText=note.content, previewRevision=revision)

        return self._attempt(action)

    @Slot(int, result=bool)
    def restoreVersion(self, revision: int) -> bool:
        if not self.flush():
            return False

        def action() -> None:
            assert self._base is not None
            old = self._require().read(self._base.id, revision=revision)
            note = self._require().save(
                old.id,
                old.content,
                expected_revision=self._base.revision,
                title=old.title,
                kind=old.kind,
            )
            self._adopt(note)

        return self._attempt(action) and self.refresh()

    @Slot(str, bool, result=bool)
    def recoverSaving(self, name: str, restore: bool) -> bool:
        return (
            self._attempt(lambda: self._require().recover(name, restore=restore)) and self.refresh()
        )
