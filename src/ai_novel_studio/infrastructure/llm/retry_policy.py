from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = 0.25

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("重试总尝试次数必须在 1 到 5 之间")
        if self.base_delay_seconds < 0:
            raise ValueError("重试等待时间不能为负数")

    def delay_before(self, attempt_number: int) -> float:
        if attempt_number < 2:
            return 0
        return float(self.base_delay_seconds * (2 ** (attempt_number - 2)))
