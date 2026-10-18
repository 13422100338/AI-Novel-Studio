from __future__ import annotations

import json
import re
from pathlib import Path
from threading import RLock
from uuid import UUID

from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text


def thread_identity(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Codex 会话编号无效")
    return value


class CodexSessionIndex:
    """Store opaque session IDs only; malformed files are never overwritten."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        if self.path.stat().st_size > 1_000_000:
            raise ValueError("Codex 会话索引过大")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or type(data.get("version")) is not int
                or data.get("version") != 1
            ):
                raise ValueError
            threads = data["threads"]
            if not isinstance(threads, dict):
                raise ValueError
            return {str(UUID(key)): thread_identity(value) for key, value in threads.items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Codex 会话索引损坏，原文件已保留") from exc

    def get(self, project_id: str) -> str | None:
        with self._lock:
            return self._load().get(str(UUID(project_id)))

    def put(self, project_id: str, thread_id: str) -> None:
        key = str(UUID(project_id))
        value = thread_identity(thread_id)
        with self._lock:
            threads = self._load()
            history = self.history(key)
            if value not in history:
                history.append(value)
            histories = {}
            if self.path.exists():
                histories = json.loads(self.path.read_text(encoding="utf-8")).get("history", {})
                if not isinstance(histories, dict):
                    raise ValueError("Codex 会话索引损坏，原文件已保留")
            histories[key] = history
            threads[key] = value
            atomic_write_text(
                self.path, json.dumps({"version": 1, "threads": threads, "history": histories})
            )

    def history(self, project_id: str) -> list[str]:
        key = str(UUID(project_id))
        with self._lock:
            threads = self._load()
            if not self.path.exists():
                return []
            histories = json.loads(self.path.read_text(encoding="utf-8")).get("history", {})
            if not isinstance(histories, dict):
                raise ValueError("Codex 会话索引损坏，原文件已保留")
            values = histories.get(key, [])
            if not isinstance(values, list):
                raise ValueError("Codex 会话索引损坏，原文件已保留")
            result = [thread_identity(value) for value in values]
            if key in threads and threads[key] not in result:
                result.append(threads[key])
            return result
