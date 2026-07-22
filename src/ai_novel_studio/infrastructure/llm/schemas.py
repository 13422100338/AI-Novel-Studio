from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskPurpose(StrEnum):
    PLOT_DISCUSSION = "plot_discussion"
    AGENT_ASSISTANT = "agent_assistant"
    CHAPTER_REQUIREMENT = "chapter_requirement"
    BRIEF_NORMALIZATION = "brief_normalization"
    PROSE_GENERATION = "prose_generation"
    STYLE_AUDIT = "style_audit"
    MEMORY_EXTRACTION = "memory_extraction"
    MEMORY_EMBEDDING = "memory_embedding"
    LOCAL_REPAIR = "local_repair"


class StreamEventKind(StrEnum):
    TEXT = "text"
    REASONING = "reasoning"
    USAGE = "usage"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"


@dataclass(frozen=True, slots=True)
class ModelRoute:
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip():
            raise ValueError("模型路由必须包含连接 ID 和模型 ID")


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    context_window: int | None = None
    max_output_tokens: int | None = None
    streaming: bool | None = None
    reasoning: bool | None = None
    tools: bool | None = None
    strict_json: bool | None = None
    prompt_cache: bool | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None

    def __post_init__(self) -> None:
        for token_limit in (self.context_window, self.max_output_tokens):
            if token_limit is not None and token_limit <= 0:
                raise ValueError("模型 Token 能力必须大于零")
        for price in (self.input_price_per_million, self.output_price_per_million):
            if price is not None and price < 0:
                raise ValueError("模型价格不能为负数")


@dataclass(frozen=True, slots=True)
class ModelSamplingParameters:
    temperature: float | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None

    def __post_init__(self) -> None:
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        if self.top_p is not None and not 0 <= self.top_p <= 1:
            raise ValueError("top_p 必须在 0 到 1 之间")
        for name, value in (
            ("frequency_penalty", self.frequency_penalty),
            ("presence_penalty", self.presence_penalty),
        ):
            if value is not None and not -2 <= value <= 2:
                raise ValueError(f"{name} 必须在 -2 到 2 之间")


@dataclass(frozen=True, slots=True)
class ModelProfile:
    provider_id: str
    model_id: str
    display_name: str = ""
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    sampling: ModelSamplingParameters = field(default_factory=ModelSamplingParameters)

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip():
            raise ValueError("模型配置必须包含连接 ID 和模型 ID")
        context = self.capabilities.context_window
        output = self.capabilities.max_output_tokens
        if context is not None and output is not None and output > context:
            raise ValueError("模型输出上限不能大于上下文窗口")


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"不支持的消息角色：{self.role}")
        if not self.content.strip():
            raise ValueError("模型消息不能为空")


@dataclass(frozen=True, slots=True)
class LLMRequest:
    model_id: str
    messages: tuple[LLMMessage, ...]
    output_token_limit: int
    temperature: float = 0.7
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stream: bool = False
    json_mode: bool = False

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("模型 ID 不能为空")
        if not self.messages:
            raise ValueError("模型请求至少需要一条消息")
        if not 1 <= self.output_token_limit <= 200_000:
            raise ValueError("输出 Token 上限必须在 1 到 200000 之间")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        ModelSamplingParameters(
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            presence_penalty=self.presence_penalty,
        )


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    model_id: str
    texts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("Embedding 模型 ID 不能为空")
        if not isinstance(self.texts, tuple) or not self.texts:
            raise ValueError("Embedding input 不能为空")
        if any(not isinstance(text, str) for text in self.texts):
            raise ValueError("Embedding input 必须全部是文本")
        if any(not text.strip() for text in self.texts):
            raise ValueError("Embedding input 不能包含空白文本")


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    estimated: bool = False

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.reasoning_tokens,
        )
        if any(value is not None and value < 0 for value in values):
            raise ValueError("Token 用量不能为负数")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model_id: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    reasoning: str = ""
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    kind: StreamEventKind
    text: str = ""
    usage: LLMUsage | None = None
    error: str = ""
