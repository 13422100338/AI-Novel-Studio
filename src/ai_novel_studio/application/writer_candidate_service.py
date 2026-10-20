"""Author-owned candidate actions, separate from model execution and planning."""

from __future__ import annotations

import sqlite3
from _thread import LockType
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from threading import Event
from typing import Any

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.application.outline_writer_input import PROMPT_VERSION, fingerprint, text_hash
from ai_novel_studio.application.selection_patch import (
    finalize_selection_patch,
    parse_selection_patch_capture,
    replay_selection_patch,
    validate_selection_patch_capture,
)
from ai_novel_studio.domain.generation import GenerationCheckpoint, GenerationRun, GenerationStatus
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.outline import validate_outline_hash
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterFileTransaction,
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.writer_input_repository import WriterInputRepository

_ACTIVE = {GenerationStatus.PREPARING, GenerationStatus.READY, GenerationStatus.STREAMING}
_CANDIDATES = (
    GenerationStatus.PREPARING,
    GenerationStatus.READY,
    GenerationStatus.STREAMING,
    GenerationStatus.PARTIAL,
    GenerationStatus.COMPLETED,
    GenerationStatus.FAILED,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    run: GenerationRun
    metadata: dict[str, Any] | None
    checkpoint: GenerationCheckpoint | None
    text: str
    problem: str


class WriterCandidateService:
    def __init__(
        self,
        project: ProjectRepository,
        novel: NovelReadService,
        *,
        operation_lock: LockType,
        on_event: Callable[[dict[str, Any]], None],
    ) -> None:
        self.project, self.novel, self._lock, self.on_event = (
            project,
            novel,
            operation_lock,
            on_event,
        )
        self.runs = GenerationRepository(project)
        self.chapters = ChapterRepository(project)
        self.checkpoints = CheckpointRepository(project, self.runs)
        self.snapshots = WriterInputRepository(project)
        self.revisions = ChapterRevisionService(project)
        self._closed = Event()

    def revoke(self) -> None:
        self._closed.set()

    def _ensure_open(self) -> None:
        if self._closed.is_set():
            raise ValueError("小说项目已切换，旧候选操作不可用")
        self.novel.editor_snapshot()

    def _read(self, run_id: str) -> _Candidate:
        validate_id(run_id)
        run = self.runs.get(run_id)
        if run.prompt_version != PROMPT_VERSION:
            raise ValueError("此入口仅处理完整大纲流程的候选")
        metadata, problem = None, ""
        try:
            metadata = self.snapshots.load(run_id)["metadata"]
        except ValueError:
            problem = "输入快照不可用，不能自动采用；原文件保留。"
        checkpoint = self.checkpoints.latest(run_id, verify=False)
        text = ""
        if checkpoint is not None:
            try:
                text = self.checkpoints.read(checkpoint.id)
            except (OSError, RuntimeError, ValueError):
                problem = "候选检查点缺失或损坏，原记录保留，不能采用。"
        return _Candidate(run, metadata, checkpoint, text, problem)

    @staticmethod
    def _source(record: _Candidate) -> NovelEditorSnapshot:
        metadata = record.metadata
        if metadata is None or not isinstance(metadata.get("adoption_source"), dict):
            raise ValueError("旧候选缺少原文定位信息，可查看和复制，请重新生成后采用。")
        value = metadata["adoption_source"]
        if set(value) != {
            "chapter_id",
            "title",
            "revision",
            "content",
            "dirty",
            "selection",
            "selection_capture",
        }:
            raise ValueError("采用来源信息无效")
        if (
            value["chapter_id"] != record.run.chapter_id
            or type(value["revision"]) is not int
            or value["revision"] < 0
            or value["revision"] != metadata.get("revision")
            or type(value["dirty"]) is not bool
            or any(not isinstance(value[key], str) for key in ("title", "content", "selection"))
        ):
            raise ValueError("采用来源信息无效")
        capture = value["selection_capture"]
        if capture is not None:
            if not isinstance(capture, dict):
                raise ValueError("原选区定位无效")
            capture = parse_selection_patch_capture(capture)
        source = NovelEditorSnapshot(
            value["chapter_id"],
            value["title"],
            value["revision"],
            value["content"],
            value["dirty"],
            value["selection"],
            capture,
        )
        target_hash = metadata.get("target_hash")
        if not isinstance(target_hash, str):
            raise ValueError("正式原文哈希无效")
        validate_outline_hash(target_hash)
        if fingerprint(asdict(source)) != metadata.get("editor_hash"):
            raise ValueError("冻结编辑原文校验失败")
        if metadata.get("scope") == "SELECTION":
            if capture is None:
                raise ValueError(
                    "此候选只有聊天引用，没有可验证的原选区位置，请复制使用或重新选文生成。"
                )
            selected = validate_selection_patch_capture(
                capture,
                source=source.content,
                chapter_id=record.run.chapter_id,
                revision=source.revision,
            )
            if selected != source.selection:
                raise ValueError("原选区与本次写作范围不一致")
        elif metadata.get("scope") != "CHAPTER" or source.selection or capture is not None:
            raise ValueError("候选处理范围不明确")
        return source

    def describe(self, run_id: str) -> dict[str, Any]:
        record = self._read(run_id)
        run, metadata = record.run, record.metadata or {}
        problem = record.problem
        try:
            self._source(record)
        except (ValueError, RuntimeError) as exc:
            problem = problem or str(exc)
        if len(record.text) > 200_000:
            problem = (
                "候选超过 200,000 字，界面仅显示和复制前 200,000 字；"
                "完整结果保留在原检查点中，不能直接采用。"
            )
        elif "\x00" in record.text:
            problem = "候选包含无效控制字符，请检查原检查点，不能直接采用。"
        elif metadata.get("scope") == "SELECTION" and len(record.text) > 20_000:
            problem = "选文候选超过 20,000 字直接替换上限，可复制检查，未自动采用。"
        request_id = metadata.get("request_id", run.id)
        try:
            validate_id(request_id)
        except ValueError:
            request_id = run.id
        message = {
            GenerationStatus.ACCEPTED: "已采用并保存正式正文修订。",
            GenerationStatus.DISCARDED: "已放弃，原输入与检查点保留。",
        }.get(run.status, "已从原检查点与原输入恢复候选，未调用模型。")
        return {
            "id": request_id,
            "run_id": run.id,
            "chapter_id": run.chapter_id,
            "revision": metadata.get("revision"),
            "status": str(run.status),
            "model": run.model_id,
            "scope": metadata.get("scope", ""),
            "outline_fingerprint": metadata.get("outline_fingerprint", ""),
            "estimated_tokens": metadata.get("estimated_tokens", 0),
            "context_window": metadata.get("context_window", 0),
            "target_words": metadata.get("target_words", 0),
            "input_ready": record.metadata is not None,
            "draft_text": record.text[:200_000],
            "word_count": len(record.text),
            "checkpoint_id": record.checkpoint.id if record.checkpoint else "",
            "candidate_hash": record.checkpoint.content_hash if record.checkpoint else "",
            "partial": run.status == GenerationStatus.PARTIAL,
            "can_adopt": bool(record.text.strip())
            and not problem
            and run.status in {GenerationStatus.COMPLETED, GenerationStatus.PARTIAL},
            "can_discard": run.status in _CANDIDATES,
            "adoption_note": problem,
            "message": problem or message,
        }

    def decorate(self, event: dict[str, Any]) -> dict[str, Any]:
        if not event.get("run_id") or event.get("status") not in {
            "COMPLETED",
            "PARTIAL",
            "CANCELLED",
            "FAILED",
        }:
            return event
        try:
            info = self.describe(event["run_id"])
        except (KeyError, RuntimeError, ValueError):
            return {
                **event,
                "can_adopt": False,
                "adoption_note": "候选记录暂不可用，请恢复后检查。",
            }
        return {
            **event,
            **{
                key: info[key]
                for key in (
                    "can_adopt",
                    "can_discard",
                    "checkpoint_id",
                    "candidate_hash",
                    "partial",
                    "adoption_note",
                )
            },
        }

    def preview(self, run_id: str) -> dict[str, Any]:
        self._ensure_open()
        payload = self.snapshots.load(run_id)
        return {**payload["metadata"], "messages": payload["messages"]}

    def recover(self, limit: int = 20) -> dict[str, int]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("恢复数量应为 1 至 100 的整数")
        if not self._lock.acquire(blocking=False):
            raise ValueError("正文任务仍在处理，请停止或等待后再恢复候选")
        try:
            self._ensure_open()
            runs = [
                r
                for r in self.runs.list_by_statuses(_CANDIDATES)
                if r.prompt_version == PROMPT_VERSION
            ]
            for run in runs[-limit:]:
                self._ensure_open()
                record = self._read(run.id)
                if run.status in _ACTIVE:
                    target = (
                        GenerationStatus.PARTIAL
                        if run.status == GenerationStatus.STREAMING and record.text
                        else GenerationStatus.FAILED
                    )
                    self.runs.transition(
                        run.id,
                        run.status,
                        target,
                        failure_code="RECOVERED_INTERRUPTION",
                        failure_message="已恢复原检查点，未重新生成",
                    )
                self.on_event(self.describe(run.id))
            return {"restored": min(limit, len(runs)), "total": len(runs)}
        finally:
            self._lock.release()

    @staticmethod
    def _check_checkpoint(record: _Candidate, checkpoint_id: str, candidate_hash: str) -> None:
        if record.checkpoint is None:
            if checkpoint_id or candidate_hash:
                raise ValueError("候选检查点已变化，请重新恢复审阅")
        elif (
            record.checkpoint.id != checkpoint_id
            or record.checkpoint.content_hash != candidate_hash
        ):
            raise ValueError("候选检查点已变化，请重新恢复审阅")

    def _current_checkpoint(self, record: _Candidate, connection: sqlite3.Connection) -> _Candidate:
        return replace(
            record,
            checkpoint=self.checkpoints.latest(record.run.id, connection=connection, verify=False),
        )

    def discard(self, run_id: str, checkpoint_id: str, candidate_hash: str) -> bool:
        if not self._lock.acquire(blocking=False):
            raise ValueError("正文任务仍在处理，不能放弃正在变化的候选")
        try:
            self._ensure_open()
            record = self._read(run_id)
            self._check_checkpoint(record, checkpoint_id, candidate_hash)
            with closing(self.project.database.connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check_checkpoint(
                    self._current_checkpoint(record, connection), checkpoint_id, candidate_hash
                )
                self._ensure_open()
                self.runs.transition(
                    run_id, record.run.status, GenerationStatus.DISCARDED, connection=connection
                )
            self.on_event(self.describe(run_id))
            return True
        except (KeyError, RuntimeError) as exc:
            raise ValueError("候选状态已变化，未放弃；请重新恢复检查") from exc
        finally:
            self._lock.release()

    def accept(
        self, run_id: str, checkpoint_id: str, candidate_hash: str, *, allow_partial: bool = False
    ) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise ValueError("正文任务仍在处理，不能采用正在变化的候选")
        try:
            self._ensure_open()
            record = self._read(run_id)
            self._check_checkpoint(record, checkpoint_id, candidate_hash)
            if record.run.status not in {GenerationStatus.COMPLETED, GenerationStatus.PARTIAL} or (
                record.run.status == GenerationStatus.PARTIAL and allow_partial is not True
            ):
                raise ValueError("候选尚未完成；部分候选需要明确选择采用部分正文")
            if not self.describe(run_id)["can_adopt"]:
                raise ValueError("此候选缺少可验证原文或原选区，不能自动采用")
            source = self._source(record)
            assert record.metadata is not None  # _source validated the frozen metadata.
            assert source.chapter_id is not None  # Bound to the run's chapter by _source.
            editor = self.novel.editor_snapshot()
            if (
                editor.chapter_id != source.chapter_id
                or editor.revision != source.revision
                or editor.content != source.content
            ):
                raise ValueError("当前编辑原文或章节已变化，未覆盖；请重新生成或复制候选")
            text = record.text
            if source.selection_capture is not None:
                patch = finalize_selection_patch(
                    source.selection_capture,
                    source=source.content,
                    chapter_id=record.run.chapter_id,
                    revision=source.revision,
                    replacement_candidate_id="sha256:" + text_hash(record.text),
                    replacement_text=record.text,
                )
                text = replay_selection_patch(
                    patch,
                    source=source.content,
                    chapter_id=record.run.chapter_id,
                    revision=source.revision,
                )
            files = ChapterFileTransaction()
            with closing(self.project.database.connect()) as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    current = self.runs.get(run_id, connection=connection)
                    self._check_checkpoint(
                        self._current_checkpoint(record, connection), checkpoint_id, candidate_hash
                    )
                    chapter = self.chapters.get_chapter(
                        source.chapter_id, include_deleted=False, connection=connection
                    )
                    formal = self.chapters.read_content_exact(
                        source.chapter_id, connection=connection
                    )
                    if (
                        current.status != record.run.status
                        or chapter.revision != source.revision
                        or text_hash(formal) != record.metadata["target_hash"]
                    ):
                        raise ValueError("正式正文或候选状态已变化，未采用")
                    self._ensure_open()
                    committed = self.revisions.commit_revision(
                        source.chapter_id,
                        text,
                        source="ai_generation",
                        reason=f"accepted outline candidate {run_id}",
                        expected_revision=source.revision,
                        connection=connection,
                        file_transaction=files,
                    )
                    self.runs.transition(
                        run_id,
                        current.status,
                        GenerationStatus.ACCEPTED,
                        accepted_chapter_revision=committed.chapter.revision,
                        connection=connection,
                    )
                    connection.commit()
                except Exception as exc:
                    connection.rollback()
                    files.rollback()
                    raise ValueError("候选采用未完成，请重新载入检查；未自动重试。") from exc
                else:
                    files.finalize()
            maintenance_pending = False
            try:
                maintenance = self.revisions.maintain_current_revision(
                    source.chapter_id,
                    expected_revision=committed.chapter.revision,
                    expected_source_hash=text_hash(text),
                )
                maintenance_pending = maintenance.recovery_required
            except Exception:
                maintenance_pending = True
            self.on_event(self.describe(run_id))
            return {
                "run_id": run_id,
                "chapter_id": source.chapter_id,
                "text": text,
                "revision": committed.chapter.revision,
                "status": "ACCEPTED",
                "maintenance_pending": maintenance_pending,
            }
        except (KeyError, RuntimeError) as exc:
            raise ValueError("候选或原文不可用，未自动采用") from exc
        finally:
            self._lock.release()
