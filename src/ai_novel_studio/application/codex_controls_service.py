from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_novel_studio.application.codex_session_service import CodexClient
from ai_novel_studio.infrastructure.codex.app_server import CodexAppServer, CodexConnectionError
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferences, CodexPreferencesStore


@dataclass(frozen=True)
class CodexModelChoice:
    model: str
    label: str
    efforts: tuple[str, ...]
    default_effort: str
    image_input: bool


@dataclass(frozen=True)
class CodexControlSnapshot:
    models: tuple[CodexModelChoice, ...]
    preferences: CodexPreferences
    account_label: str
    quota_label: str
    context_budget: int | None


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 256 or any(ord(c) < 32 for c in value):
        raise CodexConnectionError("Codex 模型目录信息无效")
    return value


class CodexControlsService:
    def __init__(
        self,
        store: CodexPreferencesStore,
        workspace: Path,
        client_factory: Callable[[Path], CodexClient] = CodexAppServer,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.factory = client_factory
        self.snapshot: CodexControlSnapshot | None = None

    def refresh(self) -> CodexControlSnapshot:
        self.workspace.mkdir(parents=True, exist_ok=True)
        client = self.factory(self.workspace)
        try:
            account = client.request("account/read", {}).get("account")
            account_label = (
                "ChatGPT 已登录"
                if isinstance(account, dict) and account.get("type") == "chatgpt"
                else "请先使用 ChatGPT 登录 Codex"
            )
            config = client.request("config/read", {}).get("config", {})
            models: list[CodexModelChoice] = []
            cursor: str | None = None
            defaults: list[str] = []
            for _page in range(5):
                params: dict[str, object] = {"limit": 100, "includeHidden": False}
                if cursor:
                    params["cursor"] = cursor
                result = client.request("model/list", params)
                data = result.get("data")
                if not isinstance(data, list):
                    raise CodexConnectionError("Codex 模型目录信息无效")
                for item in data:
                    if not isinstance(item, dict):
                        raise CodexConnectionError("Codex 模型目录信息无效")
                    raw_efforts = item.get("supportedReasoningEfforts", [])
                    if not isinstance(raw_efforts, list) or not raw_efforts:
                        continue
                    efforts = tuple(
                        _identifier(row.get("reasoningEffort"))
                        for row in raw_efforts
                        if isinstance(row, dict)
                    )
                    default = _identifier(item.get("defaultReasoningEffort"))
                    if default not in efforts:
                        raise CodexConnectionError("Codex 思考强度目录无效")
                    model = _identifier(item.get("model"))
                    models.append(
                        CodexModelChoice(
                            model,
                            _identifier(item.get("displayName")),
                            efforts,
                            default,
                            "image" in item.get("inputModalities", ["text", "image"]),
                        )
                    )
                    if item.get("isDefault"):
                        defaults.append(model)
                next_cursor = result.get("nextCursor")
                if not next_cursor:
                    break
                if not isinstance(next_cursor, str) or next_cursor == cursor:
                    raise CodexConnectionError("Codex 模型目录分页无效")
                cursor = next_cursor
            else:
                raise CodexConnectionError("Codex 模型目录过大")
            if not models:
                raise CodexConnectionError("Codex 没有返回可选模型")
            preferences = self.store.load()
            names = {item.model for item in models}
            selected = preferences.model or config.get("model")
            if selected not in names:
                selected = defaults[0] if defaults else models[0].model
            choice = next(item for item in models if item.model == selected)
            effort = preferences.effort or config.get("model_reasoning_effort")
            if effort not in choice.efforts:
                effort = choice.default_effort
            preferences = CodexPreferences(choice.model, str(effort), preferences.web_search)
            self.store.save(preferences)
            try:
                quota = self._quota(client.request("account/rateLimits/read", {}))
            except CodexConnectionError:
                quota = "用量信息暂不可用"
            budget = config.get("model_context_window")
            budget = budget if type(budget) is int and budget > 0 else None
            self.snapshot = CodexControlSnapshot(
                tuple(models), preferences, account_label, quota, budget
            )
            return self.snapshot
        finally:
            client.close()

    def choose(self, model: str, effort: str, web_search: bool) -> CodexPreferences:
        if self.snapshot is None:
            raise ValueError("请先刷新 Codex 模型目录")
        choice = next((item for item in self.snapshot.models if item.model == model), None)
        if choice is None or effort not in choice.efforts or type(web_search) is not bool:
            raise ValueError("请选择模型支持的思考强度")
        value = CodexPreferences(model, effort, web_search)
        self.store.save(value)
        return value

    @staticmethod
    def _quota(data: dict[str, Any]) -> str:
        bucket = data.get("rateLimits")
        if not isinstance(bucket, dict):
            return "用量信息暂不可用"
        windows: list[str] = []
        for key, label in (("primary", "短时"), ("secondary", "长时")):
            window = bucket.get(key)
            if isinstance(window, dict) and isinstance(window.get("usedPercent"), (int, float)):
                remaining = max(0, min(100, 100 - window["usedPercent"]))
                windows.append(f"{label}剩余 {remaining:.0f}%")
        return " · ".join(windows) or "用量信息暂不可用"
