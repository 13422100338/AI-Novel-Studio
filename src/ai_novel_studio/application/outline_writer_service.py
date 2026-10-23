"""Author-confirmed outline writing, reusing generation runs and checkpoints."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Callable
from dataclasses import asdict
from threading import Event, Lock
from typing import Any

from ai_novel_studio.application.novel_read_service import NovelReadService
from ai_novel_studio.application.outline_writer_input import (
    PROMPT_VERSION,
    OutlineWriterInputService,
    WriterInputPlan,
)
from ai_novel_studio.application.prose_generation_service import (
    ProseEventKind,
    ProseGenerationService,
)
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
    SelectedManifestItem,
    create_manifest_id,
    utc_now,
)
from ai_novel_studio.domain.generation import CreationMode, GenerationStatus
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.llm import LLMGateway
from ai_novel_studio.infrastructure.storage.checkpoint_repository import CheckpointRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.writer_input_repository import WriterInputRepository


class OutlineWriterService:
    def __init__(
        self,
        project: ProjectRepository,
        novel: NovelReadService,
        *,
        gateway_factory: Callable[[], LLMGateway],
        on_event: Callable[[dict[str, Any]], None],
        operation_lock: LockType | None = None,
    ) -> None:
        self.project, self.gateway_factory, self.on_event = project, gateway_factory, on_event
        self.inputs = OutlineWriterInputService(project, novel)
        self.snapshots = WriterInputRepository(project)
        self.runs = GenerationRepository(project)
        self._pending: WriterInputPlan | None = None
        self._completed: dict[str, str] = {}
        self._lock, self._state_lock = operation_lock or Lock(), Lock()
        self._closed, self._cancel = Event(), Event()
        self._prose: ProseGenerationService | None = None
        self._run_id: str | None = None

    def begin_turn(self) -> None:
        with self._state_lock:
            if self._closed.is_set():
                raise ValueError("小说项目已关闭")
            if self._prose is None:
                self._cancel.clear()

    def _event(
        self, plan: WriterInputPlan, status: str, message: str, **extra: Any
    ) -> dict[str, Any]:
        task = {
            **plan.summary(),
            "id": plan.id,
            "status": status,
            "message": message,
            "word_count": 0,
            "draft_text": "",
            "input_ready": True,
            **extra,
        }
        self.on_event(task)
        return task

    def prepare(
        self,
        chapter_id: str,
        revision: int,
        instruction: str,
        target_words: int,
        output_token_limit: int,
        related_refs: list[dict[str, Any]],
        style_refs: list[dict[str, Any]],
        recent_chapters: int,
        notes_summary: str = "",
    ) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise ValueError("已有正文任务，请等待或停止")
        try:
            if self._closed.is_set() or self._cancel.is_set():
                raise ValueError("小说项目已关闭")
            plan = self.inputs.prepare(
                chapter_id,
                revision,
                instruction,
                target_words,
                output_token_limit,
                self.gateway_factory(),
                related_refs,
                style_refs,
                recent_chapters,
                notes_summary,
            )
            with self._state_lock:
                if self._closed.is_set() or self._cancel.is_set():
                    raise ValueError("输入准备已取消，未调用正文模型")
                old, self._pending = self._pending, plan
            if old is not None:
                self._event(old, "CANCELLED", "已由新的输入提案替代，未调用正文模型。")
            self._event(
                plan, "AWAITING_CONFIRMATION", "请查看完整模型输入，确认后才会调用独立正文模型。"
            )
            return {
                "draft_id": plan.id,
                "chapter_id": plan.chapter_id,
                "status": "AWAITING_CONFIRMATION",
                "domain_kind": "WRITER_INPUT_PLAN",
                "note": "尚未调用正文模型；请作者在侧栏查看并确认输入，不要声称草稿已经生成。",
            }
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "完整输入读取失败，请检查大纲与正文文件。"
            )
            self.on_event(
                {
                    "id": new_id(),
                    "chapter_id": chapter_id,
                    "status": "FAILED",
                    "message": message,
                    "model": "独立写作模型",
                    "input_ready": False,
                }
            )
            raise ValueError(message) from exc
        finally:
            self._lock.release()

    def preview(self, request_id: str) -> dict[str, Any]:
        with self._state_lock:
            plan = self._pending
        if plan is not None and plan.id == request_id:
            return plan.preview()
        if request_id in self._completed:
            saved = self.snapshots.load(self._completed[request_id])
            return {**saved["metadata"], "messages": saved["messages"]}
        raise ValueError("输入提案已过期或不可用，请重新整理任务")

    def reject(self, request_id: str) -> bool:
        with self._state_lock:
            plan = self._pending
            if plan is None or plan.id != request_id:
                return False
            self._pending = None
        self._event(plan, "CANCELLED", "作者已取消输入提案，未调用正文模型。")
        return True

    def cancel(self) -> None:
        with self._state_lock:
            self._cancel.set()
            plan, self._pending = self._pending, None
            prose, run_id = self._prose, self._run_id
        if plan is not None:
            self._event(plan, "CANCELLED", "输入提案已取消，未调用正文模型。")
        if prose is not None and run_id is not None:
            prose.cancel(run_id)

    def revoke(self) -> None:
        self._closed.set()
        self.cancel()

    def confirm(self, request_id: str) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise ValueError("正文任务正在执行，请勿重复确认")
        try:
            with self._state_lock:
                plan = self._pending
                if plan is None or plan.id != request_id or self._closed.is_set():
                    raise ValueError("输入提案已失效或已经使用")
                self._pending = None
            gateway = self.gateway_factory()
            try:
                self.inputs.validate(plan, gateway)
            except (KeyError, RuntimeError, ValueError) as exc:
                self._event(plan, "STALE", "输入资料或配置已变化，请重新准备并确认。")
                raise ValueError("输入资料或配置已变化，请重新准备并确认。") from exc
            return self._generate(plan, gateway)
        finally:
            with self._state_lock:
                self._prose, self._run_id = None, None
            self._lock.release()

    def _generate(self, plan: WriterInputPlan, gateway: LLMGateway) -> dict[str, Any]:
        run = self.runs.create_preparing(
            chapter_id=plan.chapter_id,
            mode=CreationMode.BASIC,
            brief_id=None,
            brief_revision=None,
            model_provider_id=plan.provider_id,
            model_id=plan.model_id,
            output_token_limit=plan.output_token_limit,
            prompt_version=PROMPT_VERSION,
        )
        manifest = ContextManifest(
            create_manifest_id(),
            plan.chapter_id,
            run.id,
            plan.context_window - plan.output_token_limit,
            plan.output_token_limit,
            plan.estimated_tokens,
            tuple(
                SelectedManifestItem(
                    f"{plan.id}:{i}",
                    s.kind,
                    s.kind,
                    s.source_id,
                    s.source_id if s.kind == "FORMAL_MANUSCRIPT" else None,
                    s.revision,
                    s.source_hash,
                    ",".join(s.purposes) or s.title,
                    len(s.content.encode("utf-8")),
                    False,
                )
                for i, s in enumerate(plan.sources)
            ),
            (),
            (),
            utc_now(),
            target_chapter_revision=plan.revision,
        )
        try:
            ContextManifestRepository(self.project).save(manifest)
            metadata = {
                **plan.summary(),
                "author_confirmed": True,
                "target_hash": plan.target_hash,
                "editor_hash": plan.editor_hash,
                "constraints_hash": plan.constraints_hash,
                "references": [asdict(ref) for ref in plan.references],
                "adoption_source": asdict(plan.editor_source),
                "note_originals": [
                    {**n.summary(), "content": n.content} for n in plan.note_originals
                ],
            }
            self.snapshots.save(run.id, manifest.id, plan.messages, metadata)
            self.runs.mark_ready(run.id, manifest.id)
        except Exception:
            self.runs.fail_preparation(
                run.id, "WRITER_INPUT_SAVE_FAILED", "完整输入保存失败，未调用模型"
            )
            self._event(plan, "FAILED", "完整输入保存失败，未调用模型。")
            raise ValueError("完整输入保存失败，未调用模型。") from None
        with self._state_lock:
            prose = ProseGenerationService(
                gateway, self.snapshots, self.runs, CheckpointRepository(self.project, self.runs)
            )
            self._prose, self._run_id = prose, run.id
            self._completed[plan.id] = run.id
            if self._closed.is_set() or self._cancel.is_set():
                prose.cancel(run.id)
        self._event(plan, "GENERATING", "独立正文模型正在使用已确认的完整输入。", run_id=run.id)
        text = ""
        try:
            for event in prose.stream(run.id):
                if event.kind == ProseEventKind.DRAFT_CHUNK:
                    text += event.text
                    if len(text) > 200_000:
                        self.cancel()
                    self._event(
                        plan, "GENERATING", "正在接收候选正文", run_id=run.id, word_count=len(text)
                    )
        except (ValueError, OSError):
            # The message provider runs before ProseGenerationService's stream try/finally.
            if self.runs.get(run.id).status != GenerationStatus.READY:
                raise
            self.runs.transition(
                run.id,
                GenerationStatus.READY,
                GenerationStatus.FAILED,
                failure_code="INPUT_SNAPSHOT_UNAVAILABLE",
                failure_message="冻结输入无法读取，未重新检索资料或调用模型",
            )
        status = self.runs.get(run.id).status
        state = "CANCELLED" if self._closed.is_set() or self._cancel.is_set() else str(status)
        message = (
            "候选草稿保存在检查点，未覆盖正式正文。"
            if text
            else "已停止，未生成候选正文。"
            if state == "CANCELLED"
            else "正文生成未完成，请检查完整输入、连接与模型容量；未覆盖正式正文。"
        )
        self._event(
            plan,
            state,
            message,
            run_id=run.id,
            draft_text=text[:200_000],
            word_count=len(text),
        )
        return {
            "draft_id": plan.id,
            "run_id": run.id,
            "chapter_id": plan.chapter_id,
            "status": state,
            "domain_kind": "CANDIDATE_DRAFT",
            "content": text[:12_000],
            "truncated": len(text) > 12_000,
            "note": "未采用、未覆盖正式正文；生成结果与完整输入情况请查看侧栏状态。",
        }
