from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Protocol


class TokenBudgetError(ValueError):
    """Raised when an input/output budget cannot fit the model context window."""


class ModelOutputLimitError(TokenBudgetError):
    """Raised when the user's requested output exceeds a known model limit."""


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


class ConservativeTokenEstimator:
    """Deterministic provider-neutral estimate based on UTF-8 byte length."""

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, ceil(len(text.encode("utf-8")) / 4))


@dataclass(frozen=True, slots=True)
class TokenBudget:
    context_window: int
    output_limit: int
    safety_margin: int

    def __post_init__(self) -> None:
        if self.context_window <= 0:
            raise TokenBudgetError("上下文窗口必须大于 0")
        if self.output_limit <= 0:
            raise TokenBudgetError("输出 Token 上限必须大于 0")
        if self.safety_margin < 0:
            raise TokenBudgetError("安全余量不能小于 0")
        if self.output_limit + self.safety_margin >= self.context_window:
            raise TokenBudgetError(
                "上下文窗口无法容纳用户设置的输出上限和安全余量："
                f"{self.context_window} < {self.output_limit} + {self.safety_margin}"
            )

    @property
    def input_limit(self) -> int:
        return self.context_window - self.output_limit - self.safety_margin

    def validate_model_output_limit(self, model_output_limit: int | None) -> None:
        if model_output_limit is None:
            return
        if model_output_limit <= 0:
            raise ModelOutputLimitError("模型输出上限必须大于 0")
        if self.output_limit > model_output_limit:
            raise ModelOutputLimitError(
                f"用户设置的输出上限 {self.output_limit} 超过模型上限 {model_output_limit}；"
                "程序不会静默缩减该设置"
            )
