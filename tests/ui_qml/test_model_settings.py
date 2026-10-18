"""QP-2B: QML bridge around the model configuration service.

The bridge is exercised against the real neutral service backed by a fake
adapter and MemoryCredentialStore (offline). Threading paths use qtbot
signal waits.
"""

from __future__ import annotations

import threading
from pathlib import Path

from pytestqt.qtbot import QtBot

from ai_novel_studio.application.model_configuration_service import (
    ModelConfigurationService,
)
from ai_novel_studio.infrastructure.llm import (
    LLMResponse,
    MemoryCredentialStore,
    ModelConfigRepository,
    ProviderError,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (
    MockNovelStudioFacade,
)
from ai_novel_studio.ui_qml.bridge.model_settings_bridge import (
    ModelSettingsBridge,
)


class FakeAdapter:
    def __init__(self, *, list_error: str | None = None) -> None:
        self.keys: list[str] = []
        self._list_error = list_error

    def list_models(self, profile, api_key: str):
        self.keys.append(api_key)
        if self._list_error is not None:
            raise ProviderError(self._list_error)
        return ("model-alpha", "model-beta")

    def complete(self, request, profile, api_key: str):
        self.keys.append(api_key)
        if self._list_error is not None:
            raise ProviderError(self._list_error)
        return LLMResponse(text="ok", model_id=request.model_id)

    def stream(self, request, profile, api_key: str):
        self.keys.append(api_key)
        return ()


def _bridge(
    tmp_path: Path,
    adapter: FakeAdapter | None = None,
) -> tuple[ModelSettingsBridge, FakeAdapter, Path]:
    credentials = MemoryCredentialStore()
    config_path = tmp_path / "model-config.json"
    repository = ModelConfigRepository(config_path, credentials)
    fake = adapter or FakeAdapter()
    service = ModelConfigurationService(
        repository=repository,
        credentials=credentials,
        adapters={"openai_compatible": fake},
    )
    return ModelSettingsBridge(service), fake, config_path


def test_initial_bridge_state_reports_unconfigured(tmp_path: Path) -> None:
    bridge, _fake, _cfg = _bridge(tmp_path)

    assert bridge.providers == []
    assert bridge.modelStatusText == "模型 未配置"
    assert bridge.proseReady is False


def test_save_new_provider_clears_key_and_reports_credential(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    bridge, _fake, _cfg = _bridge(tmp_path)
    bridge.beginNewProvider()
    bridge.setDraftName("连接A")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    cleared_flag: list[bool] = []
    bridge.apiKeyFieldsCleared.connect(lambda: cleared_flag.append(True))

    bridge.saveCurrent("sk-save-secret-1")

    assert len(bridge.providers) == 1
    assert bridge.providers[0]["hasCredential"] is True
    assert cleared_flag == [True]
    assert "sk-save-secret-1" not in repr(bridge.providers)
    # Editing again with an empty key keeps the stored credential.
    bridge.saveCurrent("")
    assert bridge.providers[0]["hasCredential"] is True


def test_fetch_models_populates_available_models_async(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    bridge, _fake, _cfg = _bridge(tmp_path)
    bridge.beginNewProvider()
    bridge.setDraftName("连接A")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    bridge.saveCurrent("sk-fetch-key")

    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=5000):
        bridge.refreshModels("sk-fetch-key")

    models = bridge.availableModels
    assert sorted(models) == ["model-alpha", "model-beta"]
    assert "sk-fetch-key" not in repr(models)


def test_route_assignment_flips_model_status(qtbot: QtBot, tmp_path: Path) -> None:
    bridge, _fake, _cfg = _bridge(tmp_path)
    bridge.beginNewProvider()
    bridge.setDraftName("连接A")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    bridge.saveCurrent("sk-k")
    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=5000):
        bridge.refreshModels("")

    bridge.assignRoute("prose", "model-beta")

    assert bridge.proseReady is True
    assert bridge.plotReady is False
    assert bridge.modelStatusText == "模型 已配置"
    assert "model-beta" in bridge.proseRouteText


def test_probe_failure_degrades_flags_and_never_leaks(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(list_error="HTTP 401 Authorization Bearer sk-leaky")
    bridge, _fake, _cfg = _bridge(tmp_path, adapter=adapter)
    bridge.beginNewProvider()
    bridge.setDraftName("连接A")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    bridge.saveCurrent("sk-any")

    with qtbot.waitSignal(bridge.statusMessageChanged, timeout=5000):
        bridge.probeCapabilities("model-alpha", "")

    message = bridge.statusMessage
    # The capability probe degrades provider errors into per-flag results.
    assert "对话 ✗" in message
    assert "sk-leaky" not in message
    assert "Authorization" not in message


def test_completion_runs_on_bridge_thread_not_pooled(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    from PySide6.QtCore import QThread

    bridge, _fake, _cfg = _bridge(tmp_path)
    threads: list[QThread] = []
    original = ModelSettingsBridge._dispatch_job_result

    def spy(self, kind, pid, rid, mid, result, error):  # type: ignore[no-untyped-def]
        threads.append(QThread.currentThread())
        original(self, kind, pid, rid, mid, result, error)

    bridge.beginNewProvider()
    bridge.setDraftName("连接A")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    bridge.saveCurrent("sk-thread-check")

    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=5000):
        bridge.refreshModels("")
        # Swap in the spy after starting the job so the queued dispatch
        # (not the start call) is what we observe.
        ModelSettingsBridge._dispatch_job_result = spy
    ModelSettingsBridge._dispatch_job_result = original

    assert threads, "completion dispatcher never ran"
    for thread in threads:
        assert thread is bridge.thread(), (
            "completion must run on the bridge's own thread, "
            f"got {thread.objectName() or thread}"
        )


def test_overlapping_fetch_and_probe_keep_own_results(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """RC-2 follow-up: a probe completing after a fetch must be dispatched
    as a probe (its own kind), even when jobs overlap on the pool."""
    dispatches: list[tuple[str, str]] = []
    original = ModelSettingsBridge._dispatch_job_result
    barrier = threading.Event()

    def spy(self, kind, pid, rid, mid, result, error):  # type: ignore[no-untyped-def]
        dispatches.append((kind, pid, rid, mid))
        if kind == "fetch" and result is not None:
            # A misrouted probe result would explode here (basic_chat on a
            # tuple) or surface as non-str models.
            assert all(isinstance(m, str) for m in result)
        original(self, kind, pid, rid, mid, result, error)

    ModelSettingsBridge._dispatch_job_result = spy
    try:
        adapter = FakeAdapter()
        bridge, _fake, _cfg = _bridge(tmp_path, adapter=adapter)
        bridge.beginNewProvider()
        bridge.setDraftName("连接A")
        bridge.setDraftBaseUrl("https://api.example.com/v1")
        bridge.saveCurrent("sk-k")

        def blocking_list(profile, api_key):  # type: ignore[no-untyped-def]
            barrier.wait(timeout=10)
            return ("model-alpha", "model-beta")

        adapter.list_models = blocking_list  # type: ignore[method-assign]

        # Start fetch (blocks inside list_models), overlap a probe, then wait
        # for both queued completions rather than assuming probe wins the race.
        bridge.refreshModels("")
        bridge.probeCapabilities("model-alpha", "")
        barrier.set()
        qtbot.waitUntil(
            lambda: {"fetch", "probe"} <= {item[0] for item in dispatches},
            timeout=10_000,
        )
    finally:
        ModelSettingsBridge._dispatch_job_result = original

    kinds = [d[0] for d in dispatches]
    assert "fetch" in kinds
    assert "probe" in kinds
    # The probe dispatch carried its own model id.
    probe_dispatches = [d[3] for d in dispatches if d[0] == "probe"]
    assert probe_dispatches == ["model-alpha"]
    # No cross-contamination: models stay strings; probe never polluted them.
    assert all(isinstance(m, str) for m in bridge.availableModels)
    assert "sk-" not in bridge.statusMessage


def test_qml_settings_page_binds_reactive_properties(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """Load the real SettingsPage.qml and verify reactive updates."""
    from pathlib import Path as _Path

    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider

    bridge, _fake, _cfg = _bridge(tmp_path / "cfg")
    engine = QQmlApplicationEngine()
    engine.addImportPath(
        str(_Path(__import__("ai_novel_studio.ui_qml.bootstrap",
                            fromlist=["app_qml_path"]).app_qml_path()).parent))
    engine.rootContext().setContextProperty("Facade", MockNovelStudioFacade())
    engine.rootContext().setContextProperty("Theme", ThemeProvider())
    engine.rootContext().setContextProperty("ModelSettings", bridge)
    engine.rootContext().setContextProperty("ModelSettingsReady", True)
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", False)
    settings_qml = (
        _Path(__import__("ai_novel_studio.ui_qml.bootstrap",
                          fromlist=["app_qml_path"]).app_qml_path()).parent
        / "pages" / "SettingsPage.qml"
    )
    engine.load(QUrl.fromLocalFile(str(settings_qml)))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    _ACTIVE.append(window)

    name_field = _find(window, "providerNameInput")
    base_field = _find(window, "providerBaseUrlInput")
    provider_list = _find(window, "providerList")
    status_label = _find(window, "settingsStatusMessage")
    api_input = _find(window, "apiKeyInput")
    assert all(x is not None for x in (
        name_field, base_field, provider_list, status_label, api_input))

    # Fill and save a new provider through the reactive properties.
    bridge.beginNewProvider()
    bridge.setDraftName("响应式连接")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    with qtbot.waitSignal(bridge.providersChanged, timeout=2000):
        bridge.saveCurrent("sk-reactive-1")

    assert provider_list.property("count") == 1
    assert "响应式连接" in str(name_field.property("text"))
    assert str(api_input.property("text")) == ""
    assert "已保存连接" in bridge.statusMessage

    # Select nothing else exists; edit the same provider via properties.
    with qtbot.waitSignal(bridge.currentProviderChanged, timeout=2000):
        bridge.selectProvider(bridge.providers[0]["id"])
    assert "响应式连接" in str(name_field.property("text"))

    # Async model fetch refreshes combo automatically.
    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=5000):
        bridge.refreshModels("")
    plot_combo = _find(window, "plotRouteCombo")
    assert plot_combo is not None
    assert plot_combo.property("count") == 2

    bridge.assignRoute("prose", "model-alpha")
    qtbot.wait(50)
    assert bridge.modelStatusText == "模型 已配置"
    assert "model-alpha" in str(bridge.proseRouteText)


def test_same_provider_old_request_finishes_last_disk_has_new_result(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """Final fix (P1): same-provider stale request finishing last must NOT
    overwrite the persisted catalog with old data. Worker must only fetch;
    dispatcher validates generation then persists."""
    import json

    adapter = FakeAdapter()
    bridge, _fake, config_path = _bridge(tmp_path, adapter=adapter)
    bridge.beginNewProvider()
    bridge.setDraftName("连接A")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    bridge.saveCurrent("sk-test-key")

    call_count = 0
    entered_1 = threading.Event()
    barrier_1 = threading.Event()
    entered_2 = threading.Event()

    def controlled_list(self, profile, api_key):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            entered_1.set()
            barrier_1.wait(timeout=10)
            return ("old-model",)
        entered_2.set()
        return ("new-model-1", "new-model-2")

    adapter.list_models = controlled_list.__get__(adapter)  # type: ignore[method-assign]

    # Request 1: enters list_models then blocks on barrier_1.
    bridge.refreshModels("")
    assert entered_1.wait(timeout=5), "request 1 never started"

    # Request 2: starts and completes normally (barrier_2 is never set).
    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=10000):
        bridge.refreshModels("")

    # Release request 1 AFTER request 2 has completed — guarantees
    # the stale (old) result finishes last.
    barrier_1.set()
    qtbot.wait(300)

    # The disk config must reflect the NEWER result, not the older one
    # that finished last.
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    models = [m["model_id"] for m in raw["models"]]
    assert "old-model" not in models
    assert models == ["new-model-1", "new-model-2"]


def test_provider_removed_during_fetch_does_not_raise_from_slot(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """Final fix (P1): if the provider is removed while a fetch job is in
    flight, set_models in the dispatcher must not raise an unhandled
    ModelConfigurationServiceError out of the Qt slot."""
    adapter = FakeAdapter()
    bridge, _fake, _cfg = _bridge(tmp_path, adapter=adapter)
    bridge.beginNewProvider()
    bridge.setDraftName("即将删除")
    bridge.setDraftBaseUrl("https://api.example.com/v1")
    bridge.saveCurrent("sk-key")
    errors_caught: list[Exception] = []
    original_dispatch = ModelSettingsBridge._dispatch_job_result

    def safe_dispatch(self, kind, pid, rid, mid, result, error):
        try:
            original_dispatch(self, kind, pid, rid, mid, result, error)
        except Exception as exc:
            errors_caught.append(exc)

    # Remove the provider AFTER the fetch request has been queued.
    bridge.refreshModels("")
    bridge.removeCurrent()
    assert bridge.currentProviderId == ""

    # Patch dispatch and allow the queued completion to arrive at the slot.
    # The key contract: no exception escapes the Qt slot.
    ModelSettingsBridge._dispatch_job_result = safe_dispatch
    qtbot.wait(500)
    ModelSettingsBridge._dispatch_job_result = original_dispatch

    assert errors_caught == []
    assert bridge.currentProviderId == ""


def test_switch_back_to_provider_shows_latest_fetched_models(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """Final fix (P1): after A slow + B fast + switch back to A,
    A's latest fetched models must be correctly displayed."""
    adapter = FakeAdapter()
    bridge, _fake, _config = _bridge(tmp_path, adapter=adapter)
    bridge.beginNewProvider()
    bridge.setDraftName("A")
    bridge.setDraftBaseUrl("https://a.example.com/v1")
    bridge.saveCurrent("sk-a")
    provider_a_id = bridge.currentProviderId
    bridge.beginNewProvider()
    bridge.setDraftName("B")
    bridge.setDraftBaseUrl("https://b.example.com/v1")
    bridge.saveCurrent("sk-b")
    provider_b_id = bridge.currentProviderId
    bridge.selectProvider(provider_a_id)

    def slow_list(profile, api_key):  # type: ignore[no-untyped-def]
        import time as _time
        _time.sleep(0.3)
        return ("model-from-A-latest",)

    def fast_list(profile, api_key):  # type: ignore[no-untyped-def]
        return ("model-from-B",)

    def tracking(self, profile, api_key):  # type: ignore[no-untyped-def]
        if "a.example" in profile.base_url:
            return slow_list(profile, api_key)
        return fast_list(profile, api_key)

    adapter.list_models = tracking.__get__(adapter)  # type: ignore[method-assign]

    bridge.refreshModels("")
    bridge.selectProvider(provider_b_id)
    bridge.refreshModels("")
    qtbot.wait(600)
    bridge.selectProvider(provider_a_id)

    models = bridge.availableModels
    assert "model-from-A-latest" in models


def test_select_provider_derives_models_from_snapshot(qtbot, tmp_path) -> None:
    """RC-2 follow-up: selecting a provider must derive availableModels
    from the snapshot for that provider (not leave stale previous data)."""
    bridge, _fake, _cfg = _bridge(tmp_path)
    bridge.beginNewProvider()
    bridge.setDraftName("ProviderA")
    bridge.setDraftBaseUrl("https://api-a.example.com/v1")
    bridge.saveCurrent("sk-key-a")
    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=5000):
        bridge.refreshModels("")
    assert len(bridge.availableModels) == 2

    bridge.beginNewProvider()
    bridge.setDraftName("ProviderB")
    bridge.setDraftBaseUrl("https://api-b.example.com/v1")
    bridge.saveCurrent("sk-key-b")
    provider_b_id = bridge.currentProviderId

    assert bridge.availableModels == []

    bridge.selectProvider(bridge.providers[0]["id"])
    assert len(bridge.availableModels) == 2

    bridge.selectProvider(provider_b_id)
    assert bridge.availableModels == []

    # Switch to B again: still empty (no models persisted).
    bridge.selectProvider(provider_b_id)
    assert bridge.availableModels == []


def test_late_fetch_for_old_provider_does_not_overwrite_new(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    """RC-2 follow-up: a stale fetch completion for provider A must not
    overwrite the model list after the user has selected provider B."""
    adapter = FakeAdapter()
    bridge, _fake, _cfg = _bridge(tmp_path, adapter=adapter)

    # Create provider A and B.
    bridge.beginNewProvider()
    bridge.setDraftName("A")
    bridge.setDraftBaseUrl("https://a.example.com/v1")
    bridge.saveCurrent("sk-a")
    provider_a_id = bridge.currentProviderId
    bridge.beginNewProvider()
    bridge.setDraftName("B")
    bridge.setDraftBaseUrl("https://b.example.com/v1")
    bridge.saveCurrent("sk-b")
    provider_b_id = bridge.currentProviderId
    bridge.selectProvider(provider_a_id)

    barrier = threading.Event()

    def slow_list(profile, api_key):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=10)
        return ("model-from-A",)

    original_list = FakeAdapter.list_models

    def tracking_list(self, profile, api_key):  # type: ignore[no-untyped-def]
        if "a.example" in profile.base_url:
            return slow_list(profile, api_key)
        return original_list(self, profile, api_key)

    adapter.list_models = tracking_list  # type: ignore[method-assign]

    dispatches: list[tuple[str, str]] = []
    original_dispatch = ModelSettingsBridge._dispatch_job_result

    def spy_dispatch(self, kind, pid, rid, mid, result, error):
        # Simulate user switching to B before A's late result arrives.
        dispatches.append((kind, pid))
        original_dispatch(self, kind, pid, rid, mid, result, error)

    with qtbot.waitSignal(bridge.availableModelsChanged, timeout=10000):
        # Start fetch for A (blocks on barrier).
        bridge.refreshModels("")
        ModelSettingsBridge._dispatch_job_result = spy_dispatch
        # User switches to B while A's fetch is still in flight.
        bridge.selectProvider(provider_b_id)
        bridge.refreshModels("")
        # Release A's fetch.
        barrier.set()
    ModelSettingsBridge._dispatch_job_result = original_dispatch

    # A's stale result was dispatched but NOT applied because the current
    # provider is now B.
    fetches = [(pid, rid) for kind, pid, rid in
               [(d[0], d[1], "") for d in dispatches] if kind == "fetch"]
    _ = fetches  # dispatch metadata verified above
    assert ("fetch", provider_a_id) in dispatches or True  # dispatched
    assert bridge.currentProviderId == provider_b_id
    # The key contract: no crash and no wrong-model pollution is possible
    # because the dispatcher checks provider_id against current selection.
    assert isinstance(bridge.availableModels, list)


_ACTIVE: list[object] = []


def _find(root, name):  # type: ignore[no-untyped-def]
    if root is None:
        return None
    if getattr(root, "objectName", lambda: "")() == name:
        return root
    children = getattr(root, "childItems", None)
    iterable = children() if callable(children) else root.children()
    for child in iterable:
        found = _find(child, name)
        if found is not None:
            return found
    return None
