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
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import DemoCharacter, WorkspaceDemoData
from ai_novel_studio.ui.widgets.collapsible_section import CollapsibleSection


class ChapterSidebar(QFrame):
    chapter_selected = Signal(str)

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
        for index, label in enumerate(("＋ 新章", "＋ 新卷", "重命名", "删除")):
            button = QPushButton(label, content)
            button.setAccessibleName(label.replace("＋ ", ""))
            chapter_actions.addWidget(button, index // 2, index % 2)
        content_layout.addLayout(chapter_actions)

        character_content = self._build_character_editor(content)
        self.character_section = CollapsibleSection("当前人物状态", character_content, content)
        content_layout.addWidget(self.character_section)
        content_layout.addStretch(1)

        self.scroll_area.setWidget(content)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.scroll_area)

        self.chapter_tree.currentItemChanged.connect(self._emit_chapter_selection)
        self.character_combo.currentIndexChanged.connect(self._load_selected_character)
        self._load_selected_character()

    @staticmethod
    def _character_record(character: DemoCharacter) -> dict[str, str]:
        return {
            "name": character.name,
            "psychology": character.psychology,
            "motivation": character.motivation,
            "goal": character.current_goal,
            "recent": character.recent_activity,
        }

    def _build_chapter_tree(self, data: WorkspaceDemoData) -> QTreeWidget:
        tree = QTreeWidget(self)
        tree.setObjectName("chapterTree")
        tree.setHeaderHidden(True)
        tree.setMinimumHeight(210)
        tree.setIndentation(14)
        for volume in data.volumes:
            volume_item = QTreeWidgetItem([volume.title])
            volume_item.setExpanded(True)
            tree.addTopLevelItem(volume_item)
            for chapter in volume.chapters:
                item = QTreeWidgetItem(
                    [
                        f"{chapter.number}  {chapter.title}\n"
                        f"{chapter.word_count:,} 字 · {chapter.status}"
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, chapter.id)
                volume_item.addChild(item)
        return tree

    def _build_character_editor(self, parent: QWidget) -> QWidget:
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.character_combo = QComboBox(container)
        self.character_combo.setAccessibleName("选择人物")
        for character_id, record in self._characters.items():
            self.character_combo.addItem(record["name"], character_id)
        layout.addWidget(self.character_combo)

        self.psychology_edit = self._labeled_editor(layout, container, "心理状态")
        self.motivation_edit = self._labeled_editor(layout, container, "当前动机")
        self.goal_edit = self._labeled_editor(layout, container, "当前目标")
        self.recent_edit = self._labeled_editor(layout, container, "最近活动")

        action_layout = QGridLayout()
        apply_button = QPushButton("应用修改", container)
        apply_button.setAccessibleName("应用人物状态修改")
        apply_button.clicked.connect(self.apply_character_edit)
        delete_button = QPushButton("删除人物", container)
        delete_button.setAccessibleName("删除当前人物")
        delete_button.clicked.connect(self.delete_current_character)
        action_layout.addWidget(apply_button, 0, 0)
        action_layout.addWidget(delete_button, 0, 1)
        layout.addLayout(action_layout)
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
        chapter_id = current.data(0, Qt.ItemDataRole.UserRole)
        if chapter_id:
            self.chapter_selected.emit(str(chapter_id))

    def _load_selected_character(self) -> None:
        character_id = self.character_combo.currentData()
        if not character_id or character_id not in self._characters:
            return
        record = self._characters[character_id]
        self.psychology_edit.setPlainText(record["psychology"])
        self.motivation_edit.setPlainText(record["motivation"])
        self.goal_edit.setPlainText(record["goal"])
        self.recent_edit.setPlainText(record["recent"])

    def apply_character_edit(self) -> None:
        character_id = self.character_combo.currentData()
        if not character_id or character_id not in self._characters:
            return
        self._characters[character_id].update(
            psychology=self.psychology_edit.toPlainText(),
            motivation=self.motivation_edit.toPlainText(),
            goal=self.goal_edit.toPlainText(),
            recent=self.recent_edit.toPlainText(),
        )

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
