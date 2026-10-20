"""Ordered, unabridged author material for the independent prose model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.outline import outline_bundle_fingerprint, validate_outline_hash
from ai_novel_studio.infrastructure.llm import LLMGateway, LLMMessage, TaskPurpose
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.read_only_database import ReadOnlyDatabase

PROMPT_VERSION = "outline-prose-v1"


class OutlineRequiredError(ValueError):
    def __init__(self) -> None:
        super().__init__("开始正文生成前，请在大纲页面导入或新建并保存完整大纲。")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(value: object) -> str:
    return text_hash(json.dumps(value, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True, slots=True)
class ManuscriptRef:
    chapter_id: str
    revision: int
    source_hash: str
    start: int | None = None
    end: int | None = None

    @classmethod
    def parse(cls, value: object) -> ManuscriptRef:
        required = {"chapter_id", "revision", "source_hash"}
        if (
            not isinstance(value, dict)
            or not required <= value.keys()
            or value.keys() - required - {"start", "end"}
        ):
            raise ValueError("正文引用必须包含章节 ID、修订与完整原文哈希；不接受文件路径。")
        validate_id(value["chapter_id"])
        validate_outline_hash(value["source_hash"])
        if type(value["revision"]) is not int or value["revision"] < 0:
            raise ValueError("正文引用修订无效")
        start, end = value.get("start"), value.get("end")
        if (start is None) != (end is None) or (
            start is not None
            and (type(start) is not int or type(end) is not int or start < 0 or end <= start)
        ):
            raise ValueError("正文引用范围应为有效的半开字符区间")
        return cls(value["chapter_id"], value["revision"], value["source_hash"], start, end)


@dataclass(frozen=True, slots=True)
class WriterSource:
    kind: str
    source_id: str
    title: str
    revision: int
    content: str
    source_hash: str
    start: int | None = None
    end: int | None = None
    purposes: tuple[str, ...] = ()

    def summary(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_id": self.source_id,
            "title": self.title,
            "revision": self.revision,
            "source_hash": self.source_hash,
            "characters": len(self.content),
            "start": self.start,
            "end": self.end,
            "purposes": list(self.purposes),
        }


@dataclass(frozen=True, slots=True)
class WriterInputPlan:
    id: str
    project_id: str
    chapter_id: str
    revision: int
    target_hash: str
    editor_hash: str
    constraints_hash: str
    outline_fingerprint: str
    model_signature: str
    provider_id: str
    model_id: str
    output_token_limit: int
    target_words: int
    scope: str
    recent_chapters: int
    recent_chapter_ids: tuple[str, ...]
    editor_source: NovelEditorSnapshot
    references: tuple[ManuscriptRef, ...]
    sources: tuple[WriterSource, ...]
    messages: tuple[LLMMessage, ...]
    estimated_tokens: int
    context_window: int

    def summary(self) -> dict[str, Any]:
        return {
            "request_id": self.id,
            "chapter_id": self.chapter_id,
            "revision": self.revision,
            "scope": self.scope,
            "outline_fingerprint": self.outline_fingerprint,
            "model": self.model_id,
            "provider_id": self.provider_id,
            "estimated_tokens": self.estimated_tokens,
            "context_window": self.context_window,
            "output_token_limit": self.output_token_limit,
            "target_words": self.target_words,
            "recent_chapters": self.recent_chapters,
            "recent_chapter_ids": list(self.recent_chapter_ids),
            "sources": [s.summary() for s in self.sources],
        }

    def preview(self) -> dict[str, Any]:
        return {**self.summary(), "messages": [asdict(m) for m in self.messages]}


def model_signature(gateway: LLMGateway) -> str:
    route = gateway.configuration.routes.resolve(TaskPurpose.PROSE_GENERATION)
    profile = gateway.configuration.model(route)
    sampling = getattr(profile, "sampling", None)
    lookup_provider = getattr(gateway.configuration, "provider", None)
    provider = lookup_provider(route.provider_id) if callable(lookup_provider) else None
    connection = (
        tuple(
            getattr(provider, key, None)
            for key in ("base_url", "interface_type", "credential_id", "timeout_seconds")
        )
        if provider is not None
        else None
    )
    return fingerprint(
        (
            route.provider_id,
            route.model_id,
            asdict(profile.capabilities),
            asdict(sampling) if sampling is not None and is_dataclass(sampling) else None,
            connection,
        )
    )


class OutlineWriterInputService:
    def __init__(self, project: ProjectRepository, novel: NovelReadService) -> None:
        if project.project.id != novel.project_id:
            raise ValueError("正文输入项目身份不匹配")
        self.project = ProjectRepository(
            project.layout, ReadOnlyDatabase(project.database.path), project.project
        )
        self.novel = novel
        self.chapters = ChapterRepository(self.project)
        self.outlines = OutlineRepository(self.project)

    def _constraints(self, chapter_id: str) -> dict[str, Any]:
        guidance = ProjectGuidanceRepository(self.project).load()
        try:
            requirement = ChapterRequirementRepository(self.project).get(chapter_id)
        except KeyError:
            saved: dict[str, Any] = {"content": "", "revision": 0, "locked": False}
        else:
            if text_hash(requirement.content) != requirement.content_hash:
                raise ValueError("章要求与登记哈希不一致")
            saved = {
                "content": requirement.content,
                "revision": requirement.revision,
                "locked": requirement.is_locked,
            }
        return {
            "chapter": saved,
            "guidance": guidance.highest_system_prompt,
            "guidance_revision": guidance.revision,
        }

    def _reference(self, ref: ManuscriptRef) -> tuple[str, str]:
        chapter = self.chapters.get_chapter(ref.chapter_id, include_deleted=False)
        content = self.chapters.read_content_exact(ref.chapter_id)
        if chapter.revision != ref.revision or text_hash(content) != ref.source_hash:
            raise ValueError("引用正文已变更，请重新读取修订与原文哈希")
        if ref.end is not None and ref.end > len(content):
            raise ValueError("引用范围超过正式正文长度")
        return chapter.title, content[ref.start : ref.end]

    def validate(self, plan: WriterInputPlan, gateway: LLMGateway) -> None:
        editor = self.novel.editor_snapshot()
        target = self.chapters.get_chapter(plan.chapter_id, include_deleted=False)
        documents = tuple(d for d, _ in self.outlines.read_bundle())
        recent = self.chapters.list_before(plan.chapter_id)
        recent_ids = (
            tuple(c.id for c in recent[-plan.recent_chapters :]) if plan.recent_chapters else ()
        )
        if (
            editor.chapter_id != plan.chapter_id
            or fingerprint(asdict(editor)) != plan.editor_hash
            or target.revision != plan.revision
            or text_hash(self.chapters.read_content_exact(plan.chapter_id)) != plan.target_hash
            or outline_bundle_fingerprint(self.project.project.id, documents)
            != plan.outline_fingerprint
            or fingerprint(self._constraints(plan.chapter_id)) != plan.constraints_hash
            or model_signature(gateway) != plan.model_signature
            or recent_ids != plan.recent_chapter_ids
        ):
            raise ValueError("大纲、正文、选文、章要求或模型配置已变化，请重新准备并确认输入。")
        for ref in plan.references:
            self._reference(ref)

    def prepare(
        self,
        chapter_id: str,
        revision: int,
        instruction: str,
        target_words: int,
        output_token_limit: int,
        gateway: LLMGateway,
        related_refs: list[dict[str, Any]],
        style_refs: list[dict[str, Any]],
        recent_chapters: int,
    ) -> WriterInputPlan:
        if type(recent_chapters) is not int or not 0 <= recent_chapters <= 10:
            raise ValueError("近期章节数应为 0 至 10")
        if (
            not isinstance(related_refs, list)
            or not isinstance(style_refs, list)
            or len(related_refs) + len(style_refs) > 64
        ):
            raise ValueError("相关正文与范章合计最多 64 项，不能静默截断")
        references = [ManuscriptRef.parse(v) for v in related_refs]
        styles = [ManuscriptRef.parse(v) for v in style_refs]
        bundle = self.outlines.read_bundle()
        if not bundle:
            raise OutlineRequiredError()
        editor: NovelEditorSnapshot = self.novel.editor_snapshot()
        target = self.chapters.get_chapter(chapter_id, include_deleted=False)
        formal = self.chapters.read_content_exact(chapter_id)
        if (
            editor.chapter_id != chapter_id
            or editor.revision != revision
            or target.revision != revision
        ):
            raise ValueError("目标章节修订已变化")
        if not editor.dirty and editor.content != formal:
            raise ValueError("正文文件与编辑器不一致，请重新载入后准备输入")
        constraints = self._constraints(chapter_id)
        scope = "SELECTION" if editor.selection else "CHAPTER"
        scope_text = (
            (
                "仅处理选文，候选只对应选文；不得扩展到整章或把未来计划补成既成事实。\n选文原文：\n"
                + editor.selection
            )
            if editor.selection
            else "处理范围：当前章节候选。"
        )
        task = (
            f"作者本次要求：\n{instruction}\n目标章节：{target.title}（{chapter_id}）\n"
            f"目标约 {target_words} 字。\n{scope_text}\n"
            f"已保存章要求（锁定={constraints['chapter']['locked']}）原文：\n{constraints['chapter']['content']}"
        )
        sources = [
            WriterSource("FULL_OUTLINE", d.id, d.title, d.revision, s.content, d.content_hash)
            for d, s in bundle
        ]
        if constraints["guidance"]:
            guidance = constraints["guidance"]
            sources.insert(
                0,
                WriterSource(
                    "PROJECT_GUIDANCE",
                    self.project.project.id,
                    "作者最高指导",
                    constraints["guidance_revision"],
                    guidance,
                    text_hash(guidance),
                ),
            )
        sources.append(
            WriterSource(
                "AUTHOR_REQUEST", chapter_id, "作者要求与处理范围", revision, task, text_hash(task)
            )
        )
        if not editor.selection and editor.content:
            sources.append(
                WriterSource(
                    "EDITOR_BUFFER" if editor.dirty else "FORMAL_MANUSCRIPT",
                    chapter_id,
                    target.title,
                    revision,
                    editor.content,
                    text_hash(editor.content),
                )
            )
        before = self.chapters.list_before(chapter_id)
        recent = []
        for chapter in before[-recent_chapters:] if recent_chapters else []:
            raw = self.chapters.read_content_exact(chapter.id)
            recent.append(ManuscriptRef(chapter.id, chapter.revision, text_hash(raw)))
        seen: dict[tuple[str, int | None, int | None], int] = {}
        for purpose, group in (("RELATED", references), ("STYLE", styles), ("RECENT", recent)):
            for ref in group:
                title, content = self._reference(ref)
                key = (ref.chapter_id, ref.start, ref.end)
                if key in seen:
                    old = sources[seen[key]]
                    sources[seen[key]] = replace(
                        old, purposes=tuple(dict.fromkeys((*old.purposes, purpose)))
                    )
                else:
                    seen[key] = len(sources)
                    sources.append(
                        WriterSource(
                            "FORMAL_MANUSCRIPT",
                            ref.chapter_id,
                            title,
                            ref.revision,
                            content,
                            ref.source_hash,
                            ref.start,
                            ref.end,
                            (purpose,),
                        )
                    )
        messages = (
            LLMMessage(
                "system",
                "你是独立小说正文写手，只输出指定范围的候选正文，不输出分析或调用工具。"
                "完整大纲是 AUTHOR_PLAN，正式正文记录已发生事实；冲突由作者决定。"
                "严格遵守作者要求与选文边界，不把未来计划擅自写入选文。",
            ),
        ) + tuple(
            LLMMessage(
                "system" if s.kind == "PROJECT_GUIDANCE" else "user",
                f"[{s.kind}; 用途={','.join(s.purposes)}; {s.title}; id={s.source_id}; "
                f"revision={s.revision}; "
                f"sha256={s.source_hash}; chars={len(s.content)}]\n" + s.content,
            )
            for s in sources
        )
        if any("\x00" in m.content for m in messages):
            raise ValueError("输入材料含 NUL，未发送或改写")
        route = gateway.configuration.routes.resolve(TaskPurpose.PROSE_GENERATION)
        capabilities = gateway.configuration.model(route).capabilities
        window = capabilities.context_window
        if type(window) is not int or window <= 0:
            raise ValueError("正文模型上下文容量未知，请配置后重新准备输入")
        if (
            capabilities.max_output_tokens is not None
            and output_token_limit > capabilities.max_output_tokens
        ):
            raise ValueError("输出上限超过正文模型容量")
        estimate = sum(len(m.content.encode("utf-8")) + 16 for m in messages)
        if estimate + output_token_limit + max(1024, window // 20) > window:
            raise ValueError(
                f"正文模型预算不足：全文保守估算 {estimate:,}，容量 {window:,}；未摘要或裁剪大纲。"
            )
        plan = WriterInputPlan(
            new_id(),
            self.project.project.id,
            chapter_id,
            revision,
            text_hash(formal),
            fingerprint(asdict(editor)),
            fingerprint(constraints),
            outline_bundle_fingerprint(self.project.project.id, tuple(d for d, _ in bundle)),
            model_signature(gateway),
            route.provider_id,
            route.model_id,
            output_token_limit,
            target_words,
            scope,
            recent_chapters,
            tuple(ref.chapter_id for ref in recent),
            editor,
            tuple(references + styles + recent),
            tuple(sources),
            messages,
            estimate,
            window,
        )
        self.validate(plan, gateway)
        return plan
