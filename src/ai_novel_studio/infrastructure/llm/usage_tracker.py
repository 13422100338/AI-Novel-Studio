from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.infrastructure.llm.schemas import (
    LLMUsage,
    ModelProfile,
    ModelRoute,
    TaskPurpose,
)


@dataclass(frozen=True, slots=True)
class UsageRecord:
    purpose: TaskPurpose
    route: ModelRoute
    usage: LLMUsage
    output_token_limit: int
    duration_ms: int
    retry_count: int
    status: str
    cost: float | None


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    call_count: int
    failed_call_count: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    retry_count: int
    estimated_call_count: int
    cache_known: bool
    cost: float | None


class UsageTracker:
    def __init__(self) -> None:
        self._records: list[UsageRecord] = []

    def record_success(
        self,
        purpose: TaskPurpose,
        route: ModelRoute,
        model: ModelProfile,
        usage: LLMUsage,
        *,
        output_token_limit: int,
        duration_ms: int,
        retry_count: int,
    ) -> None:
        self._records.append(
            UsageRecord(
                purpose=purpose,
                route=route,
                usage=usage,
                output_token_limit=output_token_limit,
                duration_ms=duration_ms,
                retry_count=retry_count,
                status="success",
                cost=self._cost(model, usage),
            )
        )

    def record_failure(
        self,
        purpose: TaskPurpose,
        route: ModelRoute,
        model: ModelProfile,
        *,
        output_token_limit: int,
        duration_ms: int,
        retry_count: int,
        partial_usage: LLMUsage | None = None,
    ) -> None:
        usage = partial_usage or LLMUsage(estimated=True)
        self._records.append(
            UsageRecord(
                purpose=purpose,
                route=route,
                usage=usage,
                output_token_limit=output_token_limit,
                duration_ms=duration_ms,
                retry_count=retry_count,
                status="failed",
                cost=self._cost(model, usage),
            )
        )

    def snapshot(self) -> UsageSnapshot:
        known_costs = [record.cost for record in self._records if record.cost is not None]
        all_costs_known = len(known_costs) == len(self._records)
        return UsageSnapshot(
            call_count=len(self._records),
            failed_call_count=sum(record.status == "failed" for record in self._records),
            input_tokens=sum(record.usage.input_tokens or 0 for record in self._records),
            output_tokens=sum(record.usage.output_tokens or 0 for record in self._records),
            cached_input_tokens=sum(
                record.usage.cached_input_tokens or 0 for record in self._records
            ),
            reasoning_tokens=sum(
                record.usage.reasoning_tokens or 0 for record in self._records
            ),
            retry_count=sum(record.retry_count for record in self._records),
            estimated_call_count=sum(record.usage.estimated for record in self._records),
            cache_known=bool(self._records)
            and all(record.usage.cached_input_tokens is not None for record in self._records),
            cost=sum(known_costs) if all_costs_known else None,
        )

    @property
    def records(self) -> tuple[UsageRecord, ...]:
        return tuple(self._records)

    @staticmethod
    def _cost(model: ModelProfile, usage: LLMUsage) -> float | None:
        input_price = model.capabilities.input_price_per_million
        output_price = model.capabilities.output_price_per_million
        if (
            input_price is None
            or output_price is None
            or usage.input_tokens is None
            or usage.output_tokens is None
        ):
            return None
        return (
            usage.input_tokens * input_price + usage.output_tokens * output_price
        ) / 1_000_000

