"""Bounded chat-to-writer handoff; candidates use the existing generation/checkpoint pipeline."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Callable
from threading import Event, Lock
from typing import Any
from uuid import UUID, uuid4

from ai_novel_studio.application.novel_read_service import NovelReadService
from ai_novel_studio.application.outline_writer_input import OutlineRequiredError
from ai_novel_studio.application.outline_writer_service import OutlineWriterService
from ai_novel_studio.application.project_generation_session import ProjectGenerationSession
from ai_novel_studio.application.prose_generation_service import ProseEventKind
from ai_novel_studio.application.writer_candidate_service import WriterCandidateService
from ai_novel_studio.core.context.context_builder import RequiredContextOverflowError
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.infrastructure.llm import LLMGateway, TaskPurpose
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

WRITER_TOOL = "generate_novel_draft"


class NovelWriterService:
    def __init__(
        self,
        project: ProjectRepository,
        novel: NovelReadService,
        *,
        gateway_factory: Callable[[], LLMGateway],
        on_event: Callable[[dict[str, Any]], None],
        operation_lock: LockType | None = None,
    ) -> None:
        if project.project.id != novel.project_id:
            raise ValueError("写作工具项目身份不匹配")
        self.project, self.novel = project, novel
        self.gateway_factory, self.on_event = gateway_factory, on_event
        self._closed, self._cancel = Event(), Event()
        self._run_lock, self._state_lock = Lock(), Lock()
        self._allowed = False
        self._session: ProjectGenerationSession | None = None
        self._run_id: str | None = None
        shared_lock = operation_lock or Lock()
        self.candidates = WriterCandidateService(
            project, novel, operation_lock=shared_lock, on_event=on_event
        )
        self.outline_writer = OutlineWriterService(
            project,
            novel,
            gateway_factory=gateway_factory,
            on_event=lambda event: self.on_event(self.candidates.decorate(event)),
            operation_lock=shared_lock,
        )

    def begin_turn(self) -> None:
        self.outline_writer.begin_turn()
        with self._state_lock:
            if self._closed.is_set():
                raise ValueError("小说项目已关闭")
            self._allowed = True

    def cancel(self) -> None:
        self.outline_writer.cancel()
        self._cancel.set()
        with self._state_lock:
            session, run_id = self._session, self._run_id
            self._allowed = False
        if session is not None and run_id is not None:
            session.prose.cancel(run_id)

    def revoke(self) -> None:
        self.candidates.revoke()
        self.outline_writer.revoke()
        self._closed.set()
        self.cancel()

    def generate(
        self,
        chapter_id: str,
        expected_revision: int,
        instruction: str,
        target_words: int = 800,
        output_token_limit: int = 8192,
        related_refs: list[dict[str, Any]] | None = None,
        style_refs: list[dict[str, Any]] | None = None,
        recent_chapters: int = 3,
    ) -> dict[str, Any]:
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction) > 20_000
            or "\x00" in instruction
        ):
            raise ValueError("本次写作要求应为20000字以内的非空文本")
        for value, low, high in (
            (target_words, 100, 30_000),
            (output_token_limit, 1024, 32_768),
            (expected_revision, 0, 1_000_000_000),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("写作参数超出允许范围")
        chapter_id = str(UUID(chapter_id))
        context = self.novel.call("get_novel_context")
        if self._closed.is_set() or context["chapter_id"] != chapter_id:
            raise ValueError("请先切换到要写作的章节，旧项目工具已失效")
        chapter = ChapterRepository(self.project).get_chapter(chapter_id, include_deleted=False)
        if chapter.revision != expected_revision or context["revision"] != expected_revision:
            raise ValueError("章节已经修改，请重新读取上下文后生成")
        if not self.outline_writer.inputs.outlines.list_documents():
            raise OutlineRequiredError()
        if not self._run_lock.acquire(blocking=False):
            raise ValueError("已有正文生成任务，请等待或停止后重试")
        try:
            with self._state_lock:
                if self._closed.is_set() or not self._allowed:
                    raise ValueError("每轮作者消息最多生成一次正文草稿，请重新发送写作要求")
                self._allowed = False
                self._cancel.clear()
            return self.outline_writer.prepare(
                chapter_id,
                expected_revision,
                instruction,
                target_words,
                output_token_limit,
                related_refs if related_refs is not None else [],
                style_refs if style_refs is not None else [],
                recent_chapters,
            )
        finally:
            with self._state_lock:
                self._session, self._run_id = None, None
            self._run_lock.release()

    def preview_input(self, request_id: str) -> dict[str, Any]:
        return self.outline_writer.preview(request_id)

    def confirm_input(self, request_id: str) -> dict[str, Any]:
        return self.outline_writer.confirm(request_id)

    def reject_input(self, request_id: str) -> bool:
        return self.outline_writer.reject(request_id)

    def recover_candidates(self) -> dict[str, int]:
        return self.candidates.recover()

    def preview_candidate_input(self, run_id: str) -> dict[str, Any]:
        return self.candidates.preview(run_id)

    def adopt_candidate(
        self, run_id: str, checkpoint_id: str, candidate_hash: str, *, allow_partial: bool = False
    ) -> dict[str, Any]:
        return self.candidates.accept(
            run_id, checkpoint_id, candidate_hash, allow_partial=allow_partial
        )

    def discard_candidate(self, run_id: str, checkpoint_id: str, candidate_hash: str) -> bool:
        return self.candidates.discard(run_id, checkpoint_id, candidate_hash)

    def _generate(
        self,
        chapter_id: str,
        revision: int,
        instruction: str,
        target_words: int,
        output_token_limit: int,
    ) -> dict[str, Any]:
        # Historical implementation retained pending a separate cleanup ticket.
        # The default public entry no longer schedules this memory-based path.
        task: dict[str, Any] = {
            "id": str(uuid4()),
            "chapter_id": chapter_id,
            "revision": revision,
            "status": "PREPARING",
            "model": "独立写作模型",
            "word_count": 0,
            "target_words": target_words,
            "draft_text": "",
            "message": "正在整理章节上下文",
        }
        self.on_event(dict(task))
        text, run_id = "", ""
        try:
            gateway = self.gateway_factory()
            route = gateway.configuration.routes.resolve(TaskPurpose.PROSE_GENERATION)
            task["model"] = route.model_id
            session = ProjectGenerationSession(
                self.project, gateway, HistoryRetriever(SearchRepository(self.project))
            )
            with self._state_lock:
                self._session = session
            session.select_chapter(chapter_id, revision)
            if self._cancel.is_set() or self._closed.is_set():
                raise InterruptedError
            run_id = session.prepare_generation(
                CreationMode.BASIC, output_token_limit, target_words, instruction=instruction
            )
            with self._state_lock:
                self._run_id = run_id
            if self._cancel.is_set() or self._closed.is_set():
                session.prose.cancel(run_id)
            task.update(status="GENERATING", message="独立写作模型正在生成")
            self.on_event(dict(task))
            for event in session.prose.stream(run_id):
                if event.kind == ProseEventKind.DRAFT_CHUNK:
                    text += event.text
                    task.update(word_count=len(text), message="正在接收正文")
                    if len(text) > 200_000:
                        self.cancel()
                    self.on_event(dict(task))
                elif event.kind == ProseEventKind.REASONING:
                    task["message"] = "写作模型正在构思"
                    self.on_event(dict(task))
                elif event.kind == ProseEventKind.FAILED:
                    task["message"] = event.message
            status = session.runs.get(run_id).status
            task["status"] = (
                "CANCELLED"
                if self._cancel.is_set() or self._closed.is_set()
                else "COMPLETED"
                if status == GenerationStatus.COMPLETED and text.strip()
                else "PARTIAL"
                if text.strip()
                else "FAILED"
            )
        except InterruptedError:
            task.update(status="CANCELLED", message="正文生成已停止")
        except RequiredContextOverflowError:
            task.update(
                status="FAILED",
                message="写作要求超出模型上下文预算，请缩短素材或配置模型上下文容量",
            )
        except Exception:  # noqa: BLE001 - never expose provider payloads or local paths
            task.update(status="FAILED", message="正文生成失败，请检查独立写作模型连接与章节上下文")
        task["draft_text"] = text[:200_000]
        task["word_count"] = len(task["draft_text"])
        self.on_event(dict(task))
        return {
            "draft_id": task["id"],
            "run_id": run_id,
            "chapter_id": chapter_id,
            "status": task["status"],
            "domain_kind": "CANDIDATE_DRAFT",
            "content": task["draft_text"][:12_000],
            "truncated": len(text) > 12_000,
            "note": "候选草稿已显示在作者侧栏；未采用、未覆盖正式正文。全文保留在生成检查点。",
            "message": task["message"],
        }
