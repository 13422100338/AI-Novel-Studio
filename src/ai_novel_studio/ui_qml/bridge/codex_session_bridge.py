"""Qt presentation adapter for the independent Codex conversation service."""

from __future__ import annotations

import json
import os
from _thread import LockType
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any, TypedDict
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImageReader

from ai_novel_studio.application.codex_outline_context import CodexOutlineContext
from ai_novel_studio.application.codex_session_service import CodexSessionService
from ai_novel_studio.application.model_backend import ModelBackend
from ai_novel_studio.application.novel_note_service import NovelNoteService
from ai_novel_studio.application.novel_read_service import (
    NOVEL_TOOLS,
    NovelEditorSnapshot,
    NovelReadService,
)
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.domain.author_note import NoteSelection
from ai_novel_studio.infrastructure.codex.app_server import CodexConnectionError
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex
from ai_novel_studio.infrastructure.llm import LLMGateway
from ai_novel_studio.ui_qml.bridge.codex_controls_bridge import default_preferences_store
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.models.agent_timeline_model import AgentTimelineModel
from ai_novel_studio.ui_qml.bridge.novel_read_progress import NovelReadProgress


def default_session(project_id: str) -> CodexSessionService:
    local = os.environ.get("LOCALAPPDATA")
    root = (Path(local) if local else Path.home() / "AppData" / "Local") / "AI Novel Studio"
    return CodexSessionService(
        project_id,
        CodexSessionIndex(root / "codex-sessions" / f"{project_id}.json"),
        root / "codex-workspaces",
        preferences=default_preferences_store().load,
    )


def default_writer_gateway() -> LLMGateway:
    # Re-read the saved independent-writing route for every generation.
    return ModelBackend.create_default().gateway


class _WriterCardChanges(TypedDict):
    label: str
    text: str
    state: str
    status: str
    busy: bool
    draft_text: str
    data: str


class _Job(QRunnable):
    def __init__(self, action: Callable[[], None]) -> None:
        super().__init__()
        self.action = action

    def run(self) -> None:
        self.action()


class CodexSessionController(QObject):
    busy_changed = Signal()
    status_changed = Signal()
    controls_changed = Signal()
    writer_status_changed = Signal(str)
    notes_changed = Signal()
    _note_saved = Signal(int, str)
    _writer_event = Signal(int, object)
    _writer_finished = Signal(int, str)
    _writer_recovered = Signal(int, object)
    _history = Signal(int, object)
    _message = Signal(int, str, str)
    _finished = Signal(int, str)
    _failed = Signal(int, str)
    _event = Signal(int, str, object)
    _steered = Signal(int, str, bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        session_factory: Callable[[str], Any] = default_session,
        writer_gateway_factory: Callable[[], LLMGateway] = default_writer_gateway,
    ) -> None:
        super().__init__(parent)
        self._factory = session_factory
        self._writer_gateway_factory = writer_gateway_factory
        self._writer: NovelWriterService | None = None
        self._note_writer: NovelNoteService | None = None
        self._note_selection = NoteSelection()
        self._active_note: str | None = None
        self._note_dirty = False
        self._writer_generating = False
        self._writer_recovering = False
        # Keep the lock when reconnecting or reopening a project: a revoked
        # producer may still be finishing its last checkpoint in another job.
        self._writer_locks: dict[str, LockType] = {}
        self._writer_ids: dict[str, str] = {}
        self._model = AgentTimelineModel(self)
        self._port: Any = None
        self._project_id: str | None = None
        self._epoch = 0
        self._busy = False
        self._status = "请打开项目"
        self._status_id: str | None = None
        self._message_ids: dict[str, str] = {}
        self._tool_ids: dict[str, str] = {}
        self._read_progress = NovelReadProgress()
        self._read_summary_id: str | None = None
        self._attachments: list[Path] = []
        self._repository: Any = None
        self._novel: NovelReadService | None = None
        self._editor = NovelEditorSnapshot()
        self._can_steer = False
        self._usage = ""
        self._history.connect(self._on_history)
        self._message.connect(self._on_message)
        self._finished.connect(self._on_finished)
        self._failed.connect(self._on_failed)
        self._event.connect(self._on_event)
        self._steered.connect(self._on_steered)
        self._writer_event.connect(self._on_writer_event)
        self._writer_finished.connect(self._on_writer_finished)
        self._writer_recovered.connect(self._on_writer_recovered)
        self._note_saved.connect(self._on_note_saved)

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def status_text(self) -> str:
        return self._status

    @property
    def can_steer(self) -> bool:
        return self._can_steer

    @property
    def usage_text(self) -> str:
        return self._usage

    @property
    def can_manage_current(self) -> bool:
        return bool(self._port and getattr(self._port, "can_manage_current", False))

    @property
    def sessions(self) -> list[dict[str, str]]:
        values = getattr(self._port, "sessions", []) if self._port else []
        return [
            {"value": value, "label": f"会话 {i + 1} · {value[-6:]}"}
            for i, value in enumerate(values)
        ]

    @property
    def session_index(self) -> int:
        thread_id = getattr(self._port, "thread_id", None)
        return next((i for i, item in enumerate(self.sessions) if item["value"] == thread_id), -1)

    @property
    def attachments(self) -> list[dict[str, str]]:
        return [{"name": path.name, "path": str(path)} for path in self._attachments]

    @property
    def novel_text(self) -> str:
        return "小说 MCP · 资料读取与独立正文写作" if self._novel else "小说 MCP · 请打开项目"

    def update_editor(self, snapshot: NovelEditorSnapshot) -> None:
        self._editor = snapshot
        if self._novel and not self._busy:
            self._novel.update_editor(snapshot)

    def update_notes(
        self, selection: NoteSelection, active_note: str | None = None, dirty: bool = False
    ) -> None:
        self._note_selection = selection
        self._active_note, self._note_dirty = active_note, dirty
        if self._novel:
            self._novel.update_note_selection(selection, active_note, dirty)

    @Slot(int, str)
    def _on_note_saved(self, epoch: int, identity: str) -> None:
        if epoch == self._epoch:
            self.notes_changed.emit()

    def _create_port(self) -> Any:
        assert self._project_id is not None
        port = self._factory(self._project_id)
        if self._repository is not None and isinstance(port, CodexSessionService):
            self._novel = NovelReadService(self._repository)
            self._novel.update_editor(self._editor)
            self._novel.update_note_selection(
                self._note_selection, self._active_note, self._note_dirty
            )
            port.bind_novel(self._novel)
            port.bind_outline(CodexOutlineContext(self._repository))
            epoch = self._epoch
            self._note_writer = NovelNoteService(
                self._repository, on_saved=lambda identity: self._note_saved.emit(epoch, identity)
            )
            port.bind_notes(self._note_writer)
            self._writer = NovelWriterService(
                self._repository,
                self._novel,
                gateway_factory=self._writer_gateway_factory,
                on_event=lambda event: self._writer_event.emit(epoch, event),
                operation_lock=self._writer_locks.setdefault(self._project_id, Lock()),
            )
            port.bind_writer(self._writer)
        return port

    def bind_model(self, model: AgentTimelineModel) -> None:
        self._model = model

    def _state(self, text: str, busy: bool) -> None:
        self._busy = busy
        self._status = text
        if not busy:
            self._can_steer = False
        self.busy_changed.emit()
        self.status_changed.emit()
        self.controls_changed.emit()

    def _append(self, kind: str, text: str) -> str:
        item_id = str(uuid4())
        self._model.append_item(AgentTimelineItemDto(id=item_id, kind=kind, text=text))
        return item_id

    def warn(self, text: str) -> None:
        self._append("warning", text)

    def bind_project(self, project_id: str | None, repository: Any = None) -> None:
        self._epoch += 1
        if self._note_writer:
            self._note_writer.revoke()
        self._note_writer = None
        self._note_selection = NoteSelection()
        self._active_note, self._note_dirty = None, False
        self._writer_generating = False
        self._writer_recovering = False
        if self._writer:
            self._writer.revoke()
        self._writer = None
        self._writer_ids.clear()
        self.writer_status_changed.emit("IDLE")
        old = self._port
        if self._novel:
            self._novel.revoke()
        self._novel = None
        self._repository = repository
        self._editor = NovelEditorSnapshot()
        self._port = None
        self._project_id = project_id
        self._status_id = None
        self._message_ids.clear()
        self._tool_ids.clear()
        self._read_progress = NovelReadProgress()
        self._read_summary_id = None
        self._attachments.clear()
        self._usage = ""
        self._model.clear()
        self._state("就绪" if project_id else "请打开项目", False)
        if old is not None:
            QThreadPool.globalInstance().start(_Job(old.close))
        if project_id is None:
            return
        try:
            self._port = self._create_port()
            self.controls_changed.emit()
            if self._port.has_saved_thread:
                self._state("正在恢复会话", True)
                self._run(restore=True)
        except Exception:
            self._state("会话索引不可用", False)
            self.warn("Codex 会话索引不可用，原文件已保留")

    def add_attachment(self, path: Path) -> None:
        if self._busy:
            return
        try:
            path = path.resolve(strict=True)
            if len(self._attachments) >= 4:
                raise ValueError("每次最多发送4个附件")
            if not path.is_file() or path.stat().st_size > 20_000_000:
                raise ValueError("请选择20MB以内的文件")
            suffix = path.suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                if not QImageReader(str(path)).canRead():
                    raise ValueError("无法读取该图片")
            elif suffix in {".txt", ".md"}:
                if path.stat().st_size > 100_000:
                    raise ValueError("文本附件不能超过100KB")
                content = path.read_text(encoding="utf-8-sig")
                if len(content) > 20_000 or "\x00" in content:
                    raise ValueError("文本附件应为20000字以内的 UTF-8 文本")
            else:
                raise ValueError("附件支持 PNG、JPG、WebP、GIF、TXT 和 Markdown")
            if path not in self._attachments:
                self._attachments.append(path)
                self.controls_changed.emit()
        except (OSError, UnicodeError):
            self.warn("附件读取失败，请选择可读的图片或 UTF-8 文本")
        except ValueError as exc:
            self.warn(str(exc))

    def remove_attachment(self, index: int) -> None:
        if not self._busy and 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self.controls_changed.emit()

    def manage_session(self, operation: str, thread_id: str = "") -> None:
        if (
            self._busy
            or self._port is None
            or operation not in {"new", "fork", "switch", "compact"}
        ):
            return
        if operation in {"fork", "compact"} and not self.can_manage_current:
            return
        if operation == "switch" and thread_id not in {item["value"] for item in self.sessions}:
            return
        self._status_id = None
        label = {
            "new": "正在新建会话",
            "fork": "正在创建分支",
            "switch": "正在切换会话",
            "compact": "正在压缩上下文",
        }[operation]
        self._state(label, True)
        self._run(operation=operation, thread_id=thread_id)

    def steer(self, text: str) -> None:
        if not self._can_steer or not text.strip() or len(text) > 20_000:
            return
        epoch, port = self._epoch, self._port

        def action() -> None:
            try:
                port.steer(text)
                self._steered.emit(epoch, text, True)
            except Exception as exc:
                self._steered.emit(epoch, text, False)
                if isinstance(exc, ValueError):
                    self._event.emit(epoch, "session/inputRejected", {"message": str(exc)})

        QThreadPool.globalInstance().start(_Job(action))

    def start(self, text: str, *, request_text: str | None = None) -> None:
        if self._busy:
            return
        if self._port is None:
            self.warn("请先打开小说项目后使用 Codex")
            return
        if not text.strip() or len(text) > 20_000:
            self.warn("消息不能为空且不能超过20000字")
            return
        self._message_ids.clear()
        self._read_progress = NovelReadProgress()
        self._read_summary_id = None
        names = "、".join(path.name for path in self._attachments)
        quote = ""
        if self._editor.selection:
            quote = (
                f"\n引用选文 · {self._editor.title} · {len(self._editor.selection)} 字\n"
                + self._editor.selection[:160]
            )
        self._append("user_text", text + quote + (f"\n附件：{names}" if names else ""))
        self._status_id = str(uuid4())
        self._model.append_item(
            AgentTimelineItemDto(
                id=self._status_id,
                kind="run_status",
                label="Codex 正在回复",
                busy=True,
                status="RUNNING",
                state="RUNNING",
            )
        )
        self._state("正在回复", True)
        self._run(text=request_text if request_text is not None else text)

    def _run(
        self, *, text: str = "", restore: bool = False, operation: str = "send", thread_id: str = ""
    ) -> None:
        epoch, port = self._epoch, self._port
        attachments = tuple(self._attachments)

        def action() -> None:
            try:
                if restore:
                    self._history.emit(epoch, port.restore())
                    state = "ready"
                elif operation == "compact":
                    state = port.compact()
                elif operation != "send":
                    history = port.restore(
                        new=operation == "new",
                        fork=operation == "fork",
                        thread_id=thread_id or None,
                    )
                    self._history.emit(epoch, history)
                    state = "ready"
                else:
                    state = port.send(
                        text,
                        lambda item, body: self._message.emit(epoch, item, body),
                        attachments=attachments,
                        on_event=lambda method, params: self._event.emit(epoch, method, params),
                    )
                self._finished.emit(epoch, state)
            except Exception as exc:
                try:
                    port.close()
                except Exception:
                    pass
                message = (
                    str(exc)
                    if isinstance(exc, (CodexConnectionError, ValueError))
                    else "Codex 连接异常，请重试"
                )
                self._failed.emit(epoch, message)

        QThreadPool.globalInstance().start(_Job(action))

    def stop(self) -> None:
        if self._writer_recovering:
            return
        if self._writer_generating:
            self.cancel_writer()
            return
        if not self._busy or self._port is None:
            return
        self._state("正在停止", True)
        epoch, port = self._epoch, self._port

        def action() -> None:
            try:
                port.interrupt()
            except Exception:
                port.close()
                self._failed.emit(epoch, "Codex 停止请求失败，连接已关闭")

        QThreadPool.globalInstance().start(_Job(action))

    def close(self) -> None:
        self._epoch += 1
        if self._writer:
            self._writer.revoke()
        if self._novel:
            self._novel.revoke()
        if self._port is not None:
            self._port.close()
            self._port = None

    @Slot(int, object)
    def _on_history(self, epoch: int, history: list[tuple[str, str]]) -> None:
        if epoch == self._epoch:
            self._model.clear()
            self._message_ids.clear()
            self._tool_ids.clear()
            self._writer_ids.clear()
            self._read_progress = NovelReadProgress()
            self._read_summary_id = None
            self._attachments.clear()
            self._usage = ""
            for kind, text in history:
                self._append(kind, text)

    @Slot(int, str, str)
    def _on_message(self, epoch: int, item: str, text: str) -> None:
        if epoch != self._epoch or not self._busy:
            return
        if item not in self._message_ids:
            self._message_ids[item] = self._append("assistant_text", text)
        else:
            self._model.update_item(self._message_ids[item], text=text)

    @Slot(int, str)
    def _on_finished(self, epoch: int, state: str) -> None:
        if epoch != self._epoch:
            return
        if self._read_summary_id is not None:
            self._model.update_item(self._read_summary_id, **self._read_progress.finish(state))
        label = {
            "ready": "就绪",
            "completed": "回复完成",
            "interrupted": "已停止",
            "compacted": "上下文已压缩",
        }.get(state, "回复失败")
        if self._status_id is not None:
            status = {"completed": "DONE", "interrupted": "CANCELLED"}.get(state, "FAILED")
            self._model.update_item(
                self._status_id, label=label, busy=False, status=status, state=status
            )
        self._state(label, False)
        if self._novel:
            self._novel.update_editor(self._editor)
        if state in {"completed", "interrupted"}:
            self._attachments.clear()
            self.controls_changed.emit()
        if state == "failed":
            self.warn("Codex 回复失败，请检查登录、用量或连接状态后重试")

    @Slot(int, str)
    def _on_failed(self, epoch: int, message: str) -> None:
        if epoch != self._epoch:
            return
        self._on_finished(epoch, "failed")
        self.warn(message)
        if self._project_id is not None:
            self._port = self._create_port()

    @Slot(int, str, bool)
    def _on_steered(self, epoch: int, text: str, accepted: bool) -> None:
        if epoch == self._epoch:
            self._append("user_text", "追加要求：" + text)
            if not accepted:
                self.warn("追加要求未送达，任务可能已结束；请重新发送")

    def cancel_writer(self) -> None:
        if self._writer is not None:
            self._writer.cancel()

    def _writer_request(self, item_id: str) -> str:
        for request_id, row_id in self._writer_ids.items():
            if row_id == item_id:
                return request_id
        raise ValueError("当前输入提案不可用")

    def preview_writer_input(self, item_id: str) -> dict[str, Any]:
        try:
            if self._writer is None:
                raise ValueError("正文服务不可用")
            data = self._writer_card(item_id)
            if data.get("run_id"):
                return self._writer.preview_candidate_input(data["run_id"])
            return self._writer.preview_input(self._writer_request(item_id))
        except (ValueError, KeyError):
            self.warn("原输入不可用，未重新拼接；请检查候选记录或重新整理任务。")
            return {}

    def _writer_card(self, item_id: str) -> dict[str, Any]:
        row = next(
            (r for r in self._model.items() if r.id == item_id and r.kind == "writer_task"), None
        )
        if row is None:
            raise ValueError("候选卡片不可用，请恢复后检查")
        try:
            data = json.loads(row.data)
            if not isinstance(data, dict) or any(
                not isinstance(data.get(key, ""), str)
                for key in ("run_id", "checkpoint_id", "candidate_hash")
            ):
                raise ValueError
            return data
        except (TypeError, ValueError) as exc:
            raise ValueError("候选卡片无效，请恢复后检查") from exc

    def adopt_writer_draft(self, item_id: str, *, allow_partial: bool = False) -> dict[str, Any]:
        if self._writer is None or self._busy:
            self.warn("请等待当前任务结束后再采用候选。")
            return {}
        try:
            data = self._writer_card(item_id)
            return self._writer.adopt_candidate(
                data.get("run_id", ""),
                data.get("checkpoint_id", ""),
                data.get("candidate_hash", ""),
                allow_partial=allow_partial,
            )
        except (ValueError, KeyError, RuntimeError) as exc:
            self.warn(str(exc))
            return {}

    def discard_writer_draft(self, item_id: str) -> bool:
        if self._writer is None or self._busy:
            return False
        try:
            data = self._writer_card(item_id)
            return self._writer.discard_candidate(
                data.get("run_id", ""),
                data.get("checkpoint_id", ""),
                data.get("candidate_hash", ""),
            )
        except (ValueError, KeyError, RuntimeError) as exc:
            self.warn(str(exc))
            return False

    def restore_writer_drafts(self) -> bool:
        if self._writer is None or self._busy:
            return False
        epoch, writer = self._epoch, self._writer
        self._writer_recovering = True
        self._state("正在恢复候选", True)

        def action() -> None:
            result: dict[str, Any]
            try:
                result = writer.recover_candidates()
            except ValueError as exc:
                result = {"error": str(exc)}
            except Exception:
                result = {"error": "候选恢复未完成，原记录已保留。"}
            self._writer_recovered.emit(epoch, result)

        QThreadPool.globalInstance().start(_Job(action))
        return True

    @Slot(int, object)
    def _on_writer_recovered(self, epoch: int, result: dict[str, Any]) -> None:
        if epoch != self._epoch:
            return
        self._writer_recovering = False
        self._state("候选恢复未完成" if "error" in result else "候选已恢复", False)
        if "error" in result:
            self.warn(result["error"])
        else:
            self._append(
                "tool_result",
                f"已恢复最近 {result['restored']} / {result['total']} 个候选；"
                "沿用原检查点和输入，未调用模型。",
            )
        if self._novel is not None:
            self._novel.update_editor(self._editor)

    def reject_writer_input(self, item_id: str) -> bool:
        if self._writer is None or self._busy:
            return False
        return self._writer.reject_input(self._writer_request(item_id))

    def confirm_writer_input(self, item_id: str) -> bool:
        if self._writer is None or self._busy:
            self.warn("请等待当前任务完成后再确认正文输入。")
            return False
        try:
            request_id = self._writer_request(item_id)
        except ValueError:
            return False
        epoch, writer = self._epoch, self._writer
        self._writer_generating = True
        self._state("正文生成中", True)

        def action() -> None:
            status = "FAILED"
            try:
                status = str(writer.confirm_input(request_id)["status"])
            except ValueError as exc:
                self._event.emit(epoch, "session/inputRejected", {"message": str(exc)})
            except Exception:
                self._event.emit(
                    epoch,
                    "session/inputRejected",
                    {"message": "正文任务未完成，请检查输入与连接。"},
                )
            finally:
                self._writer_finished.emit(epoch, status)

        QThreadPool.globalInstance().start(_Job(action))
        return True

    @Slot(int, str)
    def _on_writer_finished(self, epoch: int, status: str) -> None:
        if epoch != self._epoch:
            return
        self._writer_generating = False
        self._state(
            {"COMPLETED": "草稿已生成", "PARTIAL": "已保留部分草稿", "CANCELLED": "已停止"}.get(
                status, "正文任务未完成"
            ),
            False,
        )
        if self._novel is not None:
            self._novel.update_editor(self._editor)

    def copy_draft(self, item_id: str) -> None:
        item = next(
            (row for row in self._model.items() if row.id == item_id and row.kind == "writer_task"),
            None,
        )
        if item is not None and item.draft_text:
            QGuiApplication.clipboard().setText(item.draft_text)
            self._model.update_item(item_id, text="草稿已复制，可粘贴到编辑器")

    @Slot(int, object)
    def _on_writer_event(self, epoch: int, event: dict[str, Any]) -> None:
        if (
            epoch != self._epoch
            or not isinstance(event, dict)
            or not isinstance(event.get("id"), str)
        ):
            return
        key, state = event["id"], str(event.get("status", "FAILED"))
        labels = {
            "AWAITING_CONFIRMATION": "待确认正文输入",
            "STALE": "输入资料已变化",
            "PREPARING": "准备写作上下文",
            "GENERATING": "正文生成中",
            "COMPLETED": "草稿已生成",
            "PARTIAL": "已保留部分草稿",
            "CANCELLED": "正文生成已停止",
            "FAILED": "正文生成失败",
            "ACCEPTED": "候选已采用",
            "DISCARDED": "候选已放弃",
        }
        changes = _WriterCardChanges(
            label=labels.get(state, "正文生成"),
            text=str(event.get("message", "")),
            state=state,
            status=state,
            busy=state in {"PREPARING", "GENERATING"},
            draft_text=str(event.get("draft_text", ""))[:200_000],
            data=json.dumps(
                {
                    "model": str(event.get("model", "独立写作模型"))[:160],
                    "word_count": event.get("word_count", 0),
                    "target_words": event.get("target_words", 0),
                    "input_ready": event.get("input_ready", False),
                    "run_id": event.get("run_id", ""),
                    "scope": event.get("scope", ""),
                    "estimated_tokens": event.get("estimated_tokens", 0),
                    "context_window": event.get("context_window", 0),
                    "outline_fingerprint": event.get("outline_fingerprint", ""),
                    "sources": event.get("sources", []),
                    "checkpoint_id": event.get("checkpoint_id", ""),
                    "candidate_hash": event.get("candidate_hash", ""),
                    "partial": event.get("partial", False),
                    "can_adopt": event.get("can_adopt", False),
                    "can_discard": event.get("can_discard", False),
                    "adoption_note": event.get("adoption_note", ""),
                },
                ensure_ascii=False,
            ),
        )
        if key not in self._writer_ids:
            self._writer_ids[key] = str(uuid4())
            self._model.append_item(
                AgentTimelineItemDto(id=self._writer_ids[key], kind="writer_task", **changes)
            )
        else:
            self._model.update_item(self._writer_ids[key], **changes)
        self.writer_status_changed.emit("QUEUED" if state == "PREPARING" else state)

    @Slot(int, str, object)
    def _on_event(self, epoch: int, method: str, params: dict[str, Any]) -> None:
        if epoch != self._epoch or not isinstance(params, dict):
            return
        if method == "session/turnReady":
            self._can_steer = True
            self.controls_changed.emit()
        elif method == "session/outlineContext":
            pending = params.get("pendingLinks", -1)
            links = "关联索引不可用" if pending == -1 else f"{pending} 项关联待确认"
            text = (
                f"{params['documents']} 份文档 · {params['characters']:,} 字\n"
                f"版本 {str(params['fingerprint'])[:12]} · 已确认关联 {params['confirmedLinks']} 项"
                f" · {links}\n"
                f"容量保守估算 {params['estimatedTokens']:,} / {params['contextLimit']:,} tokens\n"
                "本任务使用发送时的完整大纲；改纲在下一轮生效。"
            )
            self._tool(f"outline:{self._status_id}", "本轮完整大纲", text)
        elif method == "session/inputRejected":
            self.warn(str(params.get("message", "追加要求未发送")))
        elif method == "thread/tokenUsage/updated":
            token_usage = params.get("tokenUsage")
            usage = token_usage.get("last") if isinstance(token_usage, dict) else None
            if not isinstance(usage, dict):
                return
            input_tokens, output_tokens = usage.get("inputTokens"), usage.get("outputTokens")
            if type(input_tokens) is not int or type(output_tokens) is not int:
                return
            self._usage = f"最近请求 · 输入 {input_tokens:,} / 输出 {output_tokens:,} tokens"
            self.controls_changed.emit()
        elif method == "turn/plan/updated":
            labels = {"pending": "待办", "inProgress": "进行中", "completed": "完成"}
            steps = params.get("plan", [])
            if not isinstance(steps, list):
                return
            text = "\n".join(
                f"{labels.get(str(step.get('status')), '待办')} · {str(step.get('step', ''))[:300]}"
                for step in steps[:20]
                if isinstance(step, dict)
            )
            self._tool("plan", "创作计划", text)
        elif method in {"item/started", "item/completed"}:
            item = params.get("item", {})
            if not isinstance(item, dict):
                return
            kind = item.get("type")
            if kind == "webSearch":
                self._tool(
                    str(item.get("id")), "联网资料", str(item.get("query", "正在查资料"))[:1000]
                )
            elif kind == "mcpToolCall":
                if item.get("tool") == "generate_novel_draft":
                    # The writer's own progress card carries this task's state.
                    return
                if item.get("tool") in NOVEL_TOOLS:
                    changes = self._read_progress.update(item)
                    if self._read_summary_id is None:
                        self._read_summary_id = str(uuid4())
                        self._model.append_item(
                            AgentTimelineItemDto(
                                id=self._read_summary_id, kind="tool_call", **changes
                            )
                        )
                    else:
                        self._model.update_item(self._read_summary_id, **changes)
                    return
                labels = {
                    "get_novel_context": "当前小说与选区",
                    "list_novel_chapters": "章节列表",
                    "read_novel_chapter": "正式正文",
                    "search_novel_evidence": "正文证据",
                    "get_novel_constraints": "作者计划与约束",
                    "query_novel_characters": "人物查询",
                }
                text = {"inProgress": "读取中", "completed": "读取完成", "failed": "读取失败"}.get(
                    str(item.get("status")), "读取中"
                )
                self._tool(str(item.get("id")), labels.get(str(item.get("tool")), "工具目录"), text)
        elif method == "item/mcpToolCall/progress":
            if str(params.get("itemId")) in self._read_progress.calls:
                return
            item = self._tool_ids.get(str(params.get("itemId")))
            if item:
                self._model.update_item(item, text=str(params.get("message", ""))[:1000])

    def _tool(self, key: str, label: str, text: str) -> None:
        if key in self._tool_ids:
            self._model.update_item(self._tool_ids[key], label=label, text=text)
        else:
            item_id = str(uuid4())
            self._tool_ids[key] = item_id
            self._model.append_item(
                AgentTimelineItemDto(id=item_id, kind="tool_call", label=label, text=text)
            )
