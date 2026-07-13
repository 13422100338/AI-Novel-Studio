from __future__ import annotations

import re
from enum import StrEnum

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QWidget,
)


class Language(StrEnum):
    CHINESE = "zh_CN"
    ENGLISH = "en"


def _settings() -> QSettings:
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "AI Novel Studio",
        "AI Novel Studio",
    )


_EN: dict[str, str] = {
    "设置": "Settings",
    "模型、外观与项目设置": "Model, appearance, and project settings",
    "输入": "Input",
    "输出上限": "Output limit",
    "预计费用": "Estimated cost",
    "记忆": "Memory",
    "未知": "Unknown",
    "未估算": "Not estimated",
    "未加载": "Not loaded",
    "有效": "Active",
    "打开或创建一个小说项目": "Open or create a novel project",
    "可新建项目、打开已有项目，或导入 Markdown/TXT 原稿。": (
        "Create a project, open an existing one, or import a Markdown/TXT manuscript."
    ),
    "项目打开后，章节树、正文编辑器和剧情商讨 Agent 会读取同一个项目运行时。": (
        "After opening a project, the chapter tree, manuscript editor, and plot "
        "assistant share the same project runtime."
    ),
    "新建项目": "New project",
    "打开项目": "Open project",
    "导入稿件": "Import manuscript",
    "章节管理": "Chapter management",
    "当前人物状态": "Current character state",
    "项目工作台": "Project workspace",
    "＋ 新章": "+ Chapter",
    "＋ 新卷": "+ Volume",
    "重命名": "Rename",
    "删除": "Delete",
    "新增人物": "Add character",
    "应用修改": "Apply changes",
    "删除人物": "Delete character",
    "当前动机": "Current motivation",
    "心理状态": "Psychological state",
    "当前目标": "Current goal",
    "人物关系": "Relationships",
    "最近活动": "Recent activity",
    "记忆库": "Memory library",
    "整理记忆": "Build memory",
    "取消整理": "Cancel build",
    "文风规则": "Style rules",
    "审校工作台": "Review workspace",
    "请选择人物，或点击“新增人物”。": "Select a character or click Add character.",
    "应用人物状态修改": "Apply character-state changes",
    "删除当前人物": "Delete selected character",
    "打开长篇记忆库": "Open long-form memory library",
    "整理导入稿件并构建记忆库": "Analyze manuscript and build memory",
    "打开文风规则": "Open style rules",
    "打开审校工作台": "Open review workspace",
    "折叠或展开章节管理": "Collapse or expand chapter management",
    "折叠或展开当前人物状态": "Collapse or expand current character state",
    "折叠或展开项目工作台": "Collapse or expand project workspace",
    "目标字数": "Target words",
    "字号": "Font size",
    "档位": "Mode",
    "标准": "Standard",
    "快速": "Quick",
    "严格": "Strict",
    "情节点 / Brief": "Plot beats / Brief",
    "保存章节": "Save chapter",
    "AI 参考内容": "AI context",
    "审校": "Review",
    "恢复草稿": "Recover draft",
    "取消": "Cancel",
    "生成正文": "Generate prose",
    "换一个草稿": "Regenerate draft",
    "当前章要求": "Current chapter requirements",
    "展开要求": "Expand requirements",
    "折叠要求": "Collapse requirements",
    "锁定要求": "Lock requirements",
    "解除锁定": "Unlock requirements",
    "可编辑": "Editable",
    "已锁定": "Locked",
    "已折叠 · 可展开编辑": "Collapsed · Expand to edit",
    "AI 草稿预览": "AI draft preview",
    "采用草稿": "Accept draft",
    "采用部分草稿": "Accept partial draft",
    "放弃草稿": "Discard draft",
    "生成后将在正文框内预览": "The generated draft will be previewed in the manuscript editor",
    "未打开章节": "No chapter open",
    "打开或导入项目后显示当前章节": "Open or import a project to display a chapter",
    "剧情商讨": "Plot discussion",
    "剧情模型 · 尚未连接": "Plot model · Not connected",
    "剧情模型 · 已连接": "Plot model · Connected",
    "剧情模型 · 正在回复…": "Plot model · Responding…",
    "剧情模型 · 调用失败": "Plot model · Request failed",
    "工具 ▾": "Tools ▾",
    "工具 ▴": "Tools ▴",
    "工具检索": "Tool retrieval",
    "证据追踪": "Evidence trace",
    "历史摘要": "History summary",
    "独立窗口": "Detached window",
    "生成当前章要求": "Generate chapter requirements",
    "正在整理…": "Preparing…",
    "发送": "Send",
    "和剧情模型讨论人物动机、转折、伏笔……": (
        "Discuss motivation, turns, foreshadowing, and structure with the plot model…"
    ),
    "设置 · AI Novel Studio": "Settings · AI Novel Studio",
    "模型连接": "Model connections",
    "外观": "Appearance",
    "创作默认值": "Writing defaults",
    "保存设置": "Save settings",
    "关闭": "Close",
    "API 连接": "API connections",
    "连接": "Connection",
    "名称": "Name",
    "模型列表地址": "Model list URL",
    "接口类型": "API type",
    "超时": "Timeout",
    "已发现模型": "Discovered models",
    "新增": "Add",
    "连接并获取模型": "Connect and fetch models",
    "探测所选模型能力": "Probe selected model capabilities",
    "能力：尚未探测": "Capabilities: not probed",
    "新连接": "New connection",
    "留空则使用 Base URL /models": "Leave blank to use Base URL /models",
    "留空则继续使用系统凭据中已保存的 Key": (
        "Leave blank to keep the key stored in system credentials"
    ),
    "已安全保存；留空表示保持不变": "Stored securely; leave blank to keep unchanged",
    "未配置": "Not configured",
    "未配置 / 继承对应默认模型": "Not configured / inherit the corresponding default",
    "默认模型负责同类基础任务；“可覆盖”可为某项高级任务指定专用模型，"
    "未指定时继承对应默认模型。程序不会在失败后自动改用其他付费模型。": (
        "Default models handle related basic tasks. Overrides assign a dedicated model to an "
        "advanced task; otherwise it inherits the corresponding default. The app never switches "
        "to another paid model silently after a failure."
    ),
    "默认模型与任务覆盖": "Default models and task overrides",
    "剧情商讨（默认）": "Plot discussion (default)",
    "正文创作（默认）": "Prose writing (default)",
    "Brief 整理（可覆盖）": "Brief preparation (override)",
    "工具检索（可覆盖）": "Tool retrieval (override)",
    "文风审校（可覆盖）": "Style review (override)",
    "模型设置尚未保存": "Model settings have not been saved",
    "模型设置已保存": "Settings saved",
    "主题": "Theme",
    "信息密度": "Information density",
    "语言": "Language",
    "浅色（当前）": "Light (current)",
    "跟随系统": "Follow system",
    "适中": "Comfortable",
    "紧凑": "Compact",
    "宽松": "Spacious",
    "简体中文": "Simplified Chinese",
    " 秒": " sec",
    "默认目标字数": "Default target words",
    "默认输出 Token 上限": "Default output token limit",
    "记忆库 · AI Novel Studio": "Memory Library · AI Novel Studio",
    "长篇记忆库": "Long-form memory library",
    "这里展示 AI 生成前可检索的压缩前文、人物与读者知识边界、正典和叙事线索。"
    "模型提取内容只会成为待审查候选；只有用户明确晋升后才可成为当前记忆。": (
        "This library contains searchable compressed history, character and reader knowledge, "
        "canon, and narrative clues. Model extractions remain review candidates until the "
        "author explicitly approves them."
    ),
    "离线演示数据：尚未绑定项目记忆服务。": (
        "Offline demonstration data · No project memory service is connected."
    ),
    "压缩前文": "Compressed history",
    "人物状态": "Character state",
    "人物知识": "Character knowledge",
    "读者知识": "Reader knowledge",
    "正典": "Canon",
    "叙事线索": "Narrative clues",
    "过期依赖": "Stale dependencies",
    "设定资料整理": "Setting documents",
    "保存人工修改": "Save manual edits",
    "晋升为已审查": "Approve candidate",
    "资料标题": "Document title",
    "资料类型": "Document type",
    "混合设定": "Mixed settings",
    "世界观": "Worldbuilding",
    "人物设定": "Character profiles",
    "剧情大纲": "Plot outline",
    "文风资料": "Style material",
    "保存原始资料": "Save source document",
    "AI 整理为待审查候选": "Extract review candidates",
    "尚未保存": "Not saved",
    "文风规则 · AI Novel Studio": "Style Rules · AI Novel Studio",
    "分层文风系统": "Layered style system",
    "人工规则和未锁定样章可编辑；锁定样章作为高权威参考，"
    "生成时按全书、场景、人物和章节范围检索。": (
        "Human rules and unlocked samples are editable. Locked samples are high-authority "
        "references retrieved by book, scene, character, or chapter scope."
    ),
    "分层规则": "Layered rules",
    "人工样章": "Human samples",
    "AI 候选": "AI candidates",
    "保存规则": "Save rule",
    "新增规则": "Add rule",
    "删除规则": "Delete rule",
    "保存样章": "Save sample",
    "新增样章": "Add sample",
    "删除样章": "Delete sample",
    "锁定样章": "Lock sample",
    "层级": "Level",
    "规则": "Rule",
    "范围 / 权威": "Scope / authority",
    "全书": "Book",
    "场景 / 类型": "Scene / genre",
    "人物": "Character",
    "章节": "Chapter",
    "范围 ID": "Scope ID",
    "规则类型": "Rule type",
    "规则正文": "Rule text",
    "例如：叙述节奏、人物语言、禁用表达": (
        "For example: narrative pace, character voice, prohibited expressions"
    ),
    "新建规则": "New rule",
    "审校工作台 · AI Novel Studio": "Review Workspace · AI Novel Studio",
    "独立审校工作台": "Independent review workspace",
    "确定性检查": "Deterministic checks",
    "模型审校": "Model review",
    "运行确定性检查": "Run deterministic checks",
    "运行模型审校": "Run model review",
    "重新运行确定性检查": "Run deterministic checks again",
    "重新运行模型审校": "Run model review again",
    "来源": "Source",
    "问题": "Issue",
    "证据": "Evidence",
    "状态": "Status",
    "生成局部修复建议": "Generate bounded repair",
    "确认采用": "Accept repair",
    "拒绝建议": "Reject proposal",
    "标记误报": "Mark false positive",
    "忽略问题": "Ignore issue",
    "建议替换文本": "Proposed replacement",
    "局部差异": "Local diff",
    "对话轨迹": "Conversation trace",
    "工具调用": "Tool calls",
    "角色": "Role",
    "内容": "Content",
    "工具": "Tool",
    "结果字符": "Result characters",
    "省略/风险": "Omissions / risk",
    "章节 Brief 审查": "Chapter Brief Review",
    "保存草稿": "Save draft",
    "冻结 Brief": "Freeze Brief",
    "解除冻结": "Unfreeze",
    "重新编译": "Recompile",
    "剧情商讨 · AI Novel Studio": "Plot Discussion · AI Novel Studio",
    "未打开项目": "No project open",
    "请新建或打开一个小说项目": "Create or open a novel project",
    "雾港来信": "Letters from Mist Harbor",
    "第一卷 · 潮声": "Volume I · Tides",
    "雪夜来客": "Visitor on a Snowy Night",
    "没有寄出的信": "The Unsent Letter",
    "旧城钟声": "Bells of the Old City",
    "第 1 章": "Chapter 1",
    "第 2 章": "Chapter 2",
    "第 3 章": "Chapter 3",
    "已确认": "Confirmed",
    "编辑中": "Editing",
    "待创作": "Not started",
}


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^约 (.+)$"), r"Approx. \1"),
    (re.compile(r"^缓存 (\d+)$"), r"Cached \1"),
    (re.compile(r"^([\d,]+) 字$"), r"\1 words"),
    (re.compile(r"^([\d,]+) 字 · 修订 (\d+)$"), r"\1 words · Revision \2"),
    (re.compile(r"^第 (\d+) 章$"), r"Chapter \1"),
    (re.compile(r"^[−-]\s*(.+)$"), r"− \1"),
    (re.compile(r"^\+\s*(.+)$"), r"+ \1"),
    (re.compile(r"^错误：(.+)$"), r"Error: \1"),
    (re.compile(r"^保存失败：(.+)$"), r"Save failed: \1"),
    (re.compile(r"^整理失败：(.+)$"), r"Extraction failed: \1"),
)


def _to_english(text: str) -> str:
    translated = _EN.get(text)
    if translated is not None:
        return translated
    collapsible = re.match(r"^([−＋+-])\s+(.*)$", text)
    if collapsible:
        return f"{collapsible.group(1)}  {_to_english(collapsible.group(2))}"
    for pattern, replacement in _PATTERNS:
        if pattern.match(text):
            result = pattern.sub(replacement, text)
            return _EN.get(result, result)
    return text


class LocalizationManager(QObject):
    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        settings = _settings()
        self._has_saved_language = settings.contains("ui/language")
        value = settings.value("ui/language", Language.CHINESE.value)
        try:
            self._language = Language(str(value))
        except ValueError:
            self._language = Language.CHINESE
        self._installed = False
        self._applying = False

    @property
    def language(self) -> Language:
        return self._language

    @property
    def has_saved_language(self) -> bool:
        return self._has_saved_language

    def install(self, app: QApplication) -> None:
        if not self._installed:
            app.installEventFilter(self)
            self._installed = True
        self.apply_all()

    def set_language(self, language: str | Language) -> None:
        selected = Language(language)
        self._language = selected
        settings = _settings()
        settings.setValue("ui/language", selected.value)
        settings.sync()
        self._has_saved_language = True
        self.apply_all()
        self.language_changed.emit(selected.value)

    def translate(self, text: str) -> str:
        if self._language == Language.CHINESE or not text:
            return text
        return _to_english(text)

    def apply_all(self) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        for widget in app.topLevelWidgets():
            self.apply(widget)

    def apply(self, root: QWidget) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            self._translate_widget(root)
            for widget in root.findChildren(QWidget):
                self._translate_widget(widget)
        finally:
            self._applying = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in {QEvent.Type.Show, QEvent.Type.LayoutRequest} and isinstance(
            watched, QWidget
        ):
            self.apply(watched)
        return False

    def _translate_widget(self, widget: QWidget) -> None:
        self._translate_value(widget, "windowTitle", widget.windowTitle, widget.setWindowTitle)
        self._translate_value(widget, "toolTip", widget.toolTip, widget.setToolTip)
        self._translate_value(
            widget, "accessibleName", widget.accessibleName, widget.setAccessibleName
        )
        if isinstance(widget, (QLabel, QAbstractButton)):
            self._translate_value(widget, "text", widget.text, widget.setText)
        if isinstance(widget, QGroupBox):
            self._translate_value(widget, "title", widget.title, widget.setTitle)
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            self._translate_value(
                widget,
                "placeholderText",
                widget.placeholderText,
                widget.setPlaceholderText,
            )
        if isinstance(widget, QSpinBox):
            self._translate_value(widget, "suffix", widget.suffix, widget.setSuffix)
        if isinstance(widget, QComboBox):
            self._translate_combo(widget)
        if isinstance(widget, QTabWidget):
            self._translate_tabs(widget)
        if isinstance(widget, QTableWidget):
            self._translate_table_headers(widget)

    def _translate_value(self, widget: QWidget, key: str, getter: object, setter: object) -> None:
        if not callable(getter) or not callable(setter):
            return
        current = str(getter())
        property_name = f"i18nSource_{key}"
        stored = widget.property(property_name)
        source = str(stored) if isinstance(stored, str) else current
        translated_source = _to_english(source)
        if current not in {source, translated_source}:
            source = current
            widget.setProperty(property_name, source)
        elif stored is None:
            widget.setProperty(property_name, source)
        setter(source if self._language == Language.CHINESE else self.translate(source))

    def _translate_combo(self, combo: QComboBox) -> None:
        sources = getattr(combo, "_i18n_item_sources", {})
        for index in range(combo.count()):
            current = combo.itemText(index)
            source = sources.get(index, current)
            translated_source = _to_english(source)
            if current not in {source, translated_source}:
                source = current
            sources[index] = source
            combo.setItemText(
                index, source if self._language == Language.CHINESE else self.translate(source)
            )
        combo.__dict__["_i18n_item_sources"] = sources

    def _translate_tabs(self, tabs: QTabWidget) -> None:
        sources = getattr(tabs, "_i18n_tab_sources", {})
        for index in range(tabs.count()):
            current = tabs.tabText(index)
            source = sources.get(index, current)
            translated_source = _to_english(source)
            if current not in {source, translated_source}:
                source = current
            sources[index] = source
            tabs.setTabText(
                index, source if self._language == Language.CHINESE else self.translate(source)
            )
        tabs.__dict__["_i18n_tab_sources"] = sources

    def _translate_table_headers(self, table: QTableWidget) -> None:
        role = int(Qt.ItemDataRole.UserRole) + 91
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            if item is None:
                continue
            current = item.text()
            stored = item.data(role)
            source = str(stored) if isinstance(stored, str) else current
            if current not in {source, _to_english(source)}:
                source = current
            item.setData(role, source)
            item.setText(
                source if self._language == Language.CHINESE else self.translate(source)
            )


_manager: LocalizationManager | None = None


def language_manager() -> LocalizationManager:
    global _manager
    if _manager is None:
        _manager = LocalizationManager()
    return _manager
