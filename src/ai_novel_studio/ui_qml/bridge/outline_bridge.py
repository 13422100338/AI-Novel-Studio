"""Outline editing state. Model sessions and chapter buffers remain separate owners."""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from ai_novel_studio.application.outline_service import OutlineService
from ai_novel_studio.core.outline_links import insert_chapter_link
from ai_novel_studio.core.outline_markdown import apply_editor_edit, editor_text, outline_headings
from ai_novel_studio.domain.outline import OutlineSnapshot, outline_content_hash
from ai_novel_studio.domain.outline_link import OutlineLinkSnapshot
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineIntegrityError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.outline_references import build_references, reference_url


@dataclass(frozen=True, slots=True)
class _Preview:
    kind: str
    document_id: str
    expected_revision: int
    content: str
    buffer: str
    source_revision: int = 0


class OutlineBridge(QObject):
    changed = Signal()
    navigation_changed = Signal()
    chapterRequested = Signal(str)
    revealRequested = Signal(int)

    def __init__(
        self, parent: QObject | None = None, *, chapter_opener: Callable[[str], bool] | None = None
    ) -> None:
        super().__init__(parent)
        self._service: OutlineService | None = None
        self._chapter_opener = chapter_opener
        self._key: tuple[Path, str] | None = None
        self._base: OutlineSnapshot | None = None
        self._buffer = ""
        self._note_documents: list[dict[str, Any]] = []
        self._preview: _Preview | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self.flush)
        self._state = self._empty_state()
        self._source_cursor = 0
        self.changed.connect(self.navigation_changed.emit)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return dict(
            available=False,
            documents=[],
            currentId="",
            currentIndex=-1,
            title="",
            text="",
            revision=0,
            dirty=False,
            loaded=False,
            status="请打开小说项目",
            error="",
            headings=[],
            versions=[],
            previewText="",
            previewSummary="",
            previewKind="",
            links=[],
            linkFingerprint="",
            pendingLinkCount=0,
            linkChapters=[],
            linksReady=False,
            linksError="",
            linksEpoch=0,
        )

    @Property(dict, notify=changed)
    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def set_note_documents(self, documents: list[dict[str, Any]]) -> None:
        current = [{"id": n["id"], "title": n["title"]} for n in documents]
        if current != self._note_documents:
            self._note_documents = current
            self.changed.emit()

    @Property(list, notify=changed)
    def references(self) -> list[dict[str, Any]]:
        if not self._state["loaded"] or self._service is None:
            return []
        path = (
            self._service.outlines.project.layout.root
            / "outlines"
            / (self._state["currentId"] + ".md")
        )
        return build_references(
            self._state["text"],
            self._state["headings"],
            self._state["links"],
            self._state["linkChapters"],
            self._note_documents,
            path,
            dirty=self._state["dirty"],
        )

    @Property(dict, notify=navigation_changed)
    def navigation(self) -> dict[str, Any]:
        text = self._state["text"]
        prefix = text.encode("utf-16-le")[: self._source_cursor * 2].decode(
            "utf-16-le", errors="ignore"
        )
        line = prefix.count("\n") + 1
        headings = self._state["headings"]
        selected = next(
            (h for h in reversed(headings) if h["position"] <= self._source_cursor), None
        )
        start = selected["line"] if selected else 1
        end = len(text.splitlines()) + 1
        if selected:
            end = next(
                (
                    h["line"]
                    for h in headings
                    if h["line"] > start and h["level"] <= selected["level"]
                ),
                end,
            )
        titles = {c["id"]: c["title"] for c in self._state["linkChapters"]}
        order = {c["id"]: index for index, c in enumerate(self._state["linkChapters"])}
        chapters: dict[str, dict[str, Any]] = {}
        for link in self._state["links"]:
            if not link["active"] or not start <= link["line"] < end:
                continue
            chapter = chapters.setdefault(
                link["chapterId"],
                {
                    "chapterId": link["chapterId"],
                    "title": titles.get(link["chapterId"], link["chapterTitle"]),
                    "available": link["chapterAvailable"],
                    "status": link["statusText"],
                    "confirmed": True,
                    "linkCount": 0,
                },
            )
            chapter["linkCount"] += 1
            if link["status"] != "CONFIRMED":
                chapter["confirmed"] = False
                chapter["status"] = link["statusText"]
        return {
            "sourcePosition": self._source_cursor,
            "sourceLine": line,
            "headingLine": start,
            "headingTitle": selected["title"] if selected else "全篇大纲",
            "endLine": end,
            "chapters": sorted(
                chapters.values(), key=lambda chapter: order.get(chapter["chapterId"], len(order))
            ),
        }

    @Slot(int)
    def setSourceCursor(self, position: int) -> None:
        if (
            type(position) is int
            and 0 <= position <= len(self._state["text"].encode("utf-16-le")) // 2
        ):
            if position != self._source_cursor:
                self._source_cursor = position
                self.navigation_changed.emit()

    @Slot(int)
    def selectHeading(self, line: int) -> None:
        heading = next((h for h in self._state["headings"] if h["line"] == line), None)
        if heading:
            self.setSourceCursor(heading["position"])
            self.revealRequested.emit(heading["position"])

    def bind_project(self, project: ProjectRepository | None) -> None:
        """The project owner must flush successfully before changing this binding."""
        key = (project.layout.root, project.project.id) if project else None
        if key is not None and key == self._key:
            self._attempt(self._refresh_documents)
            if not self._state["currentId"] and self._state["documents"]:
                self._attempt(lambda: self._load(self._state["documents"][0]["id"]))
            elif self._state["loaded"] and not self._state["dirty"]:
                self._refresh_links()
                self.changed.emit()
            return
        self._timer.stop()
        self._source_cursor = 0
        self._note_documents = []
        self._key, self._base, self._buffer, self._preview = key, None, "", None
        self._service = OutlineService(OutlineRepository(project)) if project else None
        self._state = self._empty_state()
        self._state["available"] = project is not None
        if project:
            self._state["status"] = "导入大纲，或新建文档"
            if self._attempt(self._refresh_documents) and self._state["documents"]:
                self._attempt(lambda: self._load(self._state["documents"][0]["id"]))
        self.changed.emit()

    def _require(self) -> OutlineService:
        if self._service is None:
            raise ValueError("请先打开小说项目")
        return self._service

    def _refresh_documents(self) -> None:
        self._state["documents"] = [
            {"id": doc.id, "title": doc.title, "revision": doc.revision}
            for doc in self._require().outlines.list_documents()
        ]
        self._state["currentIndex"] = next(
            (
                i
                for i, doc in enumerate(self._state["documents"])
                if doc["id"] == self._state["currentId"]
            ),
            -1,
        )

    def _adopt(self, snapshot: OutlineSnapshot) -> None:
        repository = self._require().outlines
        document = repository.get(snapshot.version.document_id)
        if self._state["currentId"] != document.id:
            self._source_cursor = 0
        versions = repository.list_versions(document.id)
        self._timer.stop()
        self._base, self._buffer = snapshot, snapshot.content
        self._state.update(
            currentId=document.id,
            title=document.title,
            text=editor_text(snapshot.content),
            revision=snapshot.version.revision,
            dirty=False,
            loaded=True,
            status="已保存",
            headings=outline_headings(snapshot.content),
            versions=[
                {"revision": v.revision, "time": v.created_at.astimezone().strftime("%m-%d %H:%M")}
                for v in reversed(versions)
            ],
        )
        self._source_cursor = min(
            self._source_cursor, len(self._state["text"].encode("utf-16-le")) // 2
        )
        self._refresh_documents()
        self._refresh_links()

    def _link_state(self, snapshot: OutlineLinkSnapshot) -> None:
        if self._base is None or (snapshot.source_revision, snapshot.source_hash) != (
            self._base.version.revision,
            self._base.version.content_hash,
        ):
            raise OutlineConflictError("当前大纲已有新版本，请重新载入后再确认关联")
        labels = {
            "PENDING": "待确认",
            "CONFIRMED": "已确认",
            "MISSING_SOURCE": "位置待定位",
            "MISSING_CHAPTER": "章节不可用",
            "REMOVED": "已确认移除",
        }
        actions = {
            "DISCOVERED": "识别链接",
            "CONFIRMED": "确认关联",
            "RELOCATED": "重新定位（保留原位置）",
            "REMOVED": "确认移除",
        }
        chapter_ids = {chapter.id for chapter in snapshot.chapters}
        self._state.update(
            linkFingerprint=snapshot.fingerprint,
            pendingLinkCount=snapshot.pending_total,
            linksReady=True,
            linksEpoch=self._state["linksEpoch"] + 1,
            linkChapters=[
                {
                    "id": c.id,
                    "title": " ".join(p for p in (c.declared_number, c.title) if p),
                    "path": c.content_path,
                }
                for c in snapshot.chapters
            ],
            links=[
                {
                    "id": item.link.id,
                    "chapterId": item.link.chapter_id,
                    "chapterTitle": item.chapter_title,
                    "chapterAvailable": item.link.chapter_id in chapter_ids,
                    "status": item.status,
                    "statusText": labels[item.status],
                    "active": item.link.active,
                    "line": item.line or item.link.source_line,
                    "position": item.position if item.position is not None else -1,
                    "section": item.section_title,
                    "quote": item.link.source_quote[:240],
                    "history": [
                        {
                            "action": actions[r.action],
                            "revision": r.source_revision,
                            "line": r.source_line,
                            "time": r.created_at.astimezone().strftime("%m-%d %H:%M"),
                        }
                        for r in item.link.reviews
                    ],
                }
                for item in snapshot.items
            ],
        )

    def _refresh_links(self) -> bool:
        try:
            self._link_state(self._require().links.scan(self._state["currentId"]))
        except (OutlineConflictError, OutlineIntegrityError) as exc:
            message = str(exc)
        except Exception:  # noqa: BLE001 - a link-index error must not lose a saved outline
            message = "关联读取失败，请检查大纲文件并重新扫描；大纲原文保留。"
        else:
            self._state["linksError"] = ""
            return True
        self._state.update(linksReady=False, linksError=message, links=[], linkFingerprint="")
        return False

    def _load(self, document_id: str) -> None:
        repository = self._require().outlines
        document = repository.get(document_id)
        try:
            snapshot = repository.read(document_id)
        except OutlineIntegrityError:
            # The previous buffer has been flushed; never show it under a new title.
            self._base, self._buffer = None, ""
            self._state.update(
                currentId=document.id,
                title=document.title,
                text="",
                revision=document.revision,
                dirty=False,
                loaded=False,
                headings=[],
                versions=[],
                links=[],
                linksReady=False,
                linkFingerprint="",
                pendingLinkCount=0,
            )
            self._refresh_documents()
            raise
        self._adopt(snapshot)

    def _attempt(self, action: Callable[[], None]) -> bool:
        try:
            action()
        except (OutlineConflictError, OutlineIntegrityError) as exc:
            self._state["error"] = str(exc)
        except FileExistsError:
            self._state["error"] = "目标文件已存在，请选择新文件名；原文件未被覆盖。"
        except (ValueError, KeyError):
            self._state["error"] = "操作未完成，请检查文档、标题、UTF-8 编码和版本后重试。"
        except Exception:  # noqa: BLE001 - never expose paths, SQL or author text
            self._state["error"] = "操作失败，请检查文件权限或项目状态。当前编辑未清除。"
        else:
            self._state["error"] = ""
            self.changed.emit()
            return True
        self.changed.emit()
        return False

    @staticmethod
    def _local_path(url: QUrl) -> Path:
        if not url.isLocalFile() or not url.toLocalFile():
            raise ValueError("只接受作者选择的本地文件")
        return Path(url.toLocalFile())

    @Slot(str)
    def edit(self, text: str) -> None:
        if not self._state["loaded"] or self._base is None:
            return
        updated = apply_editor_edit(self._buffer, text)
        if updated == self._buffer:
            return
        self._buffer = updated
        self._state.update(
            text=editor_text(updated),
            dirty=updated != self._base.content,
            headings=outline_headings(updated),
            status="等待保存" if updated != self._base.content else "已保存",
        )
        if self._state["dirty"]:
            self._timer.start()
        else:
            self._timer.stop()
        self._source_cursor = min(
            self._source_cursor, len(self._state["text"].encode("utf-16-le")) // 2
        )
        self.changed.emit()

    @Slot(result=bool)
    def flush(self) -> bool:
        self._timer.stop()
        if not self._state["dirty"]:
            return True

        def save() -> None:
            if self._base is None:
                raise ValueError("大纲尚未载入")
            self._adopt(
                self._require().outlines.save(
                    self._base.version.document_id,
                    self._buffer,
                    expected_revision=self._base.version.revision,
                )
            )

        return self._attempt(save)

    @Slot(str, result=bool)
    def selectDocument(self, document_id: str) -> bool:
        if document_id == self._state["currentId"]:
            return True
        return self.flush() and self._attempt(lambda: self._load(document_id))

    @Slot(str, result=bool)
    def newDocument(self, title: str) -> bool:
        return self.flush() and self._attempt(
            lambda: self._adopt(self._require().outlines.create(title))
        )

    @Slot(QUrl, result=bool)
    def importFile(self, url: QUrl) -> bool:
        return self.flush() and self._attempt(
            lambda: self._adopt(self._require().import_file(self._local_path(url)))
        )

    @Slot(QUrl, result=bool)
    def exportFile(self, url: QUrl) -> bool:
        def export() -> None:
            if not self._state["loaded"]:
                raise ValueError("大纲尚未载入")
            self._require().export_text(self._buffer, self._local_path(url))
            self._state["status"] = "当前编辑已导出副本"

        return self._attempt(export)

    @Slot(int, result=bool)
    def moveDocument(self, direction: int) -> bool:
        if not self.flush():
            return False

        def move() -> None:
            order = tuple(d.id for d in self._require().outlines.list_documents())
            index = order.index(self._state["currentId"])
            other = index + direction
            if direction not in {-1, 1} or not 0 <= other < len(order):
                return
            reordered = list(order)
            reordered[index], reordered[other] = reordered[other], reordered[index]
            self._require().outlines.reorder(tuple(reordered), expected_order=order)
            self._refresh_documents()
            self._refresh_links()

        return self._attempt(move)

    @Slot(bool, result=bool)
    def reloadDocument(self, discard: bool = False) -> bool:
        if self._state["dirty"] and not discard:
            return False
        self._timer.stop()
        return self._attempt(lambda: self._load(self._state["currentId"]))

    def _set_preview(self, kind: str, content: str, summary: str, source_revision: int = 0) -> None:
        document = self._require().outlines.get(self._state["currentId"])
        if kind != "disk" and document.revision != self._state["revision"]:
            raise OutlineConflictError("大纲已有新版本，请先重新载入，再预览操作")
        self._preview = _Preview(
            kind, document.id, document.revision, content, self._buffer, source_revision
        )
        self._state.update(
            previewKind=kind, previewSummary=summary, previewText=editor_text(content)
        )

    @Slot(QUrl, result=bool)
    def previewReimport(self, url: QUrl) -> bool:
        if not self.flush():
            return False

        def preview() -> None:
            content = self._require().preview_file(self._local_path(url))
            self._set_preview("reimport", content, "重新导入将新增版本，保留旧版。请检查以下差异。")
            self._state["previewText"] = "".join(
                difflib.unified_diff(
                    editor_text(self._buffer).splitlines(keepends=True),
                    editor_text(content).splitlines(keepends=True),
                    fromfile="当前大纲",
                    tofile="重新导入",
                    n=2,
                )
            ) or ("内容相同。" if content == self._buffer else "仅 BOM 或换行格式不同。")

        return self._attempt(preview)

    @Slot(int, result=bool)
    def previewVersion(self, revision: int) -> bool:
        def preview() -> None:
            snapshot = self._require().outlines.read_version(self._state["currentId"], revision)
            self._set_preview(
                "version",
                snapshot.content,
                f"查看修订 {revision}；采用后新增版本，保留现有历史。",
                revision,
            )

        return self._attempt(preview)

    @Slot(result=bool)
    def previewDisk(self) -> bool:
        def preview() -> None:
            content = self._require().outlines.inspect_working_copy(self._state["currentId"])
            self._set_preview(
                "disk",
                content,
                "接纳磁盘版会替换当前编辑。需要保留本地修改时，请先取消并导出副本。",
            )

        return self._attempt(preview)

    @Slot(result=bool)
    def applyPreview(self) -> bool:
        def apply() -> None:
            preview = self._preview
            if (
                preview is None
                or preview.document_id != self._state["currentId"]
                or self._buffer != preview.buffer
            ):
                raise OutlineConflictError("预览后的编辑已变化，请重新预览后再确认")
            repository = self._require().outlines
            if preview.kind == "disk":
                snapshot = repository.recover_from_disk(
                    preview.document_id,
                    expected_revision=preview.expected_revision,
                    expected_disk_hash=outline_content_hash(preview.content),
                )
            else:
                if self._state["dirty"]:
                    raise OutlineConflictError("请先保存或导出当前编辑，再采用预览")
                if (
                    preview.kind == "version"
                    and repository.read_version(
                        preview.document_id, preview.source_revision
                    ).content
                    != preview.content
                ):
                    raise OutlineIntegrityError("历史版本已变化，请重新检查")
                snapshot = repository.save(
                    preview.document_id,
                    preview.content,
                    expected_revision=preview.expected_revision,
                )
            self._adopt(snapshot)
            self._preview = None

        return self._attempt(apply)

    @Slot(result=bool)
    def restoreMissing(self) -> bool:
        def restore() -> None:
            if self._state["dirty"]:
                raise OutlineConflictError("请先导出当前编辑，再恢复缺失文件")
            snapshot = self._require().outlines.restore_missing_working_copy(
                self._state["currentId"],
                expected_revision=self._state["revision"],
            )
            self._adopt(snapshot)

        return self._attempt(restore)

    @Slot(result=bool)
    def refreshLinks(self) -> bool:
        if self._state["dirty"] or not self._state["loaded"]:
            self._state["linksError"] = "请先保存大纲，再检查和确认关联。"
            self.changed.emit()
            return False
        result = self._refresh_links()
        self.changed.emit()
        return result

    def _link_action(self, fingerprint: str, action: Callable[[], OutlineLinkSnapshot]) -> bool:
        if self._state["dirty"] or not self._state["loaded"] or not self._state["linksReady"]:
            self._state["linksError"] = "大纲有未保存更改，请保存并重新检查关联。"
            self.changed.emit()
            return False
        try:
            if fingerprint != self._state["linkFingerprint"]:
                raise OutlineConflictError("关联版本与当前界面不一致，请重新检查后再操作")
            snapshot = action()
            self._link_state(snapshot)
        except (OutlineConflictError, OutlineIntegrityError) as exc:
            self._state["linksError"] = str(exc)
            self._state["linksReady"] = False
        except Exception:  # noqa: BLE001 - never expose SQL, paths or author text
            self._state["linksError"] = "关联操作未完成，请重新扫描并检查所选章节与位置。"
            self._state["linksReady"] = False
        else:
            self._state["linksError"] = ""
            self.changed.emit()
            return True
        self.changed.emit()
        return False

    @Slot(list, str, result=bool)
    def confirmLinks(self, link_ids: list[str], fingerprint: str) -> bool:
        return self._link_action(
            fingerprint,
            lambda: self._require().links.confirm(
                self._state["currentId"],
                tuple(link_ids),
                expected_fingerprint=fingerprint,
            ),
        )

    @Slot(str, int, str, result=bool)
    def relocateLink(self, link_id: str, line: int, fingerprint: str) -> bool:
        return self._link_action(
            fingerprint,
            lambda: self._require().links.relocate(
                self._state["currentId"],
                link_id,
                line,
                expected_fingerprint=fingerprint,
            ),
        )

    @Slot(str, str, result=bool)
    def retireLink(self, link_id: str, fingerprint: str) -> bool:
        return self._link_action(
            fingerprint,
            lambda: self._require().links.retire(
                self._state["currentId"],
                link_id,
                expected_fingerprint=fingerprint,
            ),
        )

    @Slot(str, int, result=bool)
    def insertNoteLink(self, note_id: str, line: int) -> bool:
        if not self.flush():
            return False

        def insert() -> None:
            if self._base is None:
                raise ValueError("大纲尚未载入")
            note = NoteRepository(self._require().outlines.project).read(note_id)
            title = note.title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            token = f"[{title}]({reference_url('note', note.id)})"
            self.edit(editor_text(insert_chapter_link(self._buffer, line, token)))

        return self._attempt(insert) and self.flush()

    @Slot(str, int, result=bool)
    def insertChapterLink(self, chapter_id: str, line: int) -> bool:
        if not self.flush():
            return False

        def insert() -> None:
            if self._base is None:
                raise ValueError("大纲尚未载入")
            content = self._require().propose_chapter_link(
                self._state["currentId"],
                chapter_id,
                line,
                expected_revision=self._base.version.revision,
            )
            self.edit(editor_text(content))

        if not self._attempt(insert) or not self.flush():
            return False
        position = sum(
            len(text.encode("utf-16-le")) // 2
            for text in editor_text(self._buffer).splitlines(keepends=True)[: line - 1]
        )
        self.revealRequested.emit(position)
        return True

    @Slot(str, result=bool)
    def openLinkedChapter(self, chapter_id: str) -> bool:
        if not self.flush():
            return False

        def open_chapter() -> None:
            ChapterRepository(self._require().outlines.project).get_chapter(
                chapter_id, include_deleted=False
            )
            if self._chapter_opener is not None and not self._chapter_opener(chapter_id):
                raise OutlineConflictError(
                    "当前正文未能安全切换，请先保存正文或等待正在运行的任务完成"
                )
            self.chapterRequested.emit(chapter_id)

        return self._attempt(open_chapter)
