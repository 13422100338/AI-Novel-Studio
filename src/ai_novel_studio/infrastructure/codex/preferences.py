"""Novel Studio's Codex choices; global Codex and Writer settings are separate."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text


@dataclass(frozen=True)
class CodexPreferences:
    model: str | None = None
    effort: str | None = None
    web_search: bool = False


class CodexPreferencesStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CodexPreferences:
        if not self.path.exists():
            return CodexPreferences()
        try:
            if self.path.stat().st_size > 16_384:
                raise ValueError
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or type(value.get("version")) is not int
                or value["version"] != 1
            ):
                raise ValueError
            for key in ("model", "effort"):
                item = value.get(key)
                if item is not None and (not isinstance(item, str) or not 0 < len(item) <= 256):
                    raise ValueError
            if type(value.get("web_search")) is not bool:
                raise ValueError
            return CodexPreferences(value.get("model"), value.get("effort"), value["web_search"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Codex 设置损坏，原文件已保留") from exc

    def save(self, preferences: CodexPreferences) -> None:
        self.load()  # Never overwrite an unreadable settings file.
        atomic_write_text(self.path, json.dumps({"version": 1, **asdict(preferences)}))
