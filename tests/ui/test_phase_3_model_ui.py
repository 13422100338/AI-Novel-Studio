from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot

from ai_novel_studio.infrastructure.llm import (
    CapabilityProbeResult,
    MemoryCredentialStore,
    ModelCapabilities,
    ModelConfigRepository,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ProviderProfile,
    TaskPurpose,
    TaskRoutes,
    UsageSnapshot,
)
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.settings_dialog import SettingsDialog
from ai_novel_studio.ui.qt.model_runtime import ModelRuntime


class FakeSettingsController(QObject):
    models_loaded = Signal(str, object)
    capabilities_loaded = Signal(str, str, object)
    saved = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.configuration = ModelConfiguration.empty()
        self.refresh_calls = []
        self.save_calls = []
        self.probe_calls = []

    def refresh_models(self, profile, api_key):  # type: ignore[no-untyped-def]
        self.refresh_calls.append((profile, api_key))

    def save(self, configuration, api_keys):  # type: ignore[no-untyped-def]
        self.configuration = configuration
        self.save_calls.append((configuration, api_keys))
        self.saved.emit(configuration)

    def probe_capabilities(self, profile, model_id, api_key):  # type: ignore[no-untyped-def]
        self.probe_calls.append((profile, model_id, api_key))

    def has_credential(self, credential_id: str) -> bool:
        return False


def _provider() -> ProviderProfile:
    return ProviderProfile(
        id="relay",
        name="第三方中转",
        base_url="https://relay.example/v1",
        credential_id="credential-relay",
    )


def test_settings_supports_editable_relay_profiles_hidden_key_and_model_refresh(
    qtbot: QtBot,
) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)

    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.api_key.setText("sk-private")
    dialog.refresh_models_button.click()

    assert dialog.base_url.isReadOnly() is False
    assert dialog.api_key.echoMode() == QLineEdit.EchoMode.Password
    assert controller.refresh_calls[0][0].base_url == "https://relay.example/v1"
    assert controller.refresh_calls[0][1] == "sk-private"


def test_settings_exposes_independent_plot_prose_and_advanced_routes(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)
    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.refresh_models_button.click()
    profile = controller.refresh_calls[-1][0]
    models = (
        ModelProfile(profile.id, "plot-model", "Plot"),
        ModelProfile(profile.id, "prose-model", "Prose"),
    )

    controller.models_loaded.emit("relay", models)

    assert dialog.plot_model_combo.count() == 3
    assert dialog.prose_model_combo.count() == 3
    assert dialog.brief_model_combo.count() == 3
    assert dialog.agent_model_combo.count() == 3
    assert dialog.audit_model_combo.count() == 3
    dialog.plot_model_combo.setCurrentIndex(1)
    dialog.prose_model_combo.setCurrentIndex(2)
    dialog.save_button.click()
    saved = controller.save_calls[0][0]
    assert saved.routes.plot == ModelRoute(profile.id, "plot-model")
    assert saved.routes.prose == ModelRoute(profile.id, "prose-model")


def test_settings_saves_agent_override_when_feature_is_enabled(
    qtbot: QtBot,
) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)
    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.refresh_models_button.click()
    profile = controller.refresh_calls[-1][0]
    controller.models_loaded.emit(
        profile.id,
        (
            ModelProfile(profile.id, "plot-model", "Plot"),
            ModelProfile(profile.id, "agent-model", "Agent"),
        ),
    )

    dialog.plot_model_combo.setCurrentIndex(1)
    dialog.prose_model_combo.setCurrentIndex(1)
    agent_index = next(
        index
        for index in range(dialog.agent_model_combo.count())
        if dialog.agent_model_combo.itemData(index) == ModelRoute(profile.id, "agent-model")
    )
    dialog.agent_model_combo.setCurrentIndex(agent_index)
    dialog.save_button.click()

    overrides = dict(controller.save_calls[0][0].routes.overrides)
    assert overrides[TaskPurpose.AGENT_ASSISTANT] == ModelRoute(
        profile.id, "agent-model"
    )


def test_settings_can_probe_selected_model_capabilities(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)
    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.api_key.setText("secret")
    dialog.refresh_models_button.click()
    profile = controller.refresh_calls[-1][0]
    controller.models_loaded.emit(
        profile.id, (ModelProfile(profile.id, "plot-model", "Plot"),)
    )

    dialog.probe_capabilities_button.click()

    assert controller.probe_calls[0][1] == "plot-model"
    controller.capabilities_loaded.emit(
        profile.id,
        "plot-model",
        CapabilityProbeResult(streaming=True, strict_json=True, tools=None),
    )
    assert "流式：支持" in dialog.capability_status.text()
    assert "工具：未知" in dialog.capability_status.text()


def test_advanced_sampling_menu_is_collapsed_and_saves_current_model(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)
    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.refresh_models_button.click()
    profile = controller.refresh_calls[-1][0]
    controller.models_loaded.emit(
        profile.id, (ModelProfile(profile.id, "novel-model", "Novel"),)
    )

    assert dialog.advanced_parameters_panel.isHidden()
    dialog.advanced_parameters_button.click()
    dialog.custom_sampling.setChecked(True)
    dialog.temperature.setValue(1.05)
    dialog.top_p.setValue(0.88)
    dialog.plot_model_combo.setCurrentIndex(1)
    dialog.prose_model_combo.setCurrentIndex(1)
    dialog.save_button.click()

    saved_model = controller.save_calls[0][0].models[0]
    assert saved_model.sampling.temperature == 1.05
    assert saved_model.sampling.top_p == 0.88


def test_advanced_model_options_save_manual_token_capabilities(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)
    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.refresh_models_button.click()
    profile = controller.refresh_calls[-1][0]
    controller.models_loaded.emit(
        profile.id, (ModelProfile(profile.id, "deepseek-v4-pro"),)
    )

    dialog.custom_token_capabilities.setChecked(True)
    dialog.context_window.setText("1000000")
    dialog.max_output_tokens.setText("64000")
    dialog.plot_model_combo.setCurrentIndex(1)
    dialog.prose_model_combo.setCurrentIndex(1)
    dialog.save_button.click()

    saved_model = controller.save_calls[0][0].models[0]
    assert saved_model.capabilities.context_window == 1_000_000
    assert saved_model.capabilities.max_output_tokens == 64_000


def test_token_capability_fields_accept_keyboard_editing(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)
    dialog.connection_name.setText("第三方中转")
    dialog.base_url.setText("https://relay.example/v1")
    dialog.refresh_models_button.click()
    profile = controller.refresh_calls[-1][0]
    controller.models_loaded.emit(
        profile.id, (ModelProfile(profile.id, "deepseek-v4-pro"),)
    )

    dialog.custom_token_capabilities.setChecked(True)
    dialog.context_window.setFocus()
    qtbot.keyClicks(dialog.context_window, "1000000")
    assert dialog.context_window.text() == "1000000"
    dialog.context_window.selectAll()
    qtbot.keyClick(dialog.context_window, Qt.Key.Key_Backspace)
    assert dialog.context_window.text() == ""


def test_refreshing_models_preserves_saved_token_capabilities(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    profile = _provider()
    model = ModelProfile(
        "relay",
        "deepseek-v4-pro",
        capabilities=ModelCapabilities(
            context_window=1_000_000,
            max_output_tokens=64_000,
        ),
    )
    route = ModelRoute("relay", "deepseek-v4-pro")
    controller.configuration = ModelConfiguration(
        providers=(profile,),
        models=(model,),
        routes=TaskRoutes(plot=route, prose=route),
    )
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)

    controller.models_loaded.emit(
        profile.id, (ModelProfile(profile.id, "deepseek-v4-pro"),)
    )
    dialog.save_button.click()

    saved_model = controller.save_calls[0][0].models[0]
    assert saved_model.capabilities.context_window == 1_000_000
    assert saved_model.capabilities.max_output_tokens == 64_000


def test_settings_restores_all_saved_task_routes(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    profile = _provider()
    model = ModelProfile("relay", "deepseek-v4-pro")
    route = ModelRoute("relay", "deepseek-v4-pro")
    controller.configuration = ModelConfiguration(
        providers=(profile,),
        models=(model,),
        routes=TaskRoutes(
            plot=route,
            prose=route,
            overrides=(
                (TaskPurpose.BRIEF_NORMALIZATION, route),
                (TaskPurpose.AGENT_ASSISTANT, route),
                (TaskPurpose.STYLE_AUDIT, route),
            ),
        ),
    )

    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)

    for combo in (
        dialog.plot_model_combo,
        dialog.prose_model_combo,
        dialog.brief_model_combo,
        dialog.agent_model_combo,
        dialog.audit_model_combo,
    ):
        assert combo.currentData() == route


def test_settings_preserves_optional_and_unrepresented_routes_across_restart(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    controller = FakeSettingsController()
    profile = _provider()
    model = ModelProfile("relay", "deepseek-v4-pro")
    route = ModelRoute("relay", "deepseek-v4-pro")
    controller.configuration = ModelConfiguration(
        providers=(profile,),
        models=(model,),
        routes=TaskRoutes(
            plot=route,
            prose=route,
            overrides=(
                (TaskPurpose.AGENT_ASSISTANT, route),
                (TaskPurpose.MEMORY_EXTRACTION, route),
                (TaskPurpose.LOCAL_REPAIR, route),
            ),
        ),
    )
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)

    assert not dialog.agent_model_combo.isHidden()
    assert dialog.agent_model_combo.currentData() == route
    dialog.save_button.click()

    saved = controller.save_calls[0][0]
    overrides = dict(saved.routes.overrides)
    assert overrides[TaskPurpose.AGENT_ASSISTANT] == route
    assert overrides[TaskPurpose.MEMORY_EXTRACTION] == route
    assert overrides[TaskPurpose.LOCAL_REPAIR] == route

    repository = ModelConfigRepository(
        tmp_path / "model-config.json",
        MemoryCredentialStore(),
    )
    repository.save(saved, {})
    assert repository.load() == saved


def test_editing_existing_connection_preserves_credential_reference(qtbot: QtBot) -> None:
    controller = FakeSettingsController()
    profile = _provider()
    model = ModelProfile("relay", "plot-model")
    route = ModelRoute("relay", "plot-model")
    controller.configuration = ModelConfiguration(
        providers=(profile,),
        models=(model,),
        routes=TaskRoutes(plot=route, prose=route),
    )
    dialog = SettingsDialog(controller=controller)
    qtbot.addWidget(dialog)

    dialog.connection_name.setText("修改后的名称")
    dialog.save_button.click()

    saved = controller.save_calls[0][0]
    assert saved.providers[0].credential_id == "credential-relay"


class FakeService:
    def __init__(self) -> None:
        self.chat_calls = []

    def stream_chat(self, conversation, manuscript, limit):  # type: ignore[no-untyped-def]
        from ai_novel_studio.infrastructure.llm import LLMStreamEvent, StreamEventKind

        self.chat_calls.append((conversation, manuscript, limit))
        yield LLMStreamEvent(StreamEventKind.TEXT, text="模型回复")
        yield LLMStreamEvent(StreamEventKind.COMPLETED)

    def draft_chapter_requirement(self, conversation, manuscript, limit):  # type: ignore[no-untyped-def]
        return "模型生成的正式当前章要求"

    def normalize_brief(self, source, limit):  # type: ignore[no-untyped-def]
        from ai_novel_studio.application.model_tasks import NormalizedBrief

        return NormalizedBrief("模型整理的戏剧功能", ("事件甲",), (), (), ())

    def audit_style(self, manuscript, rules, limit):  # type: ignore[no-untyped-def]
        from ai_novel_studio.application.model_tasks import StyleAuditFinding, StyleAuditResult

        return StyleAuditResult(
            "发现一处问题",
            (StyleAuditFinding("声音", "区分不足", "证据句", "中"),),
        )

    def usage_snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(1, 0, 1200, 300, 400, 0, 0, 0, True, 0.02)


def _runtime(tmp_path: Path) -> tuple[ModelRuntime, FakeService]:
    credentials = MemoryCredentialStore()
    repository = ModelConfigRepository(tmp_path / "models.json", credentials)
    service = FakeService()
    runtime = ModelRuntime.for_test(repository, credentials, service)  # type: ignore[arg-type]
    return runtime, service


def test_main_window_streams_plot_reply_and_passes_current_manuscript(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, service = _runtime(tmp_path)
    window = MainWindow(model_runtime=runtime)
    qtbot.addWidget(window)
    window.manuscript_panel.output_token_limit.setValue(200_000)
    window.plot_chat_panel.composer.setPlainText("继续讨论")

    window.plot_chat_panel.send_button.click()

    qtbot.waitUntil(lambda: window.plot_chat_panel.message_bubbles[-1].text() == "模型回复")
    assert service.chat_calls[0][1] == window.manuscript_panel.editor.toPlainText()
    assert service.chat_calls[0][2] == 200_000
    assert window.top_bar.metrics["input"].value_text() == "1.2K"


def test_model_requirement_respects_lock_and_replaces_only_after_unlock(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, _ = _runtime(tmp_path)
    window = MainWindow(model_runtime=runtime)
    qtbot.addWidget(window)
    original = window.manuscript_panel.chapter_requirement.toPlainText()
    window.manuscript_panel.toggle_requirement_lock()

    window.plot_chat_panel.requirement_button.click()
    qtbot.wait(100)
    assert window.manuscript_panel.chapter_requirement.toPlainText() == original

    window.manuscript_panel.toggle_requirement_lock()
    window.plot_chat_panel.requirement_button.click()
    qtbot.waitUntil(
        lambda: window.manuscript_panel.chapter_requirement.toPlainText()
        == "模型生成的正式当前章要求"
    )


def test_brief_normalization_and_style_audit_update_review_surfaces(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, _ = _runtime(tmp_path)
    window = MainWindow(model_runtime=runtime)
    qtbot.addWidget(window)
    window.open_brief_dialog()
    assert window.brief_dialog is not None
    window.brief_dialog.normalize_button.click()
    qtbot.waitUntil(
        lambda: "模型整理" in window.brief_dialog.section_editors["戏剧功能"].toPlainText()
    )

    window.open_audit_window()
    assert window.audit_window is not None
    window.audit_window.run_model_audit_button.click()
    qtbot.waitUntil(
        lambda: window.audit_window.model_table.item(0, 2).text() == "证据句"
    )
    assert window.audit_window.model_table.item(0, 2).text() == "证据句"
    assert "阶段 6" in window.audit_window.repair_button.toolTip()
    assert "阶段 5" in window.manuscript_panel.generate_button.toolTip()
