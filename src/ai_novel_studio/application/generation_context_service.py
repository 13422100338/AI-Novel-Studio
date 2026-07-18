from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from ai_novel_studio.application.generation_memory_context_provider import (
    GenerationMemoryContextProvider,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
)
from ai_novel_studio.core.context.context_manifest import (
    ContextManifest,
    ContextManifestRepository,
)
from ai_novel_studio.core.context.prose_prompt import (
    PROSE_PROMPT_VERSION,
    build_prose_messages,
    system_prompt_blocks,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.generation import (
    BriefStatus,
    ChapterBrief,
    ChapterRequirement,
    CreationMode,
    GenerationRun,
)
from ai_novel_studio.infrastructure.llm import LLMMessage, ModelCapabilities
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class StandardModeBriefError(ValueError):
    pass


class UnknownContextWindowError(ValueError):
    pass


BASIC_UNKNOWN_CONTEXT_INPUT_LIMIT = 4_096


@dataclass(frozen=True, slots=True)
class GenerationPreparationRequest:
    chapter_id: str
    mode: CreationMode
    brief_id: str | None
    output_token_limit: int
    model_capabilities: ModelCapabilities
    target_words: int
    model_provider_id: str
    model_id: str
    safety_margin: int = 1024

    def __post_init__(self) -> None:
        if not self.chapter_id.strip():
            raise ValueError("章节 ID 不能为空")
        if self.target_words <= 0:
            raise ValueError("目标字数必须大于零")
        if not self.model_provider_id.strip() or not self.model_id.strip():
            raise ValueError("生成准备必须绑定连接和模型")


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    run: GenerationRun
    manifest: ContextManifest
    selected_blocks: tuple[ContextBlock, ...]
    messages: tuple[LLMMessage, ...]


class GenerationContextService:
    def __init__(
        self,
        project: ProjectRepository,
        chapters: ChapterRepository,
        requirements: ChapterRequirementRepository,
        briefs: ChapterBriefRepository,
        runs: GenerationRepository,
        manifests: ContextManifestRepository,
        builder: ContextBuilder | None = None,
    ) -> None:
        self.project = project
        self.chapters = chapters
        self.requirements = requirements
        self.briefs = briefs
        self.runs = runs
        self.manifests = manifests
        self.builder = builder or ContextBuilder()
        self.memory_context = GenerationMemoryContextProvider(project)
        self.project_guidance = ProjectGuidanceService(
            ProjectGuidanceRepository(project)
        )

    def prepare(self, request: GenerationPreparationRequest) -> PreparedGeneration:
        requirement = self.requirements.get(request.chapter_id)
        if not requirement.content.strip():
            raise ValueError("当前章要求不能为空")
        brief = self._validated_brief(request)
        context_window = request.model_capabilities.context_window
        context_warning: str | None = None
        if context_window is None:
            if request.mode != CreationMode.BASIC:
                raise UnknownContextWindowError("模型上下文窗口未知，无法安全准备生成")
            context_window = (
                request.output_token_limit
                + request.safety_margin
                + BASIC_UNKNOWN_CONTEXT_INPUT_LIMIT
            )
            context_warning = (
                "模型未报告上下文窗口；快速模式仅使用保守的 "
                f"{BASIC_UNKNOWN_CONTEXT_INPUT_LIMIT} Token 输入预算"
            )
        budget = TokenBudget(
            context_window,
            request.output_token_limit,
            request.safety_margin,
        )
        budget.validate_model_output_limit(request.model_capabilities.max_output_tokens)

        run = self.runs.create_preparing(
            chapter_id=request.chapter_id,
            mode=request.mode,
            brief_id=brief.id if brief is not None else None,
            brief_revision=brief.revision if brief is not None else None,
            model_provider_id=request.model_provider_id,
            model_id=request.model_id,
            output_token_limit=request.output_token_limit,
            prompt_version=PROSE_PROMPT_VERSION,
        )
        try:
            blocks = self._blocks(request, requirement, brief)
            built = self.builder.build(
                ContextBuildRequest(request.chapter_id, run.id, budget, blocks)
            )
            manifest = built.manifest
            if context_warning is not None:
                manifest = replace(
                    manifest,
                    warnings=manifest.warnings + (context_warning,),
                )
            self.manifests.save(manifest)
            selected = self._selected_blocks(blocks, manifest)
            messages = build_prose_messages(requirement, brief, selected)
            ready = self.runs.mark_ready(run.id, manifest.id)
        except BaseException as error:
            self.runs.fail_preparation(run.id, type(error).__name__, str(error))
            raise

        return PreparedGeneration(ready, manifest, selected, messages)

    def _validated_brief(
        self, request: GenerationPreparationRequest
    ) -> ChapterBrief | None:
        if request.mode == CreationMode.BASIC:
            return None
        if request.brief_id is None:
            raise StandardModeBriefError("标准模式需要当前章节的冻结 Brief")
        brief = self.briefs.get(request.brief_id)
        if brief.chapter_id != request.chapter_id:
            raise StandardModeBriefError("冻结 Brief 不属于当前章节")
        if brief.status == BriefStatus.STALE:
            raise StandardModeBriefError("冻结 Brief 已过期，请重新编译")
        if brief.status != BriefStatus.FROZEN:
            raise StandardModeBriefError("标准模式只能使用冻结 Brief")
        requirement = self.requirements.get(request.chapter_id)
        requirement_sources = tuple(
            source
            for source in self.briefs.list_sources(brief.id)
            if source.source_type == "CHAPTER_REQUIREMENT"
        )
        if len(requirement_sources) != 1:
            raise StandardModeBriefError("冻结 Brief 缺少唯一的当前章要求来源")
        source = requirement_sources[0]
        if (
            source.source_id != requirement.id
            or source.source_revision != requirement.revision
            or source.source_hash != requirement.content_hash
        ):
            raise StandardModeBriefError("冻结 Brief 来源已经过期")
        return brief

    def _blocks(
        self,
        request: GenerationPreparationRequest,
        requirement: ChapterRequirement,
        brief: ChapterBrief | None,
    ) -> tuple[ContextBlock, ...]:
        blocks: list[ContextBlock] = list(system_prompt_blocks())
        guidance = self.project_guidance.load()
        if guidance.highest_system_prompt.strip():
            blocks.append(
                ContextBlock(
                    "project-guidance",
                    "PROJECT_GUIDANCE",
                    guidance.highest_system_prompt,
                    2,
                    True,
                    "PROJECT_GUIDANCE",
                    guidance.project_id,
                    None,
                    guidance.revision,
                    _hash(guidance.highest_system_prompt),
                    "作者人工维护的全书最高创作指令",
                )
            )
        blocks.extend(
            (
                ContextBlock(
                    "target-words",
                    "TARGET",
                    str(request.target_words),
                    3,
                    True,
                    "GENERATION_REQUEST",
                    request.chapter_id,
                    request.chapter_id,
                    requirement.revision,
                    _hash(str(request.target_words)),
                    "用户设置的目标字数",
                ),
                ContextBlock(
                    "chapter-requirement",
                    "REQUIREMENT",
                    requirement.content,
                    4,
                    True,
                    "CHAPTER_REQUIREMENT",
                    requirement.id,
                    request.chapter_id,
                    requirement.revision,
                    requirement.content_hash,
                    "当前章不可覆盖的用户要求",
                ),
            )
        )
        if brief is not None:
            blocks.append(
                ContextBlock(
                    "frozen-brief",
                    "BRIEF",
                    _brief_constraints(brief),
                    5,
                    True,
                    "CHAPTER_BRIEF",
                    brief.id,
                    request.chapter_id,
                    brief.revision,
                    brief.content_hash,
                    "标准模式冻结 Brief",
                )
            )
            memory = _brief_memory(brief)
            if memory:
                blocks.append(
                    ContextBlock(
                        "brief-memory",
                        "MEMORY",
                        memory,
                        30,
                        False,
                        "CHAPTER_BRIEF",
                        brief.id,
                        request.chapter_id,
                        brief.revision,
                        brief.content_hash,
                        "冻结 Brief 中的人物、知识、线索和文风",
                    )
                )

        previous = self.chapters.list_before(request.chapter_id)
        recent_contents: list[tuple[Chapter, str]] = []
        for chapter in tuple(reversed(previous))[:3]:
            content = self.chapters.read_content(chapter.id)
            if not content.strip():
                continue
            recent_contents.append((chapter, content))
        blocks.extend(
            self.memory_context.blocks(
                request.chapter_id,
                requirement.content,
                tuple(content for _chapter, content in recent_contents),
                brief.participants if brief is not None else (),
                pov_character_id=(
                    brief.pov_character_id if brief is not None else None
                ),
            )
        )
        for distance, (chapter, content) in enumerate(recent_contents, start=1):
            fallback = chapter.synopsis.strip() or None
            blocks.append(
                ContextBlock(
                    f"recent-{chapter.id}",
                    "RECENT_FULL",
                    f"《{chapter.title}》\n{content}",
                    10 + distance,
                    False,
                    "CHAPTER",
                    chapter.id,
                    chapter.id,
                    chapter.revision,
                    _hash(content),
                    f"近期第 {distance} 章全文：{chapter.title}",
                    fallback_content=(
                        f"《{chapter.title}》摘要\n{fallback}" if fallback is not None else None
                    ),
                )
            )
        return tuple(blocks)

    @staticmethod
    def _selected_blocks(
        blocks: tuple[ContextBlock, ...], manifest: ContextManifest
    ) -> tuple[ContextBlock, ...]:
        by_id = {block.id: block for block in blocks}
        selected: list[ContextBlock] = []
        for item in manifest.selected:
            block = by_id[item.block_id]
            if item.used_fallback and block.fallback_content is not None:
                block = replace(block, content=block.fallback_content)
            selected.append(block)
        return tuple(selected)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _brief_constraints(brief: ChapterBrief) -> str:
    return "\n".join(
        (
            f"戏剧功能：{brief.dramatic_purpose}",
            "必须事件：" + "；".join(brief.hard_events),
            "软目标：" + "；".join(brief.soft_goals),
            "禁止改动：" + "；".join(brief.prohibited_changes),
            "创作自由：" + "；".join(brief.creative_freedom),
        )
    )


def _brief_memory(brief: ChapterBrief) -> str:
    sections = (
        ("知识边界", brief.knowledge),
        ("线索动作", brief.clue_actions),
        ("文风规则", brief.style_rules),
    )
    return "\n".join(
        f"{title}：{'；'.join(values)}" for title, values in sections if values
    )
