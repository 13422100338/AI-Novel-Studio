from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ai_novel_studio.infrastructure.llm.schemas import ModelRoute, TaskPurpose


class MissingModelRouteError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    id: str
    name: str
    base_url: str
    credential_id: str
    interface_type: str = "openai_compatible"
    timeout_seconds: int = 90
    models_url: str | None = None

    def __post_init__(self) -> None:
        normalized = self.base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
        if not self.id.strip() or not self.name.strip() or not self.credential_id.strip():
            raise ValueError("连接名称、ID 和凭据 ID 不能为空")
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("连接超时必须在 1 到 600 秒之间")
        object.__setattr__(self, "base_url", normalized)
        if self.models_url is not None:
            object.__setattr__(self, "models_url", self.models_url.strip().rstrip("/"))


_PLOT_PURPOSES = {
    TaskPurpose.PLOT_DISCUSSION,
    TaskPurpose.AGENT_ASSISTANT,
    TaskPurpose.CHAPTER_REQUIREMENT,
    TaskPurpose.BRIEF_NORMALIZATION,
    TaskPurpose.MEMORY_EXTRACTION,
}


@dataclass(frozen=True, slots=True)
class TaskRoutes:
    plot: ModelRoute | None
    prose: ModelRoute | None
    overrides: tuple[tuple[TaskPurpose, ModelRoute], ...] = ()

    def __post_init__(self) -> None:
        purposes = [purpose for purpose, _ in self.overrides]
        if len(purposes) != len(set(purposes)):
            raise ValueError("同一任务不能配置多个模型覆盖")

    def resolve(self, purpose: TaskPurpose) -> ModelRoute:
        for configured_purpose, route in self.overrides:
            if configured_purpose == purpose:
                return route
        if purpose == TaskPurpose.MEMORY_EMBEDDING:
            raise MissingModelRouteError("尚未配置 Embedding 模型")
        if purpose in _PLOT_PURPOSES:
            if self.plot is None:
                raise MissingModelRouteError("尚未配置剧情商讨模型")
            return self.plot
        if self.prose is None:
            raise MissingModelRouteError("尚未配置正文创作模型")
        return self.prose
