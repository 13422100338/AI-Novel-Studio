import pytest

from ai_novel_studio.core.context.token_budget import (
    ModelOutputLimitError,
    TokenBudget,
    TokenBudgetError,
)


def test_input_budget_matches_context_minus_output_and_safety_margin() -> None:
    budget = TokenBudget(context_window=128_000, output_limit=16_000, safety_margin=4_000)

    assert budget.input_limit == 108_000


def test_impossible_output_budget_is_rejected_without_silent_clamping() -> None:
    with pytest.raises(TokenBudgetError, match="上下文窗口"):
        TokenBudget(context_window=8_000, output_limit=7_000, safety_margin=2_000)

    budget = TokenBudget(context_window=128_000, output_limit=20_000, safety_margin=4_000)
    with pytest.raises(ModelOutputLimitError, match="12000"):
        budget.validate_model_output_limit(12_000)
    assert budget.output_limit == 20_000
