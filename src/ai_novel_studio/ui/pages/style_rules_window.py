from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.style_workspace_service import StyleWorkspaceService
from ai_novel_studio.domain.memory import (
    Authority,
    ReviewStatus,
    StyleRule,
    StyleSample,
    StyleScope,
)
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.feature_flags import LEGACY_STYLE_AUTOMATION_VISIBLE

_SCOPE_LABELS = {
    StyleScope.BOOK: "全书",
    StyleScope.GENRE_OR_SCENE: "场景 / 类型",
    StyleScope.CHARACTER: "人物",
    StyleScope.CHAPTER: "章节",
}


class StyleRulesWindow(QMainWindow):
    def __init__(
        self,
        data: WorkspaceDemoData,
        parent: QWidget | None = None,
        *,
        service: StyleWorkspaceService | None = None,
        default_scope_id: str = "",
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._default_scope_id = default_scope_id
        self._rules: dict[str, StyleRule] = {}
        self._samples: dict[str, StyleSample] = {}
        self.setWindowTitle("文风规则 · AI Novel Studio")
        self.setMinimumSize(820, 640)
        self.resize(960, 740)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("人工文风样章", surface)
        title.setObjectName("panelTitle")
        explanation = QLabel(
            "当前仅使用人工样章作为文风参考。旧分层规则和 AI 候选数据仍保留，"
            "但已停止在界面中使用，等待后续安全迁移。",
            surface,
        )
        explanation.setObjectName("mutedLabel")
        explanation.setWordWrap(True)
        self.status_label = QLabel("", surface)
        self.status_label.setObjectName("mutedLabel")

        self.tabs = QTabWidget(surface)
        self._build_rules_tab(data)
        self._build_samples_tab()
        self._build_candidates_tab()
        if not LEGACY_STYLE_AUTOMATION_VISIBLE:
            self.tabs.setTabVisible(0, False)
            self.tabs.setTabVisible(2, False)
            self.tabs.setCurrentIndex(1)

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status_label)
        self.setCentralWidget(surface)
        self.reload()

    def _build_rules_tab(self, data: WorkspaceDemoData) -> None:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        self.rules_table = QTableWidget(0, 3, page)
        self.rules_table.setHorizontalHeaderLabels(("层级", "规则", "范围 / 权威"))
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self.rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rules_table.itemSelectionChanged.connect(self._load_selected_rule)
        layout.addWidget(self.rules_table, 1)

        form = QFormLayout()
        self.rule_scope_combo = self._scope_combo(page)
        self.rule_scope_id = QLineEdit(self._default_scope_id, page)
        self.rule_type = QLineEdit(page)
        self.rule_type.setPlaceholderText("例如：叙述节奏、人物语言、禁用表达")
        self.rule_text = QPlainTextEdit(page)
        self.rule_text.setMaximumHeight(110)
        form.addRow("层级", self.rule_scope_combo)
        form.addRow("范围 ID", self.rule_scope_id)
        form.addRow("规则类型", self.rule_type)
        form.addRow("规则正文", self.rule_text)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.new_rule_button = QPushButton("新建规则", page)
        self.save_rule_button = QPushButton("保存规则", page)
        self.delete_rule_button = QPushButton("删除规则", page)
        actions.addWidget(self.new_rule_button)
        actions.addWidget(self.save_rule_button)
        actions.addWidget(self.delete_rule_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.new_rule_button.clicked.connect(self._new_rule)
        self.save_rule_button.clicked.connect(self._save_rule)
        self.delete_rule_button.clicked.connect(self._delete_rule)
        if self._service is None:
            for scope, rule, authority in data.style_rules:
                row = self.rules_table.rowCount()
                self.rules_table.insertRow(row)
                for column, value in enumerate((scope, rule, authority)):
                    self.rules_table.setItem(row, column, QTableWidgetItem(value))

        self.tabs.addTab(page, "分层规则")

    def _build_samples_tab(self) -> None:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        self.sample_selector = QComboBox(page)
        self.sample_selector.currentIndexChanged.connect(self._load_selected_sample)
        layout.addWidget(self.sample_selector)
        form = QFormLayout()
        self.sample_scope_combo = self._scope_combo(page)
        self.sample_scope_id = QLineEdit(self._default_scope_id, page)
        self.sample_title = QLineEdit(page)
        form.addRow("层级", self.sample_scope_combo)
        form.addRow("范围 ID", self.sample_scope_id)
        form.addRow("样章标题", self.sample_title)
        layout.addLayout(form)
        self.human_sample = QPlainTextEdit(page)
        self.human_sample.setAccessibleName("人工文风样章")
        self.human_sample.setPlaceholderText("粘贴或输入希望模型模仿的人工样章……")
        layout.addWidget(self.human_sample, 1)
        actions = QHBoxLayout()
        self.new_sample_button = QPushButton("新建样章", page)
        self.save_sample_button = QPushButton("保存样章", page)
        self.lock_sample_button = QPushButton("锁定样章", page)
        self.delete_sample_button = QPushButton("删除样章", page)
        actions.addWidget(self.new_sample_button)
        actions.addWidget(self.save_sample_button)
        actions.addWidget(self.lock_sample_button)
        actions.addWidget(self.delete_sample_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.new_sample_button.clicked.connect(self._new_sample)
        self.save_sample_button.clicked.connect(self._save_sample)
        self.lock_sample_button.clicked.connect(self._lock_sample)
        self.delete_sample_button.clicked.connect(self._delete_sample)
        self.tabs.addTab(page, "人工样章")

    def _build_candidates_tab(self) -> None:
        self.candidate_editor = QPlainTextEdit(self.tabs)
        self.candidate_editor.setReadOnly(True)
        self.candidate_editor.setAccessibleName("AI 文风候选规则")
        self.candidate_editor.setPlaceholderText(
            "AI 提取的文风候选会显示在这里；请在记忆库审查后再作为正式规则使用。"
        )
        self.tabs.addTab(self.candidate_editor, "AI 候选")

    @staticmethod
    def _scope_combo(parent: QWidget) -> QComboBox:
        combo = QComboBox(parent)
        for scope, label in _SCOPE_LABELS.items():
            combo.addItem(label, scope)
        return combo

    def reload(self) -> None:
        if self._service is None:
            self.human_sample.setReadOnly(True)
            self.human_sample.setPlainText("当前未打开项目，人工样章不可保存。")
            for button in (
                self.new_rule_button,
                self.save_rule_button,
                self.delete_rule_button,
                self.new_sample_button,
                self.save_sample_button,
                self.lock_sample_button,
                self.delete_sample_button,
            ):
                button.setEnabled(False)
            return
        snapshot = self._service.load()
        self._rules = {item.id: item for item in snapshot.rules}
        self._samples = {item.id: item for item in snapshot.samples}
        self._refresh_rules()
        self._refresh_samples()
        candidates = [
            item
            for item in snapshot.rules
            if item.authority == Authority.MODEL_EXTRACTED
            and item.review_status == ReviewStatus.REVIEW
        ]
        self.candidate_editor.setPlainText(
            "\n\n".join(
                f"[{_SCOPE_LABELS[item.scope_type]} / {item.rule_type}]\n{item.rule_text}"
                for item in candidates
            )
        )

    def _refresh_rules(self) -> None:
        self.rules_table.setRowCount(0)
        for rule in self._rules.values():
            row = self.rules_table.rowCount()
            self.rules_table.insertRow(row)
            values = (
                _SCOPE_LABELS[rule.scope_type],
                rule.rule_text,
                f"{rule.scope_id} / {rule.authority.value} / {rule.review_status.value}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, rule.id)
                self.rules_table.setItem(row, column, item)

    def _refresh_samples(self) -> None:
        selected = self.sample_selector.currentData()
        self.sample_selector.blockSignals(True)
        self.sample_selector.clear()
        self.sample_selector.addItem("新样章", None)
        for sample in self._samples.values():
            suffix = "（已锁定）" if sample.immutable else ""
            self.sample_selector.addItem(sample.title + suffix, sample.id)
        index = self.sample_selector.findData(selected)
        self.sample_selector.setCurrentIndex(index if index >= 0 else 0)
        self.sample_selector.blockSignals(False)
        self._load_selected_sample()

    def _selected_rule_id(self) -> str | None:
        row = self.rules_table.currentRow()
        item = self.rules_table.item(row, 0) if row >= 0 else None
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    @staticmethod
    def _current_scope(combo: QComboBox) -> StyleScope:
        value = combo.currentData()
        return value if isinstance(value, StyleScope) else StyleScope(str(value))

    def _load_selected_rule(self) -> None:
        rule_id = self._selected_rule_id()
        rule = self._rules.get(rule_id or "")
        if rule is None:
            return
        self.rule_scope_combo.setCurrentIndex(self.rule_scope_combo.findData(rule.scope_type))
        self.rule_scope_id.setText(rule.scope_id)
        self.rule_type.setText(rule.rule_type)
        self.rule_text.setPlainText(rule.rule_text)

    def _new_rule(self) -> None:
        self.rules_table.clearSelection()
        self.rule_scope_id.setText(self._default_scope_id)
        self.rule_type.clear()
        self.rule_text.clear()

    def _save_rule(self) -> None:
        if self._service is None:
            return
        try:
            rule_id = self._selected_rule_id()
            values = (
                self._current_scope(self.rule_scope_combo),
                self.rule_scope_id.text(),
                self.rule_type.text(),
                self.rule_text.toPlainText(),
            )
            if rule_id is None:
                self._service.add_rule(*values)
            else:
                self._service.update_rule(rule_id, *values)
            self.status_label.setText("文风规则已保存")
            self.reload()
        except (KeyError, PermissionError, ValueError) as error:
            self.status_label.setText(f"保存失败：{error}")

    def _delete_rule(self) -> None:
        rule_id = self._selected_rule_id()
        if self._service is None or rule_id is None:
            return
        try:
            self._service.delete_rule(rule_id)
            self.status_label.setText("文风规则已删除")
            self.reload()
        except (KeyError, PermissionError, ValueError) as error:
            self.status_label.setText(f"删除失败：{error}")

    def _selected_sample(self) -> StyleSample | None:
        value = self.sample_selector.currentData()
        return self._samples.get(str(value)) if value else None

    def _load_selected_sample(self, _index: int = -1) -> None:
        sample = self._selected_sample()
        if sample is None:
            self.sample_scope_id.setText(self._default_scope_id)
            self.sample_title.clear()
            self.human_sample.clear()
            locked = False
        else:
            self.sample_scope_combo.setCurrentIndex(
                self.sample_scope_combo.findData(sample.scope_type)
            )
            self.sample_scope_id.setText(sample.scope_id)
            self.sample_title.setText(sample.title)
            self.human_sample.setPlainText(sample.content)
            locked = sample.immutable
        self.sample_scope_combo.setEnabled(not locked)
        self.sample_scope_id.setReadOnly(locked)
        self.sample_title.setReadOnly(locked)
        self.human_sample.setReadOnly(locked)
        self.save_sample_button.setEnabled(not locked)
        self.lock_sample_button.setEnabled(sample is not None and not locked)
        self.delete_sample_button.setEnabled(sample is not None and not locked)

    def _new_sample(self) -> None:
        self.sample_selector.setCurrentIndex(0)

    def _save_sample(self) -> None:
        if self._service is None:
            return
        try:
            sample = self._selected_sample()
            values = (
                self._current_scope(self.sample_scope_combo),
                self.sample_scope_id.text(),
                self.sample_title.text(),
                self.human_sample.toPlainText(),
            )
            if sample is None:
                self._service.add_sample(*values)
            else:
                self._service.update_sample(sample.id, *values)
            self.status_label.setText("人工样章已保存")
            self.reload()
        except (KeyError, PermissionError, ValueError) as error:
            self.status_label.setText(f"保存失败：{error}")

    def _lock_sample(self) -> None:
        sample = self._selected_sample()
        if self._service is None or sample is None:
            return
        try:
            self._service.lock_sample(sample.id)
            self.status_label.setText("人工样章已锁定；锁定后不可修改或删除")
            self.reload()
        except (KeyError, PermissionError, ValueError) as error:
            self.status_label.setText(f"锁定失败：{error}")

    def _delete_sample(self) -> None:
        sample = self._selected_sample()
        if self._service is None or sample is None:
            return
        try:
            self._service.delete_sample(sample.id)
            self.status_label.setText("人工样章已删除")
            self.reload()
        except (KeyError, PermissionError, ValueError) as error:
            self.status_label.setText(f"删除失败：{error}")
