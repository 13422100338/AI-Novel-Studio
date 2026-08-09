from __future__ import annotations

from typing import cast

from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionExtractionAlreadyExistsError,
    ViewAssertionService,
)
from ai_novel_studio.domain.view import EpistemicStatus, ViewAssertion, ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.llm.contract_runner import (
    ContractValidationError,
    JsonField,
    JsonObjectContract,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage, TaskPurpose
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_CONTRACT = JsonObjectContract((JsonField("assertions", list),))
_MAX_CANDIDATES = 12
_OUTPUT_TOKEN_LIMIT = 3_000
_SUPPORTED_VIEW_TYPES = {ViewType.CHARACTER_VIEW, ViewType.READER_VIEW}


class ViewAssertionExtractionService:
    """Extracts one chapter into non-authoritative View Assertion candidates."""

    def __init__(
        self, runner: LLMContractRunner, project: ProjectRepository | None = None
    ) -> None:
        self._runner = runner
        self._project = project

    def extract_current_chapter(self, chapter_id: str) -> tuple[ViewAssertion, ...]:
        if self._project is None:
            raise ValueError("提取服务尚未绑定项目")
        return self.extract(self._project, chapter_id)

    def extract(
        self, project: ProjectRepository, chapter_id: str
    ) -> tuple[ViewAssertion, ...]:
        chapters = ChapterRepository(project)
        chapter = chapters.get_chapter(chapter_id, include_deleted=False)
        content = chapters.read_content(chapter.id)
        if not content.strip():
            raise ValueError("当前章节没有可提取的正文")
        assertions = ViewAssertionService(project)
        if assertions.has_current_model_candidates(
            source_id=chapter.id,
            source_revision=chapter.revision,
        ):
            raise ViewAssertionExtractionAlreadyExistsError(
                "该章节当前修订已有有效的模型 View Assertion 候选"
            )
        characters = CharacterMemoryRepository(project).list_characters()
        active_ids = frozenset(character.id for character in characters)
        if not active_ids:
            raise ValueError("没有可用于 View Assertion 的活跃人物")
        chapter_sequence = chapters.get_chapter_sequence(chapter.id)
        payload = self._runner.run_json(
            TaskPurpose.MEMORY_EXTRACTION,
            self._messages(chapter.id, chapter.revision, content, active_ids),
            _OUTPUT_TOKEN_LIMIT,
            _CONTRACT,
            lambda value: self._validate_payload(
                value,
                active_ids=active_ids,
                narrative_visible_from_sequence=chapter_sequence + 1,
            ),
        )
        drafts = cast(tuple[ViewAssertionDraft, ...], payload["drafts"])
        return assertions.create_model_candidates_for_chapter(
            drafts,
            source_id=chapter.id,
            source_revision=chapter.revision,
        )

    @staticmethod
    def _messages(
        chapter_id: str,
        revision: int,
        content: str,
        active_ids: frozenset[str],
    ) -> tuple[LLMMessage, ...]:
        return (
            LLMMessage(
                "system",
                "仅提取当前章节中的候选 View Assertion。返回 JSON 对象，"
                "顶层 assertions 必须为数组。每项只可含 subject_id、view_type、"
                "content、viewer_subject_id、epistemic_status、valid_from_sequence、"
                "valid_to_sequence、story_time_label。只可使用提供的活跃人物 ID；"
                "view_type 只可为 CHARACTER_VIEW 或 READER_VIEW。输出仅供人工审查，"
                "不得创建人物、不得推断未知身份、不得包含叙事可见性或来源字段。"
                f"活跃人物 IDs：{', '.join(sorted(active_ids))}",
            ),
            LLMMessage(
                "user",
                f"source_chapter_id={chapter_id}\nrevision={revision}\n\n"
                f"<chapter_text>\n{content}\n</chapter_text>",
            ),
        )

    @staticmethod
    def _validate_payload(
        payload: dict[str, object],
        *,
        active_ids: frozenset[str],
        narrative_visible_from_sequence: int,
    ) -> dict[str, object]:
        values = payload["assertions"]
        try:
            if not isinstance(values, list):
                raise ValueError("assertions 必须是数组")
            if len(values) > _MAX_CANDIDATES:
                raise ValueError(
                    f"assertions may contain at most {_MAX_CANDIDATES} items"
                )
            drafts = tuple(
                ViewAssertionExtractionService._draft(
                    value,
                    active_ids=active_ids,
                    narrative_visible_from_sequence=narrative_visible_from_sequence,
                )
                for value in values
            )
        except ValueError as error:
            raise ContractValidationError(str(error)) from error
        return {"drafts": drafts}

    @staticmethod
    def _draft(
        value: object,
        *,
        active_ids: frozenset[str],
        narrative_visible_from_sequence: int,
    ) -> ViewAssertionDraft:
        if not isinstance(value, dict):
            raise ValueError("每个 assertion 必须是对象")
        subject_id = ViewAssertionExtractionService._required_string(value, "subject_id")
        if subject_id not in active_ids:
            raise ValueError("assertion 使用了未知或非活跃人物 ID")
        view_type = ViewType(
            ViewAssertionExtractionService._required_string(value, "view_type")
        )
        if view_type not in _SUPPORTED_VIEW_TYPES:
            raise ValueError("不支持该 View Assertion 类型")
        viewer_id = ViewAssertionExtractionService._optional_string(
            value, "viewer_subject_id"
        )
        if viewer_id is not None and viewer_id not in active_ids:
            raise ValueError("viewer_subject_id 必须是活跃人物 ID")
        epistemic_value = ViewAssertionExtractionService._optional_string(
            value, "epistemic_status"
        )
        epistemic_status = (
            EpistemicStatus(epistemic_value) if epistemic_value is not None else None
        )
        return ViewAssertionDraft(
            subject_id=subject_id,
            view_type=view_type,
            content=ViewAssertionExtractionService._required_string(value, "content"),
            viewer_subject_id=viewer_id,
            epistemic_status=epistemic_status,
            valid_from_sequence=ViewAssertionExtractionService._optional_sequence(
                value, "valid_from_sequence"
            ),
            valid_to_sequence=ViewAssertionExtractionService._optional_sequence(
                value, "valid_to_sequence"
            ),
            story_time_label=ViewAssertionExtractionService._optional_string(
                value, "story_time_label"
            ),
            narrative_visible_from_sequence=narrative_visible_from_sequence,
        )

    @staticmethod
    def _required_string(value: dict[object, object], field: str) -> str:
        result = ViewAssertionExtractionService._optional_string(value, field)
        if result is None:
            raise ValueError(f"{field} is required")
        return result

    @staticmethod
    def _optional_string(value: dict[object, object], field: str) -> str | None:
        result = value.get(field)
        if result is None:
            return None
        if not isinstance(result, str):
            raise ValueError(f"{field} 必须是字符串")
        return result.strip() or None

    @staticmethod
    def _optional_sequence(value: dict[object, object], field: str) -> int | None:
        result = value.get(field)
        if result is None:
            return None
        if isinstance(result, bool) or not isinstance(result, int) or result < 0:
            raise ValueError(f"{field} 必须是非负整数")
        return result
