"""One bounded presentation summary for all novel reads in an author turn."""

from __future__ import annotations

import json
from typing import Any


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and len(value) <= 2_000_000:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    return {}


class NovelReadProgress:
    def __init__(self) -> None:
        self.calls: dict[str, str] = {}
        self.chapters: set[str] = set()
        self.terminal: str | None = None

    def update(self, item: dict[str, Any]) -> dict[str, Any]:
        key = str(item.get("id", ""))
        state = str(item.get("status", "inProgress"))
        result = _mapping(item.get("result"))
        if result.get("isError"):
            state = "failed"
        if self.calls.get(key) not in {"completed", "failed"} or state in {"completed", "failed"}:
            self.calls[key] = state
        if state == "completed":
            payload = _mapping(result.get("structuredContent"))
            if not payload:
                for part in (
                    result.get("content", []) if isinstance(result.get("content"), list) else []
                ):
                    if isinstance(part, dict) and part.get("type") == "text":
                        payload = _mapping(part.get("text"))
                        if payload:
                            break
            if item.get("tool") == "read_novel_chapter":
                arguments = _mapping(item.get("arguments"))
                chapter_id = payload.get("chapter_id") or arguments.get("chapter_id")
                if isinstance(chapter_id, str):
                    self.chapters.add(chapter_id)
            elif item.get("tool") == "read_novel_chapters":
                for entry in (
                    payload.get("chapters", []) if isinstance(payload.get("chapters"), list) else []
                ):
                    if isinstance(entry, dict) and isinstance(entry.get("chapter_id"), str):
                        self.chapters.add(entry["chapter_id"])
        return self.presentation()

    def finish(self, state: str) -> dict[str, Any]:
        self.terminal = (
            "CANCELLED"
            if state == "interrupted"
            else "FAILED"
            if state == "failed" or "failed" in self.calls.values()
            else "DONE"
        )
        return self.presentation()

    def presentation(self) -> dict[str, Any]:
        completed = sum(state == "completed" for state in self.calls.values())
        failed = sum(state == "failed" for state in self.calls.values())
        pending = len(self.calls) - completed - failed
        state = self.terminal or ("RUNNING" if pending else "FAILED" if failed else "DONE")
        parts = []
        if self.chapters:
            parts.append(f"已读取 {len(self.chapters)} 章内容")
        parts.append(f"资料查询 {completed}/{len(self.calls)} 项")
        if failed:
            parts.append(f"{failed} 项失败")
        parts.append(
            {
                "RUNNING": "正在读取",
                "DONE": "读取完成",
                "FAILED": "读取中断",
                "CANCELLED": "已停止读取",
            }.get(state, "读取中")
        )
        return dict(
            label="小说资料汇总",
            text=" · ".join(parts),
            busy=state == "RUNNING",
            status=state,
            state=state,
        )
