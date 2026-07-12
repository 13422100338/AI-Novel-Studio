import pytest

from ai_novel_studio.infrastructure.llm import (
    LLMMessage,
    LLMRequest,
    MissingModelRouteError,
    ModelCapabilities,
    ModelProfile,
    ModelRoute,
    ProviderProfile,
    TaskPurpose,
    TaskRoutes,
)


def test_provider_profile_normalizes_base_url_without_storing_a_secret() -> None:
    profile = ProviderProfile(
        id="provider-local",
        name="第三方中转",
        base_url="https://relay.example/v1///",
        credential_id="credential-provider-local",
    )

    assert profile.base_url == "https://relay.example/v1"
    assert "api_key" not in profile.__dataclass_fields__
    assert "secret" not in repr(profile).casefold()


def test_model_profile_rejects_output_limit_larger_than_context() -> None:
    with pytest.raises(ValueError, match="输出上限"):
        ModelProfile(
            provider_id="provider-local",
            model_id="writer-model",
            capabilities=ModelCapabilities(context_window=8_000, max_output_tokens=9_000),
        )


def test_advanced_route_precedes_default_dual_model_route() -> None:
    plot = ModelRoute("provider-a", "plot-model")
    prose = ModelRoute("provider-b", "prose-model")
    audit = ModelRoute("provider-c", "audit-model")
    routes = TaskRoutes(
        plot=plot,
        prose=prose,
        overrides=((TaskPurpose.STYLE_AUDIT, audit),),
    )

    assert routes.resolve(TaskPurpose.PLOT_DISCUSSION) == plot
    assert routes.resolve(TaskPurpose.AGENT_ASSISTANT) == plot
    assert routes.resolve(TaskPurpose.CHAPTER_REQUIREMENT) == plot
    assert routes.resolve(TaskPurpose.BRIEF_NORMALIZATION) == plot
    assert routes.resolve(TaskPurpose.PROSE_GENERATION) == prose
    assert routes.resolve(TaskPurpose.LOCAL_REPAIR) == prose
    assert routes.resolve(TaskPurpose.STYLE_AUDIT) == audit


def test_missing_default_route_is_reported_instead_of_guessed() -> None:
    routes = TaskRoutes(plot=None, prose=None)

    with pytest.raises(MissingModelRouteError, match="剧情商讨"):
        routes.resolve(TaskPurpose.CHAPTER_REQUIREMENT)

    with pytest.raises(MissingModelRouteError, match="正文创作"):
        routes.resolve(TaskPurpose.STYLE_AUDIT)


@pytest.mark.parametrize("limit", [0, 200_001])
def test_request_rejects_output_limit_outside_supported_user_range(limit: int) -> None:
    with pytest.raises(ValueError, match="Token"):
        LLMRequest(
            model_id="writer-model",
            messages=(LLMMessage("user", "写作请求"),),
            output_token_limit=limit,
        )


def test_request_accepts_user_selected_200000_token_limit() -> None:
    request = LLMRequest(
        model_id="writer-model",
        messages=(LLMMessage("user", "写作请求"),),
        output_token_limit=200_000,
    )

    assert request.output_token_limit == 200_000
