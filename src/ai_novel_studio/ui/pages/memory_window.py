from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.memory_promotion_coordinator import (
    MemoryPromotionCoordinator,
)
from ai_novel_studio.application.memory_workspace_service import (
    MemoryBulkPromotionResult,
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.i18n import language_manager


class MemoryWindow(QMainWindow):
    setting_save_requested = Signal(str, str, str, object)
    setting_analyze_requested = Signal(str, str, str, object)

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service: MemoryWorkspaceService | None = None
        self._records: dict[str, MemoryWorkspaceRecord] = {}
        self.selectors: dict[str, QComboBox] = {}
        self.editors: dict[str, QPlainTextEdit] = {}
        self.field_widgets: dict[str, dict[str, QWidget]] = {}
        self.setting_source_id: str | None = None
        self._promotion_coordinator: MemoryPromotionCoordinator | None = None

        self.setWindowTitle("记忆库 · AI Novel Studio")
        self.setMinimumSize(820, 640)
        self.resize(980, 760)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("长篇记忆库", surface)
        title.setObjectName("panelTitle")
        self.explanation_label = QLabel(
            "这里展示 AI 生成前可检索的压缩前文、人物与读者知识边界、正典和叙事线索。"
            "模型提取内容只会成为待审查候选；只有用户明确晋升后才可成为当前记忆。",
            surface,
        )
        self.explanation_label.setWordWrap(True)
        self.explanation_label.setObjectName("mutedLabel")

        self.tabs = QTabWidget(surface)
        self.tabs.setObjectName("memoryTabs")
        for tab_name, text in data.memory_tabs:
            self._add_demo_tab(tab_name, text)
        self._add_setting_tab()
        self.tabs.currentChanged.connect(self._refresh_current_record)

        note = QFrame(surface)
        note.setObjectName("cardSurface")
        note_layout = QVBoxLayout(note)
        self.metadata_label = QLabel("离线演示数据：尚未绑定项目记忆服务。", note)
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setObjectName("mutedLabel")
        note_layout.addWidget(self.metadata_label)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存人工修改", note)
        self.save_button.setAccessibleName("保存当前记忆记录")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_current)
        self.promote_button = QPushButton("晋升为已审查", note)
        self.promote_button.setAccessibleName("晋升当前候选记忆")
        self.promote_button.setEnabled(False)
        self.promote_button.clicked.connect(self._promote_current)
        self.promote_all_button = QPushButton("一键晋升全部候选", note)
        self.promote_all_button.setAccessibleName("晋升记忆库中的全部待审查候选")
        self.promote_all_button.setEnabled(False)
        self.promote_all_button.clicked.connect(self._promote_all)
        actions.addWidget(self.save_button)
        actions.addWidget(self.promote_button)
        actions.addWidget(self.promote_all_button)
        actions.addStretch(1)
        note_layout.addLayout(actions)

        layout.addWidget(title)
        layout.addWidget(self.explanation_label)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(note)
        self.setCentralWidget(surface)

    def bind(self, service: MemoryWorkspaceService, before_chapter_id: str) -> None:
        if (
            self._promotion_coordinator is not None
            and self._promotion_coordinator.is_running
        ):
            self.metadata_label.setText(
                self._tr("批量晋升仍在后台运行，请等待完成。")
            )
            return
        setting_draft = (
            self._setting_values()
            if hasattr(self, "setting_title_edit")
            else ("", "混合设定", "")
        )
        snapshot = service.load(before_chapter_id)
        grouped: dict[str, list[MemoryWorkspaceRecord]] = defaultdict(list)
        for record in snapshot.records:
            grouped[record.category].append(record)
        self._service = service
        self._promotion_coordinator = MemoryPromotionCoordinator(service, self)
        self._promotion_coordinator.progress_changed.connect(
            self._bulk_promotion_progress
        )
        self._promotion_coordinator.completed.connect(self._bulk_promotion_completed)
        self._promotion_coordinator.failed.connect(self._bulk_promotion_failed)
        self._records = {record.id: record for record in snapshot.records}
        self.tabs.clear()
        self.selectors.clear()
        self.editors.clear()
        self.field_widgets.clear()
        for category, records in grouped.items():
            self._add_record_tab(category, records)
        self._add_setting_tab()
        self.setting_title_edit.setText(setting_draft[0])
        self.setting_type_combo.setCurrentText(setting_draft[1])
        self.setting_editor.setPlainText(setting_draft[2])
        if not grouped:
            self.metadata_label.setText("该章节边界之前没有可显示的记忆记录。")
            self.save_button.setEnabled(False)
            self.promote_button.setEnabled(False)
            self.promote_all_button.setEnabled(False)
            return
        self.tabs.setCurrentIndex(0)
        self._refresh_current_record()

    def _add_setting_tab(self) -> None:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        explanation = QLabel(
            "用于粘贴世界观、人物小传、剧情计划或文风资料。原文会完整保存；"
            "AI 整理结果只会进入待审查候选，不会直接覆盖正式记忆。",
            page,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        form = QFormLayout()
        self.setting_title_edit = QLineEdit(page)
        self.setting_title_edit.setPlaceholderText("例如：世界观与主要人物设定")
        self.setting_type_combo = QComboBox(page)
        self.setting_type_combo.addItems(("混合设定", "世界观", "人物设定", "剧情大纲", "文风资料"))
        form.addRow("资料标题", self.setting_title_edit)
        form.addRow("资料类型", self.setting_type_combo)
        self.setting_editor = QPlainTextEdit(page)
        self.setting_editor.setPlaceholderText("在此粘贴设定文档。建议一次处理一份主题明确的短文档。")
        buttons = QHBoxLayout()
        self.setting_save_button = QPushButton("保存原始资料", page)
        self.setting_analyze_button = QPushButton("AI 整理为待审查候选", page)
        self.setting_status_label = QLabel("尚未保存", page)
        self.setting_status_label.setObjectName("mutedLabel")
        self.setting_save_button.clicked.connect(self._request_setting_save)
        self.setting_analyze_button.clicked.connect(self._request_setting_analyze)
        buttons.addWidget(self.setting_save_button)
        buttons.addWidget(self.setting_analyze_button)
        buttons.addWidget(self.setting_status_label, 1)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.setting_editor, 1)
        layout.addLayout(buttons)
        self.tabs.addTab(page, "设定资料整理")

    def _setting_values(self) -> tuple[str, str, str]:
        return (
            self.setting_title_edit.text().strip(),
            self.setting_type_combo.currentText(),
            self.setting_editor.toPlainText().strip(),
        )

    def _request_setting_save(self) -> None:
        title, document_type, text = self._setting_values()
        self.setting_save_requested.emit(title, document_type, text, self.setting_source_id)

    def _request_setting_analyze(self) -> None:
        title, document_type, text = self._setting_values()
        self.setting_analyze_requested.emit(title, document_type, text, self.setting_source_id)

    def set_setting_busy(self, busy: bool, message: str) -> None:
        self.setting_save_button.setEnabled(not busy)
        self.setting_analyze_button.setEnabled(not busy)
        self.setting_status_label.setText(message)

    def setting_saved(self, source_id: str, message: str) -> None:
        self.setting_source_id = source_id
        self.set_setting_busy(False, message)

    def _add_demo_tab(self, tab_name: str, text: str) -> None:
        editor = QPlainTextEdit(self.tabs)
        editor.setPlainText(text)
        editor.setAccessibleName(f"编辑{tab_name}")
        self.editors[tab_name] = editor
        self.tabs.addTab(editor, tab_name)

    def _add_record_tab(self, category: str, records: list[MemoryWorkspaceRecord]) -> None:
        page = QWidget(self.tabs)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 8, 0, 0)
        selector = QComboBox(page)
        selector.setAccessibleName(f"选择{category}记录")
        for record in records:
            selector.addItem(record.title, record.id)
        editor = QPlainTextEdit(page)
        editor.setAccessibleName(f"编辑{category}")
        field_widgets: dict[str, QWidget] = {}
        fields = records[0].fields
        page_layout.addWidget(selector)
        if fields:
            form = QFormLayout()
            for field in fields:
                widget: QWidget
                if field.choices:
                    widget = QComboBox(page)
                    widget.addItems(field.choices)
                elif field.multiline:
                    widget = QPlainTextEdit(page)
                    widget.setMaximumHeight(90)
                else:
                    widget = QLineEdit(page)
                widget.setAccessibleName(f"{category}：{field.label}")
                field_widgets[field.key] = widget
                form.addRow(field.label, widget)
            page_layout.addLayout(form)
            editor.hide()
        page_layout.addWidget(editor, 1)
        self.selectors[category] = selector
        self.editors[category] = editor
        self.field_widgets[category] = field_widgets
        selector.currentIndexChanged.connect(self._refresh_current_record)
        self.tabs.addTab(page, category)

    def _current_record(self) -> MemoryWorkspaceRecord | None:
        category = self.tabs.tabText(self.tabs.currentIndex())
        selector = self.selectors.get(category)
        if selector is None:
            return None
        record_id = selector.currentData()
        return self._records.get(str(record_id))

    def _refresh_current_record(self, _index: int = -1) -> None:
        record = self._current_record()
        if record is None:
            if self._service is not None:
                self.save_button.setEnabled(False)
                self.promote_button.setEnabled(False)
                self._refresh_bulk_promotion_button()
            return
        category = self.tabs.tabText(self.tabs.currentIndex())
        editor = self.editors[category]
        editor.setPlainText(record.content)
        locked = record.review_status == ReviewStatus.LOCKED
        editor.setReadOnly(locked or not record.editable)
        widgets = self.field_widgets.get(category, {})
        for field in record.fields:
            widget = widgets.get(field.key)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(field.value)
                widget.setEnabled(not locked)
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(field.value)
                widget.setReadOnly(locked)
            elif isinstance(widget, QLineEdit):
                widget.setText(field.value)
                widget.setReadOnly(locked)
        source = record.source_chapter_id or "无章节来源"
        source_revision = (
            str(record.source_revision) if record.source_revision is not None else "未知"
        )
        self.metadata_label.setText(
            f"来源：{record.source_type} / {source} / 修订 {source_revision}　"
            f"权限：{record.authority.value}　审查：{record.review_status.value}　"
            f"状态：{record.status.value}"
        )
        if record.source_type == "SUMMARY_FALLBACK":
            self.metadata_label.setText(
                "⚠ 当前内容只是模型提取失败后的原文定位预览，并非有效压缩摘要。"
                "请返回主界面点击“整理记忆”重试。\n" + self.metadata_label.text()
            )
        busy = self._bulk_promotion_running()
        self.save_button.setEnabled(record.editable and not locked and not busy)
        self.promote_button.setEnabled(record.promotable and not locked and not busy)
        self._refresh_bulk_promotion_button()

    def _save_current(self) -> None:
        record = self._current_record()
        service = self._service
        if record is None or service is None:
            return
        category = self.tabs.tabText(self.tabs.currentIndex())
        try:
            if record.fields:
                values: dict[str, str] = {}
                for field in record.fields:
                    widget = self.field_widgets[category][field.key]
                    if isinstance(widget, QComboBox):
                        values[field.key] = widget.currentText()
                    elif isinstance(widget, QPlainTextEdit):
                        values[field.key] = widget.toPlainText()
                    elif isinstance(widget, QLineEdit):
                        values[field.key] = widget.text()
                updated = service.edit_fields(record.id, values, expected_revision=record.revision)
            else:
                updated = service.edit(
                    record.id,
                    self.editors[category].toPlainText(),
                    expected_revision=record.revision,
                )
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            self.metadata_label.setText(f"保存失败：{error}")
            return
        self._records[updated.id] = updated
        self._refresh_current_record()

    def _promote_current(self) -> None:
        record = self._current_record()
        service = self._service
        if record is None or service is None:
            return
        try:
            promoted = service.promote(record.id, expected_revision=record.revision)
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            self.metadata_label.setText(f"晋升失败：{error}")
            return
        self._records[promoted.id] = promoted
        self._refresh_current_record()

    def _refresh_bulk_promotion_button(self) -> None:
        count = (
            self._service.pending_promotion_count()
            if self._service is not None
            else 0
        )
        self.promote_all_button.setEnabled(count > 0 and not self._bulk_promotion_running())
        self.promote_all_button.setToolTip(
            self._tr("当前共有 {count} 条可晋升候选").format(count=count)
        )

    def _promote_all(self) -> None:
        service = self._service
        if service is None:
            return
        count = service.pending_promotion_count()
        if count <= 0:
            self.metadata_label.setText(self._tr("当前没有可晋升的待审查候选。"))
            self._refresh_bulk_promotion_button()
            return
        answer = QMessageBox.question(
            self,
            self._tr("确认批量晋升"),
            self._tr(
                "将把当前项目中的 {count} 条待审查候选晋升为已审查记忆。\n"
                "编辑框中尚未保存的修改不会自动保存。是否继续？"
            ).format(count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        coordinator = self._promotion_coordinator
        if coordinator is None:
            self.metadata_label.setText(self._tr("批量晋升服务尚未连接。"))
            return
        self._set_bulk_promotion_busy(True)
        self.metadata_label.setText(
            self._tr("正在后台晋升 0 / {count} 条候选……").format(count=count)
        )
        try:
            coordinator.start()
        except RuntimeError as error:
            self._set_bulk_promotion_busy(False)
            self.metadata_label.setText(
                self._tr("批量晋升失败：{message}").format(message=error)
            )

    def _bulk_promotion_progress(self, current: int, total: int, title: str) -> None:
        self.metadata_label.setText(
            self._tr("正在后台晋升 {current} / {total} 条候选……当前：{title}").format(
                current=current,
                total=total,
                title=title,
            )
        )

    def _bulk_promotion_completed(self, value: object) -> None:
        if not isinstance(value, MemoryBulkPromotionResult):
            self._bulk_promotion_failed(self._tr("批量晋升返回了无效结果"))
            return
        result = value
        for promoted in result.promoted:
            self._records[promoted.id] = promoted
        self._set_bulk_promotion_busy(False)
        self._refresh_current_record()
        if result.failures:
            self.metadata_label.setText(
                self._tr(
                    "批量晋升完成：成功 {promoted} 条，失败 {failed} 条。"
                    "失败记录仍保留为待审查候选，可逐条处理。"
                ).format(
                    promoted=len(result.promoted), failed=len(result.failures)
                )
            )
        else:
            self.metadata_label.setText(
                self._tr("批量晋升完成：已成功晋升 {count} 条候选。").format(
                    count=len(result.promoted)
                )
            )
        self._refresh_bulk_promotion_button()

    def _bulk_promotion_failed(self, message: str) -> None:
        self._set_bulk_promotion_busy(False)
        self.metadata_label.setText(
            self._tr("批量晋升失败：{message}").format(message=message)
        )
        self._refresh_bulk_promotion_button()

    def _set_bulk_promotion_busy(self, busy: bool) -> None:
        self.tabs.setEnabled(not busy)
        if busy:
            self.save_button.setEnabled(False)
            self.promote_button.setEnabled(False)
            self.promote_all_button.setEnabled(False)

    def _bulk_promotion_running(self) -> bool:
        return bool(
            self._promotion_coordinator is not None
            and self._promotion_coordinator.is_running
        )

    @staticmethod
    def _tr(text: str) -> str:
        return language_manager().translate(text)
