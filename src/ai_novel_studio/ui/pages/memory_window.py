from __future__ import annotations

from collections import defaultdict

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.memory_workspace_service import (
    MemoryWorkspaceRecord,
    MemoryWorkspaceService,
)
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class MemoryWindow(QMainWindow):
    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service: MemoryWorkspaceService | None = None
        self._records: dict[str, MemoryWorkspaceRecord] = {}
        self.selectors: dict[str, QComboBox] = {}
        self.editors: dict[str, QPlainTextEdit] = {}

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
        actions.addWidget(self.save_button)
        actions.addWidget(self.promote_button)
        actions.addStretch(1)
        note_layout.addLayout(actions)

        layout.addWidget(title)
        layout.addWidget(self.explanation_label)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(note)
        self.setCentralWidget(surface)

    def bind(self, service: MemoryWorkspaceService, before_chapter_id: str) -> None:
        snapshot = service.load(before_chapter_id)
        grouped: dict[str, list[MemoryWorkspaceRecord]] = defaultdict(list)
        for record in snapshot.records:
            grouped[record.category].append(record)
        self._service = service
        self._records = {record.id: record for record in snapshot.records}
        self.tabs.clear()
        self.selectors.clear()
        self.editors.clear()
        for category, records in grouped.items():
            self._add_record_tab(category, records)
        if not grouped:
            self.metadata_label.setText("该章节边界之前没有可显示的记忆记录。")
            self.save_button.setEnabled(False)
            self.promote_button.setEnabled(False)
            return
        self.tabs.setCurrentIndex(0)
        self._refresh_current_record()

    def _add_demo_tab(self, tab_name: str, text: str) -> None:
        editor = QPlainTextEdit(self.tabs)
        editor.setPlainText(text)
        editor.setAccessibleName(f"编辑{tab_name}")
        self.editors[tab_name] = editor
        self.tabs.addTab(editor, tab_name)

    def _add_record_tab(
        self, category: str, records: list[MemoryWorkspaceRecord]
    ) -> None:
        page = QWidget(self.tabs)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 8, 0, 0)
        selector = QComboBox(page)
        selector.setAccessibleName(f"选择{category}记录")
        for record in records:
            selector.addItem(record.title, record.id)
        editor = QPlainTextEdit(page)
        editor.setAccessibleName(f"编辑{category}")
        page_layout.addWidget(selector)
        page_layout.addWidget(editor, 1)
        self.selectors[category] = selector
        self.editors[category] = editor
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
            return
        category = self.tabs.tabText(self.tabs.currentIndex())
        editor = self.editors[category]
        editor.setPlainText(record.content)
        locked = record.review_status == ReviewStatus.LOCKED
        editor.setReadOnly(locked or not record.editable)
        source = record.source_chapter_id or "无章节来源"
        source_revision = (
            str(record.source_revision) if record.source_revision is not None else "未知"
        )
        self.metadata_label.setText(
            f"来源：{record.source_type} / {source} / 修订 {source_revision}　"
            f"权限：{record.authority.value}　审查：{record.review_status.value}　"
            f"状态：{record.status.value}"
        )
        self.save_button.setEnabled(record.editable and not locked)
        self.promote_button.setEnabled(record.promotable and not locked)

    def _save_current(self) -> None:
        record = self._current_record()
        service = self._service
        if record is None or service is None:
            return
        category = self.tabs.tabText(self.tabs.currentIndex())
        try:
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
