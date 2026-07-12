from ai_novel_studio.infrastructure.llm import (
    LLMUsage,
    ModelCapabilities,
    ModelProfile,
    ModelRoute,
    TaskPurpose,
    UsageTracker,
)


def test_usage_tracker_aggregates_tokens_cache_retries_and_cost() -> None:
    tracker = UsageTracker()
    model = ModelProfile(
        provider_id="relay",
        model_id="novel-pro",
        capabilities=ModelCapabilities(
            input_price_per_million=2.0,
            output_price_per_million=8.0,
        ),
    )
    tracker.record_success(
        TaskPurpose.PLOT_DISCUSSION,
        ModelRoute("relay", "novel-pro"),
        model,
        LLMUsage(1_000_000, 500_000, cached_input_tokens=250_000),
        output_token_limit=600_000,
        duration_ms=25,
        retry_count=1,
    )

    snapshot = tracker.snapshot()
    assert snapshot.call_count == 1
    assert snapshot.input_tokens == 1_000_000
    assert snapshot.output_tokens == 500_000
    assert snapshot.cached_input_tokens == 250_000
    assert snapshot.cache_known is True
    assert snapshot.retry_count == 1
    assert snapshot.cost == 6.0


def test_usage_tracker_marks_absent_provider_usage_as_estimated_and_cache_unknown() -> None:
    tracker = UsageTracker()
    model = ModelProfile(provider_id="relay", model_id="novel-pro")
    tracker.record_success(
        TaskPurpose.STYLE_AUDIT,
        ModelRoute("relay", "novel-pro"),
        model,
        LLMUsage(input_tokens=120, output_tokens=30, estimated=True),
        output_token_limit=100,
        duration_ms=4,
        retry_count=0,
    )

    snapshot = tracker.snapshot()
    assert snapshot.estimated_call_count == 1
    assert snapshot.cached_input_tokens == 0
    assert snapshot.cache_known is False
    assert snapshot.cost is None

