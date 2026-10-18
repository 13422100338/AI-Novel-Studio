from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.application.audit_claim_service import (
    AuditClaimService,
    AuditClaimsRequest,
)
from ai_novel_studio.application.audit_workflow_service import AuditWorkflowResult
from ai_novel_studio.application.compile_context_service import CompiledContext
from ai_novel_studio.application.selection_patch import (
    SelectionPatch,
    SelectionPatchCapture,
    SelectionPatchStaleError,
    SelectionPatchValidationError,
    finalize_selection_patch,
    replay_selection_patch,
    validate_selection_patch_capture,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.audit import AuditTargetKind
from ai_novel_studio.domain.changeset import (
    ChangeOperation,
    ChangeOperationKind,
    ChangeSet,
)
from ai_novel_studio.domain.generation import (
    AuditPolicy,
    CreationMode,
    GenerationProfile,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.harness.approval_resolver import (
    ApprovalResolution,
    ApprovalResolver,
    changeset_to_payload,
)
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest
from ai_novel_studio.harness.artifacts import ArtifactStore, ProjectArtifactBackend
from ai_novel_studio.harness.compile_step import CompileStepAdapter
from ai_novel_studio.harness.constitution_flow import ConstitutionFlowService
from ai_novel_studio.harness.draft_stream import (
    ChapterDraftStreamService,
    DraftCandidateResult,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.generation_package import EditorSnapshot, GenerationPackage
from ai_novel_studio.harness.model_adapter import HarnessModelAdapter, StreamingGateway
from ai_novel_studio.harness.model_roles import ModelRoleBinding
from ai_novel_studio.harness.prompt_compiler import (
    ComponentKind,
    ComponentStability,
    PromptCompiler,
    PromptComponent,
)
from ai_novel_studio.harness.run_engine import HarnessRunEngine
from ai_novel_studio.harness.run_state import HarnessRun, RunEventType, RunStage
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_WRITER_SYSTEM = (
    "你是长篇小说正文写手。严格遵守正典、当前章要求和知识边界；"
    "不得输出分析、解释或规划，不得调用工具。"
)
_SELECTION_WRITER_SYSTEM = (
    "你是长篇小说正文编辑。只改写用户给出的选区，严格遵守正典、当前章要求"
    "和知识边界；只输出可直接替换选区的正文，不得输出分析、解释、标题、"
    "Markdown 代码块或选区之外的内容。"
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_draft_messages(
    package: GenerationPackage,
    projection_text: str,
    writer_constitution: PromptComponent | None = None,
) -> tuple[LLMMessage, ...]:
    """Deterministic draft-model request assembly (design v0.3 §15, contract §5.2).

    HARNESS_SYSTEM (GLOBAL), the writer-only constitution projection
    (PROJECT) and TASK_BLOCK (RUN) form the stable prefix; the
    ContextProjection is a TURN component and the write instruction is
    CURRENT_INPUT, which the compiler always places last. The draft model
    only receives shared_creative_rules + writer_only_rules (§37.1); agent
    and approval rules never enter this request.
    """
    task_lines = [f"任务目标：{package.goal}"]
    if package.must_happen:
        task_lines.append("必须发生：" + "；".join(package.must_happen))
    if package.forbidden:
        task_lines.append("禁止：" + "；".join(package.forbidden))
    if package.scene_plan:
        task_lines.append("场景计划：" + "；".join(package.scene_plan))
    if package.pov:
        task_lines.append(f"视角：{package.pov}")
    if package.story_time:
        task_lines.append(f"故事时间：{package.story_time}")
    if package.narrative_sequence_boundary is not None:
        task_lines.append(f"叙事序边界：{package.narrative_sequence_boundary}")
    if package.knowledge_known:
        task_lines.append("已知(必须遵守)：" + "；".join(package.knowledge_known))
    if package.knowledge_unaware:
        task_lines.append("不得写出其知情(角色不知晓)：" + "；".join(package.knowledge_unaware))
    if package.knowledge_unknown:
        task_lines.append("未知(不得擅自补全)：" + "；".join(package.knowledge_unknown))
    if package.relationship_boundaries:
        task_lines.append("关系边界：" + "；".join(package.relationship_boundaries))
    if package.non_revealable_constraints:
        task_lines.append("不可揭示：" + "；".join(package.non_revealable_constraints))
    components: list[PromptComponent] = [
        PromptComponent(
            id="harness-writer-system",
            kind=ComponentKind.HARNESS_SYSTEM,
            role="system",
            stability=ComponentStability.GLOBAL,
            revision=1,
            content=_WRITER_SYSTEM,
            ordering_priority=100,
        ),
    ]
    if writer_constitution is not None:
        components.append(writer_constitution)
    components.extend(
        (
            PromptComponent(
                id="draft-task-block",
                kind=ComponentKind.TASK_BLOCK,
                role="system",
                stability=ComponentStability.RUN,
                revision=1,
                content="\n".join(task_lines),
                ordering_priority=300,
            ),
            PromptComponent(
                id="draft-context-projection",
                kind=ComponentKind.CONTEXT_PROJECTION,
                role="user",
                stability=ComponentStability.TURN,
                revision=1,
                content="编译上下文：\n" + (projection_text.strip() or "（无）"),
                ordering_priority=400,
            ),
            PromptComponent(
                id="draft-write-input",
                kind=ComponentKind.CURRENT_INPUT,
                role="user",
                stability=ComponentStability.TURN,
                revision=1,
                content="请创作本章正文。严格执行以上约束，只输出正文。",
                ordering_priority=500,
            ),
        )
    )
    return PromptCompiler(tuple(components)).compile().messages


def build_selection_draft_messages(
    package: GenerationPackage,
    projection_text: str,
    selected_markdown: str,
    writer_constitution: PromptComponent | None = None,
) -> tuple[LLMMessage, ...]:
    """Compile a selection-only rewrite request through the same writer route."""
    components: list[PromptComponent] = [
        PromptComponent(
            id="harness-selection-writer-system",
            kind=ComponentKind.HARNESS_SYSTEM,
            role="system",
            stability=ComponentStability.GLOBAL,
            revision=1,
            content=_SELECTION_WRITER_SYSTEM,
            ordering_priority=100,
        ),
    ]
    if writer_constitution is not None:
        components.append(writer_constitution)
    components.extend(
        (
            PromptComponent(
                id="selection-task-block",
                kind=ComponentKind.TASK_BLOCK,
                role="system",
                stability=ComponentStability.RUN,
                revision=1,
                content=f"修改目标：{package.goal}",
                ordering_priority=300,
            ),
            PromptComponent(
                id="selection-context-projection",
                kind=ComponentKind.CONTEXT_PROJECTION,
                role="user",
                stability=ComponentStability.TURN,
                revision=1,
                content="编译上下文：\n" + (projection_text.strip() or "（无）"),
                ordering_priority=400,
            ),
            PromptComponent(
                id="selection-current-input",
                kind=ComponentKind.CURRENT_INPUT,
                role="user",
                stability=ComponentStability.TURN,
                revision=1,
                content=(
                    "待修改选区如下。仅返回替换后的选区正文：\n"
                    "<selection>\n"
                    f"{selected_markdown}\n"
                    "</selection>"
                ),
                ordering_priority=500,
            ),
        )
    )
    return PromptCompiler(tuple(components)).compile().messages


class DraftBlockedError(RuntimeError):
    """The package carries unresolved plot decisions; the draft model must not run (§41)."""


_GENERATION_PAIRING: dict[GenerationProfile, AuditPolicy] = {
    GenerationProfile.QUICK: AuditPolicy.MINIMAL,
    GenerationProfile.NORMAL: AuditPolicy.STANDARD,
}


def validate_generation_pairing(
    generation_profile: GenerationProfile, audit_policy: AuditPolicy
) -> None:
    """§41.1: only QUICK+MINIMAL and NORMAL+STANDARD are generation modes.

    AuditPolicy.DEEP is a separate audit action on existing drafts or prose
    and can never become a third generation mode.
    """
    if not isinstance(generation_profile, GenerationProfile):
        raise ValueError("generation profile is invalid")
    if not isinstance(audit_policy, AuditPolicy):
        raise ValueError("audit policy is invalid")
    expected = _GENERATION_PAIRING[generation_profile]
    if audit_policy is not expected:
        raise ValueError(
            f"generation profile {generation_profile.value} requires audit "
            f"policy {expected.value}, got {audit_policy.value}"
        )


@dataclass(frozen=True, slots=True)
class ChapterGenerationResult:
    """Deterministic chain outcome handed to the approval step (design §52)."""

    run: HarnessRun
    compiled: CompiledContext
    package: GenerationPackage
    draft: DraftCandidateResult
    audit: AuditWorkflowResult
    approval: ApprovalRequest


class ChapterGenerationLoop:
    """Harness deterministic generation chain (design v0.3 §73 gate, §52).

    Compose the pieces built in B1-B7 into the single orchestration path:
    compile → package freeze → draft stream → deterministic audit → changeset
    approval. The author-approved commit runs through the ApprovalResolver
    (B3); this loop never writes domain data directly.
    """

    def __init__(
        self,
        engine: HarnessRunEngine,
        audit: AuditClaimService,
        resolver: ApprovalResolver,
        chapters: ChapterRepository,
        project: ProjectRepository,
        *,
        output_token_limit: int,
        mode: CreationMode = CreationMode.BASIC,
        audit_policy: AuditPolicy = AuditPolicy.MINIMAL,
        generation_profile: GenerationProfile = GenerationProfile.QUICK,
    ) -> None:
        validate_generation_pairing(generation_profile, audit_policy)
        self._engine = engine
        self._audit = audit
        self._resolver = resolver
        self._chapters = chapters
        self._project = project
        self._output_token_limit = output_token_limit
        self._mode = mode
        self._audit_policy = audit_policy
        self._generation_profile = generation_profile

    @classmethod
    def for_project(
        cls,
        project: ProjectRepository,
        gateway: StreamingGateway,
        binding: ModelRoleBinding,
        *,
        budget: TokenBudget,
        output_token_limit: int,
        checkpoint_chars: int = 2000,
        mode: CreationMode = CreationMode.BASIC,
        audit_policy: AuditPolicy = AuditPolicy.MINIMAL,
        generation_profile: GenerationProfile = GenerationProfile.QUICK,
    ) -> ChapterGenerationLoop:
        store = HarnessEventStore(HarnessEventRepository(project))
        compile_step = CompileStepAdapter.for_project(project, budget=budget)
        artifacts = ArtifactStore(ProjectArtifactBackend(project))
        adapter = HarnessModelAdapter("loop", (binding,), gateway)
        draft_stream = ChapterDraftStreamService(
            store, artifacts, adapter, checkpoint_chars=checkpoint_chars
        )
        engine = HarnessRunEngine(project, compile_step=compile_step, draft_stream=draft_stream)
        return cls(
            engine,
            AuditClaimService.for_project(project),
            ApprovalResolver.for_project(project),
            ChapterRepository(project),
            project,
            output_token_limit=output_token_limit,
            mode=mode,
            audit_policy=audit_policy,
            generation_profile=generation_profile,
        )

    def generate_candidate(
        self,
        goal: str,
        chapter_id: str,
        *,
        unresolved: tuple[str, ...] = (),
        selection_patch: SelectionPatchCapture | None = None,
    ) -> ChapterGenerationResult:
        run, _ = self._engine.start(goal, active_chapter_id=chapter_id)
        compiled = self._engine.compile_step(run.id)
        if not isinstance(compiled, CompiledContext):
            raise TypeError("compile step did not return CompiledContext")
        self._engine.transition(run.id, RunStage.CONTEXT_COMPILED)
        package = self._package(run, compiled, unresolved)
        self._engine.store.append(
            run.id,
            RunEventType.GENERATION_PACKAGE_READY,
            {
                "chapter_id": package.chapter_id,
                "editor_snapshot_revision": package.editor_snapshot.revision,
                "formal_revision": package.formal_revision,
                "context_manifest_id": package.context_manifest_id,
            },
        )
        self._engine.transition(run.id, RunStage.PACKAGE_READY)
        if not package.ready_for_draft_model:
            message = "；".join(package.draft_blocked_reasons)
            self._engine.transition(
                run.id,
                RunStage.INTERRUPTED,
                failure_code="DRAFT_BLOCKED",
                failure_message=message,
            )
            raise DraftBlockedError(f"draft model blocked for run {run.id}: {message}")
        selected: str | None = None
        if selection_patch is not None:
            try:
                selected = validate_selection_patch_capture(
                    selection_patch,
                    source=package.editor_snapshot.content,
                    chapter_id=package.chapter_id,
                    revision=package.formal_revision,
                )
            except (SelectionPatchStaleError, SelectionPatchValidationError):
                self._engine.transition(
                    run.id,
                    RunStage.STALE,
                    failure_code="SELECTION_PATCH_STALE",
                    failure_message="selection patch is stale",
                )
                raise DraftBlockedError("selection patch is stale") from None
        messages = (
            build_selection_draft_messages(
                package,
                compiled.projection.text,
                selected,
                self._writer_constitution(),
            )
            if selected is not None
            else build_draft_messages(
                package,
                compiled.projection.text,
                self._writer_constitution(),
            )
        )
        self._engine.transition(run.id, RunStage.MODEL_RUNNING)
        draft = self._engine.stream_draft(run.id, messages, self._output_token_limit)
        final_patch: SelectionPatch | None = None
        if selection_patch is not None:
            try:
                final_patch = finalize_selection_patch(
                    selection_patch,
                    source=package.editor_snapshot.content,
                    chapter_id=package.chapter_id,
                    revision=package.formal_revision,
                    replacement_candidate_id=draft.artifact.artifact_id,
                    replacement_text=draft.text,
                )
            except SelectionPatchStaleError:
                self._engine.transition(
                    run.id,
                    RunStage.STALE,
                    failure_code="SELECTION_PATCH_STALE",
                    failure_message="selection patch is stale",
                )
                raise DraftBlockedError("selection patch is stale") from None
            except SelectionPatchValidationError:
                self._engine.transition(
                    run.id,
                    RunStage.FAILED,
                    failure_code="SELECTION_PATCH_INVALID",
                    failure_message="selection patch is invalid",
                )
                raise DraftBlockedError("selection patch is invalid") from None
        committed_text = (
            draft.text
            if final_patch is None
            else replay_selection_patch(
                final_patch,
                source=package.editor_snapshot.content,
                chapter_id=package.chapter_id,
                revision=package.formal_revision,
            )
        )
        audit_draft = DraftCandidateResult(
            draft.artifact,
            committed_text,
            draft.usage,
        )
        audit_result = self._audit_draft(run, package, audit_draft)
        self._engine.transition(run.id, RunStage.AUDIT_COMPLETED)
        approval = self._propose_changeset(
            run,
            package,
            draft,
            committed_text=committed_text,
            selection_patch=final_patch,
        )
        return ChapterGenerationResult(
            run=run,
            compiled=compiled,
            package=package,
            draft=draft,
            audit=audit_result,
            approval=approval,
        )

    def finish(self, run_id: str) -> HarnessRun:
        return self._engine.transition(run_id, RunStage.COMPLETED)

    def cancel(self, run_id: str) -> HarnessRun:
        return self._engine.cancel(run_id)

    def commit_approved(self, request_id: str) -> ApprovalResolution:
        return self._resolver.resolve_and_commit(request_id, approved=True)

    def _package(
        self,
        run: HarnessRun,
        compiled: CompiledContext,
        unresolved: tuple[str, ...] = (),
    ) -> GenerationPackage:
        chapter = self._chapters.get_chapter(compiled.manifest.chapter_id, include_deleted=False)
        content = self._chapters.read_content_exact(chapter.id)
        snapshot = EditorSnapshot(
            chapter_id=chapter.id,
            content=content,
            revision=chapter.revision,
            content_hash=_sha256(content),
        )
        return GenerationPackage(
            chapter_id=chapter.id,
            editor_snapshot=snapshot,
            formal_revision=chapter.revision,
            generation_profile=self._generation_profile,
            audit_policy=self._audit_policy,
            goal=run.goal,
            context_manifest_id=compiled.manifest.id,
            unresolved=unresolved,
        )

    def _writer_constitution(self) -> PromptComponent | None:
        current = ProjectConstitutionRepository(self._project).current()
        if current is None:
            return None
        return ConstitutionFlowService.to_writer_prompt_component(current)

    def _audit_draft(
        self,
        run: HarnessRun,
        package: GenerationPackage,
        draft: DraftCandidateResult,
    ) -> AuditWorkflowResult:
        self._engine.store.append(
            run.id,
            RunEventType.AUDIT_STARTED,
            {"chapter_id": package.chapter_id},
        )
        result = self._audit.run(
            AuditClaimsRequest(
                chapter_id=package.chapter_id,
                target_kind=AuditTargetKind.GENERATED_DRAFT,
                target_id=run.id,
                target_revision=package.formal_revision,
                mode=self._mode,
                target_text=draft.text,
                audit_policy=package.audit_policy,
            )
        )
        self._engine.store.append(
            run.id,
            RunEventType.AUDIT_COMPLETED,
            {"finding_count": len(result.findings)},
        )
        return result

    def _propose_changeset(
        self,
        run: HarnessRun,
        package: GenerationPackage,
        draft: DraftCandidateResult,
        *,
        committed_text: str | None = None,
        selection_patch: SelectionPatch | None = None,
    ) -> ApprovalRequest:
        content = draft.text if committed_text is None else committed_text
        change_set = ChangeSet(
            str(new_id()),
            (
                ChangeOperation(
                    str(new_id()),
                    ChangeOperationKind.CHAPTER_CONTENT_REPLACE,
                    package.chapter_id,
                    package.formal_revision,
                    {
                        "content": (
                            selection_patch.result_hash if selection_patch is not None else content
                        ),
                        "source": "agent",
                        "reason": package.goal,
                        **(
                            {"selection_patch": selection_patch.to_payload()}
                            if selection_patch is not None
                            else {}
                        ),
                    },
                ),
            ),
        )
        self._engine.store.append(
            run.id,
            RunEventType.CHANGESET_READY,
            {"change_set_id": change_set.change_set_id, "operation_count": 1},
        )
        return self._engine.request_approval(
            run.id,
            ApprovalKind.CHANGESET,
            (
                f"候选稿替换选区({len(draft.text)} 字)"
                if selection_patch is not None
                else f"候选稿替换章节({len(draft.text)} 字)"
            ),
            payload=changeset_to_payload(change_set),
            idempotency_key=f"generate-{run.id}",
        )
