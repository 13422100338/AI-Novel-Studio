from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, Signal, Slot
from shiboken6 import isValid

from ai_novel_studio.application.codex_controls_service import (
    CodexControlSnapshot,
    CodexControlsService,
)
from ai_novel_studio.infrastructure.codex.app_server import CodexConnectionError
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferences, CodexPreferencesStore


def codex_state_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData" / "Local") / "AI Novel Studio"


def default_preferences_store() -> CodexPreferencesStore:
    return CodexPreferencesStore(codex_state_root() / "codex-preferences.json")


class _Refresh(QRunnable):
    def __init__(self, bridge: CodexControlsBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def run(self) -> None:
        if not isValid(self.bridge):
            return
        try:
            snapshot = self.bridge.service.refresh()
        except CodexConnectionError as exc:
            error = str(exc)
        except Exception:
            error = "Codex 目录刷新失败，请刷新后重试"
        else:
            if isValid(self.bridge):
                self.bridge._loaded.emit(snapshot)
            return
        if isValid(self.bridge):
            self.bridge._error.emit(error)


class CodexControlsBridge(QObject):
    changed = Signal()
    preferencesChanged = Signal()
    _loaded = Signal(object)
    _error = Signal(str)

    def __init__(
        self, parent: QObject | None = None, *, service: CodexControlsService | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service or CodexControlsService(
            default_preferences_store(), codex_state_root() / "codex-control"
        )
        self._snapshot: CodexControlSnapshot | None = None
        self._prefs = CodexPreferences()
        self._busy = False
        self._message = "刷新以读取 Codex 模型和账号状态"
        self._loaded.connect(self._apply)
        self._error.connect(self._fail)

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        return self._snapshot is not None

    @Property("QVariantList", notify=changed)  # type: ignore[arg-type]
    def models(self) -> list[dict[str, object]]:
        if self._snapshot is None:
            return []
        return [{"value": item.model, "label": item.label} for item in self._snapshot.models]

    @Property(int, notify=changed)
    def modelIndex(self) -> int:
        if self._snapshot is None:
            return -1
        return next(
            (i for i, item in enumerate(self._snapshot.models) if item.model == self._prefs.model),
            -1,
        )

    @Property("QVariantList", notify=changed)  # type: ignore[arg-type]
    def efforts(self) -> list[dict[str, str]]:
        if self._snapshot is None:
            return []
        choice = next(
            (item for item in self._snapshot.models if item.model == self._prefs.model), None
        )
        labels = {
            "none": "无",
            "minimal": "极低",
            "low": "低",
            "medium": "中",
            "high": "高",
            "xhigh": "更高",
            "max": "最高",
            "ultra": "极深",
        }
        return (
            [{"value": value, "label": labels.get(value, value)} for value in choice.efforts]
            if choice
            else []
        )

    @Property(int, notify=changed)
    def effortIndex(self) -> int:
        if self._snapshot:
            choice = next(
                (item for item in self._snapshot.models if item.model == self._prefs.model), None
            )
            if choice and self._prefs.effort in choice.efforts:
                return choice.efforts.index(str(self._prefs.effort))
        return -1

    @Property(bool, notify=changed)
    def webSearch(self) -> bool:
        return self._prefs.web_search

    @Property(str, notify=changed)
    def accountText(self) -> str:
        return self._snapshot.account_label if self._snapshot else "账号状态待刷新"

    @Property(str, notify=changed)
    def quotaText(self) -> str:
        return self._snapshot.quota_label if self._snapshot else ""

    @Property(str, notify=changed)
    def contextText(self) -> str:
        budget = self._snapshot.context_budget if self._snapshot else None
        return f"上下文设置 {budget:,} tokens" if budget else ""

    @Property(str, notify=changed)
    def statusText(self) -> str:
        return self._message

    @Slot()
    def refresh(self) -> None:
        if not self._busy:
            self._busy = True
            self._message = "正在读取 Codex 模型目录"
            self.changed.emit()
            QThreadPool.globalInstance().start(_Refresh(self))

    @Slot(str)
    def selectModel(self, model: str) -> None:
        if self._snapshot is None:
            return
        choice = next((item for item in self._snapshot.models if item.model == model), None)
        if choice:
            effort = (
                self._prefs.effort
                if self._prefs.effort in choice.efforts
                else choice.default_effort
            )
            self._save(model, str(effort), self._prefs.web_search)

    @Slot(str)
    def selectEffort(self, effort: str) -> None:
        if self._prefs.model:
            self._save(self._prefs.model, effort, self._prefs.web_search)

    @Slot(bool)
    def setWebSearch(self, enabled: bool) -> None:
        if self._prefs.model and self._prefs.effort:
            self._save(self._prefs.model, self._prefs.effort, enabled)

    def _save(self, model: str, effort: str, web: bool) -> None:
        try:
            self._prefs = self.service.choose(model, effort, web)
            self._message = "已保存，下一次请求使用当前选择"
            self.preferencesChanged.emit()
        except Exception:
            self._message = "Codex 设置未保存，请刷新目录后重试"
        self.changed.emit()

    @Slot(object)
    def _apply(self, snapshot: CodexControlSnapshot) -> None:
        self._snapshot = snapshot
        self._prefs = snapshot.preferences
        self._busy = False
        self._message = "Codex 目录已更新"
        self.changed.emit()

    @Slot(str)
    def _fail(self, message: str) -> None:
        self._busy = False
        self._message = message
        self.changed.emit()
