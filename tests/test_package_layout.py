from importlib import import_module


def test_planned_package_boundaries_are_importable() -> None:
    modules = (
        "ai_novel_studio.application",
        "ai_novel_studio.domain",
        "ai_novel_studio.pipelines",
        "ai_novel_studio.core.context",
        "ai_novel_studio.core.memory",
        "ai_novel_studio.infrastructure.llm",
        "ai_novel_studio.infrastructure.storage",
        "ai_novel_studio.ui",
    )

    for module in modules:
        assert import_module(module) is not None
