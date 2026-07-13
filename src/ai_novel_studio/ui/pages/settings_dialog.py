from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.model_settings_controller import ModelSettingsController
from ai_novel_studio.infrastructure.llm import (
    CapabilityProbeResult,
    ModelConfiguration,
    ModelProfile,
    ModelRoute,
    ModelSamplingParameters,
    ProviderProfile,
    TaskPurpose,
    TaskRoutes,
)
from ai_novel_studio.ui.appearance import (
    InformationDensity,
    ThemePreference,
    appearance_manager,
)
from ai_novel_studio.ui.i18n import Language, language_manager


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: ModelSettingsController | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.configuration = (
            controller.configuration if controller is not None else ModelConfiguration.empty()
        )
        self._providers = {profile.id: profile for profile in self.configuration.providers}
        self._models = {
            (model.provider_id, model.model_id): model for model in self.configuration.models
        }
        self._current_provider_id = ""
        self._current_model_key: tuple[str, str] | None = None
        self.setWindowTitle("设置 · AI Novel Studio")
        self.setMinimumSize(640, 480)
        self.resize(820, 680)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._model_tab(), "模型连接")
        self.tabs.addTab(self._appearance_tab(), "外观")
        self.tabs.addTab(self._creation_tab(), "创作默认值")
        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName("settingsContentScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setWidget(self.tabs)

        self.save_button = QPushButton("保存设置", self)
        self.save_button.setAccessibleName("保存模型和应用设置")
        self.save_button.setProperty("buttonRole", "primary")
        self.save_button.clicked.connect(self.save_model_settings)
        close_button = QPushButton("关闭", self)
        close_button.setAccessibleName("关闭设置")
        close_button.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(self.status_label)
        actions.addStretch(1)
        actions.addWidget(close_button)
        actions.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(self.content_scroll, 1)
        layout.addLayout(actions)

        if self.controller is not None:
            self.controller.models_loaded.connect(self._apply_models)
            self.controller.capabilities_loaded.connect(self._apply_capabilities)
            self.controller.saved.connect(self._settings_saved)
            self.controller.failed.connect(self._show_error)
        self._populate_connections()

    def _model_tab(self) -> QWidget:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        connection_box = QGroupBox("API 连接", page)
        connection_form = QFormLayout(connection_box)
        self.connection_combo = QComboBox(connection_box)
        self.connection_combo.setAccessibleName("模型连接")
        self.connection_combo.currentIndexChanged.connect(self._connection_changed)
        add_button = QPushButton("新增", connection_box)
        add_button.setAccessibleName("新增模型连接")
        add_button.clicked.connect(self.add_connection)
        delete_button = QPushButton("删除", connection_box)
        delete_button.setAccessibleName("删除当前模型连接")
        delete_button.clicked.connect(self.delete_current_connection)
        selector_row = QHBoxLayout()
        selector_row.addWidget(self.connection_combo, 1)
        selector_row.addWidget(add_button)
        selector_row.addWidget(delete_button)
        self.connection_name = QLineEdit(connection_box)
        self.connection_name.setAccessibleName("连接名称")
        self.base_url = QLineEdit(connection_box)
        self.base_url.setAccessibleName("API Base URL")
        self.models_url = QLineEdit(connection_box)
        self.models_url.setAccessibleName("模型列表地址")
        self.models_url.setPlaceholderText("留空则使用 Base URL /models")
        self.api_key = QLineEdit(connection_box)
        self.api_key.setAccessibleName("API Key")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("留空则继续使用系统凭据中已保存的 Key")
        self.timeout_seconds = QSpinBox(connection_box)
        self.timeout_seconds.setRange(1, 600)
        self.timeout_seconds.setValue(90)
        self.timeout_seconds.setSuffix(" 秒")
        self.timeout_seconds.setAccessibleName("API 请求超时")
        self.interface_type = QComboBox(connection_box)
        self.interface_type.addItem("OpenAI-compatible", "openai_compatible")
        self.interface_type.setAccessibleName("API 接口类型")
        self.refresh_models_button = QPushButton("连接并获取模型", connection_box)
        self.refresh_models_button.setAccessibleName("连接第三方 API 并获取模型列表")
        self.refresh_models_button.clicked.connect(self.refresh_models)
        self.available_model_combo = QComboBox(connection_box)
        self.available_model_combo.setAccessibleName("待探测能力的模型")
        self.available_model_combo.currentIndexChanged.connect(
            self._model_selection_changed
        )
        self.probe_capabilities_button = QPushButton("探测所选模型能力", connection_box)
        self.probe_capabilities_button.setAccessibleName("探测所选模型的实际 API 能力")
        self.probe_capabilities_button.clicked.connect(self.probe_capabilities)
        self.capability_status = QLabel("能力：尚未探测", connection_box)
        self.capability_status.setObjectName("mutedLabel")
        self.advanced_parameters_button = QPushButton(
            "高级生成参数 ▾", connection_box
        )
        self.advanced_parameters_button.setCheckable(True)
        self.advanced_parameters_button.setAccessibleName("展开高级生成参数")
        self.advanced_parameters_button.toggled.connect(
            self._toggle_advanced_parameters
        )
        self.advanced_parameters_panel = QWidget(connection_box)
        advanced_form = QFormLayout(self.advanced_parameters_panel)
        advanced_form.setContentsMargins(0, 4, 0, 0)
        self.custom_sampling = QCheckBox(
            "为当前模型覆盖默认采样参数", self.advanced_parameters_panel
        )
        self.custom_sampling.toggled.connect(self._sampling_enabled_changed)
        self.temperature = self._sampling_spinbox(0, 2, 0.7, 0.1)
        self.top_p = self._sampling_spinbox(0, 1, 1.0, 0.05)
        self.frequency_penalty = self._sampling_spinbox(-2, 2, 0.0, 0.1)
        self.presence_penalty = self._sampling_spinbox(-2, 2, 0.0, 0.1)
        advanced_form.addRow(self.custom_sampling)
        advanced_form.addRow("温度", self.temperature)
        advanced_form.addRow("Top P", self.top_p)
        advanced_form.addRow("频率惩罚", self.frequency_penalty)
        advanced_form.addRow("存在惩罚", self.presence_penalty)
        advanced_hint = QLabel(
            "仅覆盖当前选中模型。关闭后继续使用各创作任务的安全默认值；部分中转站可能不支持全部参数。",
            self.advanced_parameters_panel,
        )
        advanced_hint.setWordWrap(True)
        advanced_hint.setObjectName("mutedLabel")
        advanced_form.addRow(advanced_hint)
        self.advanced_parameters_panel.setVisible(False)
        self._sampling_enabled_changed(False)
        connection_form.addRow("连接", selector_row)
        connection_form.addRow("名称", self.connection_name)
        connection_form.addRow("Base URL", self.base_url)
        connection_form.addRow("模型列表地址", self.models_url)
        connection_form.addRow("API Key", self.api_key)
        connection_form.addRow("接口类型", self.interface_type)
        connection_form.addRow("超时", self.timeout_seconds)
        connection_form.addRow("", self.refresh_models_button)
        connection_form.addRow("已发现模型", self.available_model_combo)
        connection_form.addRow("", self.probe_capabilities_button)
        connection_form.addRow("", self.capability_status)
        connection_form.addRow("", self.advanced_parameters_button)
        connection_form.addRow("", self.advanced_parameters_panel)

        route_box = QGroupBox("默认模型与任务覆盖", page)
        route_form = QFormLayout(route_box)
        self.plot_model_combo = self._route_combo("剧情商讨模型", route_box)
        self.prose_model_combo = self._route_combo("正文创作模型", route_box)
        self.brief_model_combo = self._route_combo("Brief 整理模型", route_box)
        self.agent_model_combo = self._route_combo("工具检索模型", route_box)
        self.audit_model_combo = self._route_combo("文风审校模型", route_box)
        route_form.addRow("剧情商讨（默认）", self.plot_model_combo)
        route_form.addRow("正文创作（默认）", self.prose_model_combo)
        route_form.addRow("Brief 整理（可覆盖）", self.brief_model_combo)
        route_form.addRow("工具检索（可覆盖）", self.agent_model_combo)
        route_form.addRow("文风审校（可覆盖）", self.audit_model_combo)
        hint = QLabel(
            "默认模型负责同类基础任务；“可覆盖”可为某项高级任务指定专用模型，未指定时继承对应默认模型。程序不会在失败后自动改用其他付费模型。",
            route_box,
        )
        hint.setWordWrap(True)
        hint.setObjectName("mutedLabel")
        route_form.addRow(hint)

        self.status_label = QLabel("模型设置尚未保存", page)
        self.status_label.setObjectName("mutedLabel")
        layout.addWidget(connection_box)
        layout.addWidget(route_box)
        layout.addStretch(1)
        return page

    @staticmethod
    def _route_combo(accessible_name: str, parent: QWidget) -> QComboBox:
        combo = QComboBox(parent)
        combo.setAccessibleName(accessible_name)
        return combo

    def _sampling_spinbox(
        self,
        minimum: float,
        maximum: float,
        value: float,
        step: float,
    ) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox(self.advanced_parameters_panel)
        spinbox.setRange(minimum, maximum)
        spinbox.setDecimals(2)
        spinbox.setSingleStep(step)
        spinbox.setValue(value)
        return spinbox

    def _toggle_advanced_parameters(self, expanded: bool) -> None:
        self.advanced_parameters_panel.setVisible(expanded)
        self.advanced_parameters_button.setText(
            "高级生成参数 ▴" if expanded else "高级生成参数 ▾"
        )
        self.advanced_parameters_button.setAccessibleName(
            "收起高级生成参数" if expanded else "展开高级生成参数"
        )

    def _sampling_enabled_changed(self, enabled: bool) -> None:
        for editor in (
            self.temperature,
            self.top_p,
            self.frequency_penalty,
            self.presence_penalty,
        ):
            editor.setEnabled(enabled)

    def _appearance_tab(self) -> QWidget:
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        self.theme_combo = QComboBox(page)
        self.theme_combo.addItem("浅色（当前）", ThemePreference.LIGHT.value)
        self.theme_combo.addItem("跟随系统", ThemePreference.SYSTEM.value)
        theme_index = self.theme_combo.findData(appearance_manager().theme.value)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.theme_combo.setAccessibleName("界面主题")
        self.density_combo = QComboBox(page)
        self.density_combo.addItem("适中", InformationDensity.NORMAL.value)
        self.density_combo.addItem("紧凑", InformationDensity.COMPACT.value)
        self.density_combo.addItem("宽松", InformationDensity.COMFORTABLE.value)
        density_index = self.density_combo.findData(appearance_manager().density.value)
        self.density_combo.setCurrentIndex(max(0, density_index))
        self.density_combo.setAccessibleName("界面密度")
        self.language_combo = QComboBox(page)
        self.language_combo.addItem("简体中文", Language.CHINESE.value)
        self.language_combo.addItem("English", Language.ENGLISH.value)
        language_index = self.language_combo.findData(language_manager().language.value)
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.language_combo.setAccessibleName("界面语言")
        form.addRow("主题", self.theme_combo)
        form.addRow("信息密度", self.density_combo)
        form.addRow("语言", self.language_combo)
        return page

    def _creation_tab(self) -> QWidget:
        page = QWidget(self.tabs)
        form = QFormLayout(page)
        target_words = QSpinBox(page)
        target_words.setRange(500, 50000)
        target_words.setValue(3500)
        target_words.setAccessibleName("默认目标字数")
        output_tokens = QSpinBox(page)
        output_tokens.setRange(256, 200000)
        output_tokens.setValue(8000)
        output_tokens.setAccessibleName("默认输出 Token 上限")
        form.addRow("目标字数", target_words)
        form.addRow("输出 Token 上限", output_tokens)
        return page

    def _populate_connections(self) -> None:
        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()
        for profile in self._providers.values():
            self.connection_combo.addItem(profile.name, profile.id)
        self.connection_combo.blockSignals(False)
        if self.connection_combo.count():
            self.connection_combo.setCurrentIndex(0)
            self._connection_changed(0)
        else:
            self.add_connection()
        self._refresh_route_choices()

    def add_connection(self) -> None:
        self._store_current_sampling()
        self._store_current_profile(ignore_errors=True)
        provider_id = f"connection-{uuid4().hex}"
        default_name = language_manager().translate("新连接")
        self.connection_combo.addItem(default_name, provider_id)
        self.connection_combo.setCurrentIndex(self.connection_combo.count() - 1)
        self.connection_name.setText(default_name)
        self.base_url.setText("https://api.example.com/v1")
        self.models_url.clear()
        self.api_key.clear()
        self.timeout_seconds.setValue(90)

    def delete_current_connection(self) -> None:
        self._store_current_sampling()
        provider_id = self.connection_combo.currentData()
        if not isinstance(provider_id, str):
            return
        self._current_provider_id = ""
        self._providers.pop(provider_id, None)
        self._models = {key: model for key, model in self._models.items() if key[0] != provider_id}
        index = self.connection_combo.currentIndex()
        self.connection_combo.removeItem(index)
        if not self.connection_combo.count():
            self.add_connection()
        self._refresh_route_choices()

    def _connection_changed(self, index: int) -> None:
        if index < 0:
            return
        if self._current_provider_id:
            self._store_current_sampling()
            self._store_current_profile(ignore_errors=True)
        provider_id = self.connection_combo.itemData(index)
        if not isinstance(provider_id, str):
            return
        self._current_provider_id = provider_id
        profile = self._providers.get(provider_id)
        if profile is None:
            return
        self.connection_name.setText(profile.name)
        self.base_url.setText(profile.base_url)
        self.models_url.setText(profile.models_url or "")
        self.timeout_seconds.setValue(profile.timeout_seconds)
        interface_index = self.interface_type.findData(profile.interface_type)
        if interface_index >= 0:
            self.interface_type.setCurrentIndex(interface_index)
        self.api_key.clear()
        if self.controller is not None and self.controller.has_credential(profile.credential_id):
            self.api_key.setPlaceholderText("已安全保存；留空表示保持不变")
        self._refresh_available_models()

    def _profile_from_fields(self) -> ProviderProfile:
        if not self._current_provider_id:
            raise ValueError("请先选择模型连接")
        existing = self._providers.get(self._current_provider_id)
        credential_id = (
            existing.credential_id
            if existing is not None
            else f"provider-{self._current_provider_id}"
        )
        return ProviderProfile(
            id=self._current_provider_id,
            name=self.connection_name.text().strip(),
            base_url=self.base_url.text().strip(),
            credential_id=credential_id,
            interface_type=str(self.interface_type.currentData()),
            timeout_seconds=self.timeout_seconds.value(),
            models_url=self.models_url.text().strip() or None,
        )

    def _store_current_profile(self, *, ignore_errors: bool = False) -> None:
        if not self._current_provider_id:
            return
        try:
            profile = self._profile_from_fields()
        except ValueError:
            if ignore_errors:
                return
            raise
        self._providers[profile.id] = profile
        index = self.connection_combo.findData(profile.id)
        if index >= 0:
            self.connection_combo.setItemText(index, profile.name)

    def refresh_models(self) -> None:
        if self.controller is None:
            self._show_error("当前窗口未连接模型配置服务")
            return
        try:
            profile = self._profile_from_fields()
            self._providers[profile.id] = profile
        except ValueError as error:
            self._show_error(str(error))
            return
        self.status_label.setText("正在获取模型列表……")
        self.controller.refresh_models(profile, self.api_key.text())

    def _apply_models(self, provider_id: str, models: object) -> None:
        if not isinstance(models, tuple) or any(
            not isinstance(model, ModelProfile) for model in models
        ):
            self._show_error("模型列表格式无效")
            return
        previous = dict(self._models)
        self._models = {key: value for key, value in self._models.items() if key[0] != provider_id}
        for model in models:
            key = (model.provider_id, model.model_id)
            existing = previous.get(key)
            self._models[key] = (
                replace(model, sampling=existing.sampling)
                if existing is not None
                else model
            )
        self._refresh_available_models()
        self._refresh_route_choices()
        self.status_label.setText(f"已获取 {len(models)} 个模型；保存后生效")

    def _refresh_available_models(self) -> None:
        self._store_current_sampling()
        selected = self.available_model_combo.currentData()
        self.available_model_combo.blockSignals(True)
        self.available_model_combo.clear()
        for model in sorted(
            (
                item
                for item in self._models.values()
                if item.provider_id == self._current_provider_id
            ),
            key=lambda item: item.model_id,
        ):
            self.available_model_combo.addItem(model.display_name or model.model_id, model.model_id)
        index = self.available_model_combo.findData(selected)
        if index >= 0:
            self.available_model_combo.setCurrentIndex(index)
        self.available_model_combo.blockSignals(False)
        self._model_selection_changed(self.available_model_combo.currentIndex())

    def _model_selection_changed(self, index: int) -> None:
        self._store_current_sampling()
        model_id = self.available_model_combo.itemData(index) if index >= 0 else None
        if not isinstance(model_id, str):
            self._current_model_key = None
            self.custom_sampling.setChecked(False)
            self.advanced_parameters_button.setEnabled(False)
            return
        key = (self._current_provider_id, model_id)
        self._current_model_key = key
        model = self._models.get(key)
        sampling = model.sampling if model is not None else ModelSamplingParameters()
        enabled = any(
            value is not None
            for value in (
                sampling.temperature,
                sampling.top_p,
                sampling.frequency_penalty,
                sampling.presence_penalty,
            )
        )
        self.custom_sampling.blockSignals(True)
        self.custom_sampling.setChecked(enabled)
        self.custom_sampling.blockSignals(False)
        self.temperature.setValue(
            sampling.temperature if sampling.temperature is not None else 0.7
        )
        self.top_p.setValue(sampling.top_p if sampling.top_p is not None else 1.0)
        self.frequency_penalty.setValue(sampling.frequency_penalty or 0.0)
        self.presence_penalty.setValue(sampling.presence_penalty or 0.0)
        self.advanced_parameters_button.setEnabled(model is not None)
        self._sampling_enabled_changed(enabled)

    def _store_current_sampling(self) -> None:
        if self._current_model_key is None:
            return
        model = self._models.get(self._current_model_key)
        if model is None:
            return
        sampling = (
            ModelSamplingParameters(
                temperature=self.temperature.value(),
                top_p=self.top_p.value(),
                frequency_penalty=self.frequency_penalty.value(),
                presence_penalty=self.presence_penalty.value(),
            )
            if self.custom_sampling.isChecked()
            else ModelSamplingParameters()
        )
        self._models[self._current_model_key] = replace(model, sampling=sampling)

    def probe_capabilities(self) -> None:
        if self.controller is None:
            self._show_error("当前窗口未连接模型配置服务")
            return
        model_id = self.available_model_combo.currentData()
        if not isinstance(model_id, str):
            self._show_error("请先获取并选择模型")
            return
        try:
            profile = self._profile_from_fields()
        except ValueError as error:
            self._show_error(str(error))
            return
        self.capability_status.setText("能力：正在执行实际请求探测…")
        self.controller.probe_capabilities(profile, model_id, self.api_key.text())

    def _apply_capabilities(
        self,
        provider_id: str,
        model_id: str,
        result: object,
    ) -> None:
        if not isinstance(result, CapabilityProbeResult):
            self._show_error("能力探测结果格式无效")
            return
        key = (provider_id, model_id)
        model = self._models.get(key)
        if model is not None:
            capabilities = replace(
                model.capabilities,
                streaming=result.streaming,
                reasoning=result.reasoning,
                tools=result.tools,
                strict_json=result.strict_json,
            )
            self._models[key] = replace(model, capabilities=capabilities)
        self.capability_status.setText(
            "能力："
            f"流式：{self._support_text(result.streaming)} · "
            f"JSON：{self._support_text(result.strict_json)} · "
            f"工具：{self._support_text(result.tools)} · "
            f"推理：{self._support_text(result.reasoning)}"
        )

    @staticmethod
    def _support_text(value: bool | None) -> str:
        if value is None:
            return "未知"
        return "支持" if value else "不支持"

    def _refresh_route_choices(self) -> None:
        current = self.configuration.routes
        selections = {
            self.plot_model_combo: current.plot,
            self.prose_model_combo: current.prose,
            self.brief_model_combo: self._override(current, TaskPurpose.BRIEF_NORMALIZATION),
            self.agent_model_combo: self._override(current, TaskPurpose.AGENT_ASSISTANT),
            self.audit_model_combo: self._override(current, TaskPurpose.STYLE_AUDIT),
        }
        default_combos = {self.plot_model_combo, self.prose_model_combo}
        for combo, selected in selections.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(
                "未配置" if combo in default_combos else "未配置 / 继承对应默认模型",
                None,
            )
            for model in sorted(
                self._models.values(), key=lambda item: (item.provider_id, item.model_id)
            ):
                provider = self._providers.get(model.provider_id)
                provider_name = provider.name if provider is not None else model.provider_id
                display = model.display_name or model.model_id
                combo.addItem(
                    f"{provider_name} · {display}",
                    ModelRoute(model.provider_id, model.model_id),
                )
            index = combo.findData(selected)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    @staticmethod
    def _override(routes: TaskRoutes, purpose: TaskPurpose) -> ModelRoute | None:
        for configured_purpose, route in routes.overrides:
            if configured_purpose == purpose:
                return route
        return None

    def save_model_settings(self) -> None:
        theme = self.theme_combo.currentData()
        density = self.density_combo.currentData()
        if isinstance(theme, str) and isinstance(density, str):
            appearance_manager().set_preferences(theme, density)
        language = self.language_combo.currentData()
        if isinstance(language, str):
            language_manager().set_language(language)
        if self.controller is None:
            self._show_error("当前窗口未连接模型配置服务")
            return
        try:
            self._store_current_sampling()
            self._store_current_profile()
            overrides: list[tuple[TaskPurpose, ModelRoute]] = []
            brief = self.brief_model_combo.currentData()
            agent = self.agent_model_combo.currentData()
            audit = self.audit_model_combo.currentData()
            if isinstance(brief, ModelRoute):
                overrides.append((TaskPurpose.BRIEF_NORMALIZATION, brief))
            if isinstance(agent, ModelRoute):
                overrides.append((TaskPurpose.AGENT_ASSISTANT, agent))
            if isinstance(audit, ModelRoute):
                overrides.append((TaskPurpose.STYLE_AUDIT, audit))
            configuration = ModelConfiguration(
                providers=tuple(self._providers.values()),
                models=tuple(self._models.values()),
                routes=TaskRoutes(
                    plot=self._selected_route(self.plot_model_combo),
                    prose=self._selected_route(self.prose_model_combo),
                    overrides=tuple(overrides),
                ),
            )
            profile = self._providers.get(self._current_provider_id)
            keys = (
                {profile.credential_id: self.api_key.text()}
                if profile is not None and self.api_key.text()
                else {}
            )
            self.controller.save(configuration, keys)
        except ValueError as error:
            self._show_error(str(error))

    @staticmethod
    def _selected_route(combo: QComboBox) -> ModelRoute | None:
        value = combo.currentData()
        return value if isinstance(value, ModelRoute) else None

    def _settings_saved(self, configuration: object) -> None:
        if isinstance(configuration, ModelConfiguration):
            self.configuration = configuration
        self.api_key.clear()
        self.status_label.setText("模型设置已保存")

    def _show_error(self, message: str) -> None:
        self.status_label.setText(f"错误：{message}")
