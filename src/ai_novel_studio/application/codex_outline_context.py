"""Complete author outlines and explicit capacity checks for Codex turns."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ai_novel_studio.core.outline_links import registered_chapter_path, scan_chapter_links
from ai_novel_studio.domain.outline import outline_bundle_fingerprint
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_link_repository import OutlineLinkRepository
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineIntegrityError,
    OutlineRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.read_only_database import ReadOnlyDatabase

OUTLINE_INPUT_PREFIX = "[AI Novel Studio COMPLETE_OUTLINE v1 "


def json_input_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def visible_user_text(content: list[dict[str, Any]]) -> str:
    texts = [
        p["text"] for p in content if p.get("type") == "text" and isinstance(p.get("text"), str)
    ]
    if len(texts) > 1 and all(text.startswith(OUTLINE_INPUT_PREFIX) for text in texts[:-1]):
        return str(texts[-1])
    return "\n".join(texts)


@dataclass(frozen=True, slots=True)
class OutlineTurnContext:
    fingerprint: str
    texts: tuple[str, ...]
    documents: int
    characters: int
    confirmed_links: int
    pending_links: int

    def inputs(self) -> list[dict[str, object]]:
        return [{"type": "text", "text": text} for text in self.texts]

    def summary(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "documents": self.documents,
            "characters": self.characters,
            "confirmedLinks": self.confirmed_links,
            "pendingLinks": self.pending_links,
        }


class CodexOutlineContext:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = ProjectRepository(
            project.layout, ReadOnlyDatabase(project.database.path), project.project
        )
        self.project_id = project.project.id

    def snapshot(self) -> OutlineTurnContext | None:
        outlines = OutlineRepository(self.project)
        try:
            bundle = outlines.read_bundle()
        except (OSError, ValueError, OutlineIntegrityError) as exc:
            raise ValueError(
                "完整大纲读取失败，请先在大纲页面检查并保存或恢复；未发送旧版本。"
            ) from exc
        if not bundle:
            return None
        documents = tuple(document for document, _ in bundle)
        fingerprint = outline_bundle_fingerprint(self.project_id, documents)
        texts = tuple(
            f"{OUTLINE_INPUT_PREFIX}document={document.id}; revision={document.revision}; "
            f"sha256={document.content_hash}; bundle={fingerprint}; chars={len(source.content)}]\n"
            f"标题：{document.title}\n以下为完整 AUTHOR_PLAN 原文，不是已发生的正文事实：\n"
            + source.content
            + "\n[END COMPLETE_OUTLINE]\n"
            for document, source in bundle
        )
        confirmed: list[dict[str, object]] = []
        pending = 0
        try:
            chapters = ChapterRepository(self.project).list_chapters()
            paths = {
                path: chapter.id
                for chapter in chapters
                if (path := registered_chapter_path(self.project.layout.root, chapter.content_path))
                is not None
            }
            matches = {
                (document.id, m.line, m.column, m.quote, m.chapter_id)
                for document, source in bundle
                for m in scan_chapter_links(
                    source.content,
                    self.project.layout.root / "outlines" / f"{document.id}.md",
                    paths,
                )
            }
            for link in OutlineLinkRepository(self.project).list_registered():
                if not link.active:
                    continue
                if (
                    link.confirmed_fingerprint == fingerprint
                    and (
                        link.document_id,
                        link.source_line,
                        link.source_column,
                        link.source_quote,
                        link.chapter_id,
                    )
                    in matches
                ):
                    confirmed.append(
                        {
                            "document_id": link.document_id,
                            "line": link.source_line,
                            "chapter_id": link.chapter_id,
                            "link": link.source_quote,
                        }
                    )
                else:
                    pending += 1
        except (sqlite3.Error, ValueError, OutlineIntegrityError):
            # A broken optional index cannot replace or suppress the complete outline.
            confirmed, pending = [], -1
        if outline_bundle_fingerprint(self.project_id, outlines.list_documents()) != fingerprint:
            raise ValueError("收集完整大纲期间版本已变更，请重新发送。")
        texts += (
            f"{OUTLINE_INPUT_PREFIX}bundle={fingerprint}; CONFIRMED_OUTLINE_LINKS]\n"
            + json.dumps(confirmed, ensure_ascii=False)
            + "\n仅这些关联已在本版本确认；其他原文链接待作者确认。"
            "需要原文时用 chapter_id 调用 read_novel_chapters，不自动携带正文。\n"
            "[END COMPLETE_OUTLINE]\n",
        )
        return OutlineTurnContext(
            fingerprint,
            texts,
            len(bundle),
            sum(len(s.content) for _, s in bundle),
            len(confirmed),
            pending,
        )


def check_outline_capacity(
    config: dict[str, Any],
    inputs: list[dict[str, object]],
    history_tokens: int,
    runtime_window: int | None = None,
) -> dict[str, int]:
    window = config.get("model_context_window")
    if type(window) is not int or window <= 0:
        raise ValueError(
            "Codex 上下文容量未知，请配置 model_context_window 后重试；完整大纲未发送。"
        )
    if type(runtime_window) is int and runtime_window > 0:
        window = min(window, runtime_window)
    threshold = config.get("model_auto_compact_token_limit")
    if type(threshold) is int and threshold > 0:
        window = min(window, threshold)
    # UTF-8 bytes conservatively bound text tokens; never use bytes/4 for Chinese.
    # Hidden system/tool messages and model output still need their own reserve.
    incoming = json_input_size(inputs)
    images = sum(item.get("type") == "localImage" for item in inputs)
    reserve = 65_536 + 32_768 + window // 20 + images * 32_768
    required = history_tokens + incoming + reserve
    if required > window:
        raise ValueError(
            f"Codex 上下文预算不足：保守估算 {required:,} / 可用 {window:,} tokens"
            f"（本轮文本 {incoming:,}，历史 {history_tokens:,}，预留 {reserve:,}）。"
            "完整大纲未裁剪，请新建会话、减少可选附件或调整容量配置。"
        )
    return {"estimatedTokens": required, "contextLimit": window}
