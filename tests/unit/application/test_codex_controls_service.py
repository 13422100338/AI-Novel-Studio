import json

import pytest

from ai_novel_studio.application.codex_controls_service import CodexControlsService
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferencesStore


class CatalogClient:
    def request(self, method, params):
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "config/read":
            return {
                "config": {
                    "model": "model-b",
                    "model_reasoning_effort": "deep",
                    "model_context_window": 1000000,
                }
            }
        if method == "account/rateLimits/read":
            return {"rateLimits": {"primary": {"usedPercent": 23}}}
        return {
            "data": [
                {
                    "model": "model-a",
                    "displayName": "A",
                    "defaultReasoningEffort": "light",
                    "supportedReasoningEfforts": [{"reasoningEffort": "light"}],
                    "isDefault": True,
                },
                {
                    "model": "model-b",
                    "displayName": "B",
                    "defaultReasoningEffort": "deep",
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "deep"},
                        {"reasoningEffort": "custom-effort"},
                    ],
                },
            ]
        }

    def close(self):
        pass


def test_catalog_uses_configured_model_and_dynamic_effort_and_persists(tmp_path):
    store = CodexPreferencesStore(tmp_path / "choices.json")
    service = CodexControlsService(store, tmp_path / "control", lambda _root: CatalogClient())
    result = service.refresh()
    assert result.preferences.model == "model-b"
    assert result.preferences.effort == "deep"
    assert result.quota_label == "短时剩余 77%"
    assert result.context_budget == 1000000
    service.choose("model-b", "custom-effort", True)
    assert store.load().effort == "custom-effort"
    assert store.load().web_search is True
    with pytest.raises(ValueError):
        service.choose("model-a", "custom-effort", False)


def test_corrupt_preferences_are_preserved(tmp_path):
    path = tmp_path / "choices.json"
    path.write_text(json.dumps({"version": True, "web_search": False}))
    with pytest.raises(ValueError):
        CodexPreferencesStore(path).load()
    assert json.loads(path.read_text())["version"] is True
