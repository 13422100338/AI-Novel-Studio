from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import DemoCharacter, WorkspaceDemoData
from ai_novel_studio.ui.widgets.collapsible_section import CollapsibleSection


class ChapterSidebar(QFrame):
    chapter_selected = Signal(str)
    memory_requested = Signal()
    memory_build_requested = Signal()
    style_requested = Signal()
    audit_requested = Signal()
    character_edit_applied = Signal(object)
    chapter_create_requested = Signal(str)
    volume_create_requested = Signal()
    rename_requested = Signal(str, str)
    delete_requested = Signal(str, str)

    _ITEM_ID_ROLE = int(Qt.ItemDataRole.UserRole)
    _ITEM_KIND_ROLE = _ITEM_ID_ROLE + 1

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapterSidebar")
        self.setMinimumWidth(250)
        self._characters: dict[str, dict[str, str]] = {
            character.id: self._character_record(character) for character in data.characters
        }

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("chapterSidebarScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget(self.scroll_area)
        content.setObjectName("appSurface")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 10, 8, 12)
        content_layout.setSpacing(10)

        self.chapter_tree = self._build_chapter_tree(data)
        self.chapter_section = CollapsibleSection("章节管理", self.chapter_tree, content)
        content_layout.addWidget(self.chapter_section)

        chapter_actions = QGridLayout()
        self.new_chapter_button = QPushButton("＋ 新章", content)
        self.new_volume_button = QPushButton("＋ 新卷", content)
        self.rename_button = QPushButton("重命名", content)
        self.delete_button = QPushButton("删除", content)
        for index, button in enumerate(
            (
                self.new_chapter_button,
                self.new_volume_button,
                self.rename_button,
                self.delete_button,
            )
        ):
            button.setAccessibleName(button.text().replace("＋ ", ""))
            chapter_actions.addWidget(button, index // 2, index % 2)
        content_layout.addLayout(chapter_actions)

        character_content = self._build_character_editor(content)
        self.character_section = CollapsibleSection("当前人物状态", character_content, content)
        content_layout.addWidget(self.character_section)

        workspace_content = QWidget(content)
        workspace_layout = QGridLayout(workspace_content)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.memory_button = QPushButton("记忆库", workspace_content)
        self.memory_button.setAccessibleName("打开长篇记忆库")
        self.memory_build_button = QPushButton("整理记忆", workspace_content)
        self.memory_build_button.setAccessibleName("整理导入稿件并构建记忆库")
        self.style_button = QPushButton("文风规则", workspace_content)
        self.style_button.setAccessibleName("打开文风规则")
        self.audit_button = QPushButton("审校工作台", workspace_content)
        self.audit_button.setAccessibleName("打开审校工作台")
        workspace_layout.addWidget(self.memory_button, 0, 0)
        workspace_layout.addWidget(self.memory_build_button, 0, 1)
        workspace_layout.addWidget(self.style_button, 1, 0)
        workspace_layout.addWidget(self.audit_button, 1, 1)
        self.workspace_section = CollapsibleSection("项目工作台", workspace_content, content)
        content_layout.addWidget(self.workspace_section)
        content_layout.addStretch(1)

        self.scroll_area.setWidget(content)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.scroll_area)

        self.chapter_tree.currentItemChanged.connect(self._emit_chapter_selection)
        self.character_combo.currentIndexChanged.connect(self._load_selected_character)
        self.memory_button.clicked.connect(self.memory_requested)
        self.memory_build_button.clicked.connect(self.memory_build_requested)
        self.style_button.clicked.connect(self.style_requested)
        self.audit_button.clicked.connect(self.audit_requested)
        self.new_chapter_button.clicked.connect(self._request_new_chapter)
        self.new_volume_button.clicked.connect(self.volume_create_requested)
        self.rename_button.clicked.connect(self._request_rename)
        self.delete_button.clicked.connect(self._request_delete)
        self._load_selected_character()

    def set_memory_build_running(self, running: bool) -> None:
        self.memory_build_button.setText("取消整理" if running else "整理记忆")
        self.memory_build_button.setAccessibleName(
            "请求取消记忆整理" if running else "整理导入稿件并构建记忆库"
        )

    @staticmethod
    def _character_record(character: DemoCharacter) -> dict[str, str]:
        return {
            "name": character.name,
            "psychology": character.psychology,
            "motivation": character.motivation,
            "goal": character.current_goal,
            "relationships": "",
            "recent": character.recent_activity,
        }

    def _build_chapter_tree(self, data: WorkspaceDemoData) -> QTreeWidget:
        tree = QTreeWidget(self)
        tree.setObjectName("chapterTree")
        tree.setHeaderHidden(True)
        tree.setMinimumHeight(210)
        tree.setIndentation(14)
        self._populate_demo_tree(tree, data)
        return tree

    def _populate_demo_tree(self, tree: QTreeWidget, data: WorkspaceDemoData) -> None:
        tree.clear()
        for volume in data.volumes:
            volume_item = QTreeWidgetItem([volume.title])
            volume_item.setData(0, self._ITEM_ID_ROLE, volume.id)
            volume_item.setData(0, self._ITEM_KIND_ROLE, "volume")
            tree.addTopLevelItem(volume_item)
            for chapter in volume.chapters:
                item = QTreeWidgetItem(
                    [
                        f"{chapter.number}  {chapter.title}\n"
                        f"{chapter.word_count:,} 字 · {chapter.status}"
                    ]
                )
                item.setData(0, self._ITEM_ID_ROLE, chapter.id)
                item.setData(0, self._ITEM_KIND_ROLE, "chapter")
                volume_item.addChild(item)
            volume_item.setExpanded(True)

    def apply_volume_tree(self, volumes: Iterable[Any]) -> None:
        self.chapter_tree.clear()
        for volume in volumes:
            volume_item = QTreeWidgetItem([str(volume.title)])
            volume_item.setData(0, self._ITEM_ID_ROLE, str(volume.id))
            volume_item.setData(0, self._ITEM_KIND_ROLE, "volume")
            self.chapter_tree.addTopLevelItem(volume_item)
            for chapter in volume.chapters:
                item = QTreeWidgetItem(
                    [
                        f"{chapter.declared_number}  {chapter.title}\n"
                        f"{chapter.word_count:,} 字 · 修订 {chapter.revision}"
                    ]
                )
                item.setData(0, self._ITEM_ID_ROLE, chapter.id)
                item.setData(0, self._ITEM_KIND_ROLE, "chapter")
                volume_item.addChild(item)
            volume_item.setExpanded(True)

    def _build_character_editor(self, parent: QWidget) -> QWidget:
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.character_combo = QComboBox(container)
        self.character_combo.setAccessibleName("选择人物")
        self.character_combo.setEditable(True)
        for character_id, record in self._characters.items():
            self.character_combo.addItem(record["name"], character_id)
        layout.addWidget(self.character_combo)

        self.psychology_edit = self._labeled_editor(layout, container, "心理状态")
        self.motivation_edit = self._labeled_editor(layout, container, "当前动机")
        self.goal_edit = self._labeled_editor(layout, container, "当前目标")
        self.relationships_edit = self._labeled_editor(layout, container, "人物关系")
        self.recent_edit = self._labeled_editor(layout, container, "最近活动")

        action_layout = QGridLayout()
        new_button = QPushButton("新增人物", container)
        new_button.setAccessibleName("新增人物")
        new_button.clicked.connect(self.begin_new_character)
        apply_button = QPushButton("应用修改", container)
        apply_button.setAccessibleName("应用人物状态修改")
        apply_button.clicked.connect(self.apply_character_edit)
        delete_button = QPushButton("删除人物", container)
        delete_button.setAccessibleName("删除当前人物")
        delete_button.clicked.connect(self.delete_current_character)
        action_layout.addWidget(new_button, 0, 0)
        action_layout.addWidget(apply_button, 0, 1)
        action_layout.addWidget(delete_button, 1, 0, 1, 2)
        layout.addLayout(action_layout)
        self.character_feedback_label = QLabel("请选择人物，或点击“新增人物”。", container)
        self.character_feedback_label.setObjectName("mutedLabel")
        self.character_feedback_label.setWordWrap(True)
        layout.addWidget(self.character_feedback_label)
        return container

    @staticmethod
    def _labeled_editor(layout: QVBoxLayout, parent: QWidget, label: str) -> QTextEdit:
        title = QLabel(label, parent)
        title.setObjectName("sectionEyebrow")
        editor = QTextEdit(parent)
        editor.setAcceptRichText(False)
        editor.setFixedHeight(62)
        editor.setAccessibleName(label)
        layout.addWidget(title)
        layout.addWidget(editor)
        return editor

    def _emit_chapter_selection(self, current: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        chapter_id = current.data(0, self._ITEM_ID_ROLE)
        if chapter_id and current.data(0, self._ITEM_KIND_ROLE) == "chapter":
            self.chapter_selected.emit(str(chapter_id))

    def selected_target(self) -> tuple[str, str] | None:
        item = self.chapter_tree.currentItem()
        if item is None:
            return None
        item_id = item.data(0, self._ITEM_ID_ROLE)
        kind = item.data(0, self._ITEM_KIND_ROLE)
        if not item_id or kind not in {"volume", "chapter"}:
            return None
        return str(kind), str(item_id)

    def _request_new_chapter(self) -> None:
        item = self.chapter_tree.currentItem()
        if item is None and self.chapter_tree.topLevelItemCount():
            item = self.chapter_tree.topLevelItem(0)
        if item is None:
            return
        kind = item.data(0, self._ITEM_KIND_ROLE)
        volume_item = item.parent() if kind == "chapter" else item
        if volume_item is None:
            return
        volume_id = volume_item.data(0, self._ITEM_ID_ROLE)
        if volume_id:
            self.chapter_create_requested.emit(str(volume_id))

    def _request_rename(self) -> None:
        target = self.selected_target()
        if target is not None:
            self.rename_requested.emit(*target)

    def _request_delete(self) -> None:
        target = self.selected_target()
        if target is not None:
            self.delete_requested.emit(*target)

    def select_chapter(self, chapter_id: str) -> bool:
        iterator = QTreeWidgetItemIterator(self.chapter_tree)
        while iterator.value() is not None:
            item = iterator.value()
            if (
                item.data(0, self._ITEM_KIND_ROLE) == "chapter"
                and str(item.data(0, self._ITEM_ID_ROLE)) == chapter_id
            ):
                self.chapter_tree.setCurrentItem(item)
                return True
            iterator += 1
        return False

    def _load_selected_character(self) -> None:
        character_id = self.character_combo.currentData()
        if not character_id or character_id not in self._characters:
            self._clear_character_fields()
            return
        record = self._characters[character_id]
        self.character_combo.setCurrentText(record["name"])
        self.psychology_edit.setPlainText(record["psychology"])
        self.motivation_edit.setPlainText(record["motivation"])
        self.goal_edit.setPlainText(record["goal"])
        self.relationships_edit.setPlainText(record.get("relationships", ""))
        self.recent_edit.setPlainText(record["recent"])

    def _clear_character_fields(self) -> None:
        self.psychology_edit.clear()
        self.motivation_edit.clear()
        self.goal_edit.clear()
        self.relationships_edit.clear()
        self.recent_edit.clear()

    def apply_character_records(self, records: Iterable[Any]) -> None:
        current_id = self.character_combo.currentData()
        self._characters = {
            str(record.id): {
                "name": str(record.name),
                "psychology": str(record.psychology),
                "motivation": str(record.motivation),
                "goal": str(record.goal),
                "relationships": str(getattr(record, "relationships", "")),
                "recent": str(record.recent),
            }
            for record in records
        }
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        selected_index = -1
        for index, (character_id, record) in enumerate(self._characters.items()):
            self.character_combo.addItem(record["name"], character_id)
            if character_id == current_id:
                selected_index = index
        if selected_index >= 0:
            self.character_combo.setCurrentIndex(selected_index)
        self.character_combo.blockSignals(False)
        self._load_selected_character()
        if self._characters:
            self.character_feedback_label.setText(
                f"已加载 {len(self._characters)} 个人物；修改后请点击“应用修改”。"
            )
        else:
            self.character_feedback_label.setText(
                "当前项目还没有人物状态。可先整理记忆，或手动新增人物。"
            )

    def begin_new_character(self, name: str = "新人物") -> None:
        display_name = name.strip() if isinstance(name, str) else "新人物"
        if not display_name:
            display_name = "新人物"
        self.character_combo.addItem(display_name, "")
        self.character_combo.setCurrentIndex(self.character_combo.count() - 1)
        self.character_combo.setCurrentText(display_name)
        self._clear_character_fields()

    def apply_character_edit(self) -> None:
        character_id = self.character_combo.currentData()
        name = self.character_combo.currentText().strip()
        if not name and character_id in self._characters:
            name = self._characters[character_id]["name"]
        if not name:
            name = "新人物"
            self.character_combo.setCurrentText(name)
        if not character_id or character_id not in self._characters:
            character_id = f"local-{uuid4().hex}"
            current_index = self.character_combo.currentIndex()
            if current_index < 0:
                self.character_combo.addItem(name, character_id)
                self.character_combo.setCurrentIndex(self.character_combo.count() - 1)
            else:
                self.character_combo.setItemText(current_index, name)
                self.character_combo.setItemData(current_index, character_id)
            self._characters[character_id] = {
                "name": name,
                "psychology": "",
                "motivation": "",
                "goal": "",
                "relationships": "",
                "recent": "",
            }
        self._characters[character_id].update(
            name=name,
            psychology=self.psychology_edit.toPlainText(),
            motivation=self.motivation_edit.toPlainText(),
            goal=self.goal_edit.toPlainText(),
            relationships=self.relationships_edit.toPlainText(),
            recent=self.recent_edit.toPlainText(),
        )
        self.character_feedback_label.setText("正在保存人物状态……")
        self.character_edit_applied.emit(
            {
                "id": character_id,
                "name": name,
                "psychology": self.psychology_edit.toPlainText(),
                "motivation": self.motivation_edit.toPlainText(),
                "goal": self.goal_edit.toPlainText(),
                "relationships": self.relationships_edit.toPlainText(),
                "recent": self.recent_edit.toPlainText(),
            }
        )

    def set_character_feedback(self, message: str) -> None:
        self.character_feedback_label.setText(message)

    def delete_current_character(self) -> None:
        index = self.character_combo.currentIndex()
        character_id = self.character_combo.currentData()
        if index < 0 or not character_id:
            return
        self._characters.pop(character_id, None)
        self.character_combo.removeItem(index)
        self._load_selected_character()

    def character_status(self, character_id: str) -> dict[str, str]:
        return dict(self._characters[character_id])
