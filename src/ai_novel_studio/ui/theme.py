def application_stylesheet(*, theme: str = "light", density: str = "normal") -> str:
    stylesheet = """
    * {
        font-family: "Segoe UI", "Microsoft YaHei UI";
        font-size: 13px;
        color: #202124;
    }
    QMainWindow, QDialog, QWidget#appSurface {
        background: #f6f7f8;
    }
    QFrame#topBar, QFrame#panelSurface, QFrame#cardSurface,
    QFrame#chapterSidebar, QFrame#manuscriptPanel, QFrame#plotChatPanel {
        background: #ffffff;
        border: 1px solid #e4e6e8;
        border-radius: 12px;
    }
    QLabel#mutedLabel { color: #6f7378; }
    QLabel#sectionEyebrow {
        color: #74787e;
        font-size: 11px;
        font-weight: 600;
    }
    QLabel#panelTitle {
        font-size: 16px;
        font-weight: 650;
    }
    QToolButton#briefHelpButton {
        background: transparent;
        color: #6f7378;
        border: 1px solid #8f9399;
        border-radius: 8px;
        padding: 0;
        font-size: 11px;
        font-weight: 700;
    }
    QToolButton#briefHelpButton:hover {
        background: #e9eaec;
        color: #202124;
        border-color: #565a60;
    }
    QPushButton, QToolButton {
        background: #f2f3f4;
        border: 1px solid #e0e2e4;
        border-radius: 8px;
        padding: 6px 10px;
    }
    QPushButton:hover, QToolButton:hover { background: #e9eaec; }
    QPushButton:pressed, QToolButton:pressed { background: #dfe1e3; }
    QPushButton:focus, QToolButton:focus, QLineEdit:focus, QPlainTextEdit:focus,
    QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #565a60;
    }
    QPushButton[buttonRole="primary"] {
        background: #242629;
        color: #ffffff;
        border-color: #242629;
        font-weight: 600;
    }
    QPushButton[buttonRole="primary"]:hover { background: #36393d; }
    QPushButton:disabled { color: #a7aaae; background: #f5f5f5; }
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QListWidget,
    QTreeWidget, QTableWidget, QTabWidget::pane {
        background: #ffffff;
        border: 1px solid #dedfe1;
        border-radius: 8px;
        selection-background-color: #dedfe1;
        selection-color: #111111;
    }
    QTreeWidget#chapterTree {
        background: transparent;
        border: none;
        padding: 2px;
        outline: none;
    }
    QTreeWidget#chapterTree::item:has-children {
        background: transparent;
        border: none;
        padding: 5px 3px;
        font-weight: 600;
    }
    QTreeWidget#chapterTree::item:!has-children {
        background: #eff0f1;
        border: 1px solid #e0e2e4;
        border-radius: 9px;
        padding: 7px 8px;
        margin: 3px 2px;
    }
    QTreeWidget#chapterTree::item:!has-children:hover { background: #e6e7e9; }
    QTreeWidget#chapterTree::item:!has-children:selected {
        background: #d8dade;
        border-color: #c8cbd0;
        color: #111111;
    }
    QLineEdit, QComboBox, QSpinBox { min-height: 30px; padding: 0 8px; }
    QPlainTextEdit, QTextEdit { padding: 8px; }
    QHeaderView::section {
        background: #f2f3f4;
        border: none;
        border-bottom: 1px solid #dfe1e3;
        padding: 7px;
        font-weight: 600;
    }
    QTabBar::tab {
        background: transparent;
        padding: 8px 11px;
        color: #6c7075;
        border-bottom: 2px solid transparent;
    }
    QTabBar::tab:selected { color: #202124; border-bottom-color: #202124; }
    QSplitter::handle { background: #e5e6e8; }
    QSplitter::handle:horizontal { width: 5px; }
    QSplitter::handle:vertical { height: 5px; }
    QSplitter#chapterSectionSplitter::handle:vertical {
        background: #d5d7da;
        border-radius: 3px;
        margin: 1px 34px;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #b8bbc0;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 10px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: #b8bbc0;
        border-radius: 4px;
        min-width: 30px;
    }
    QScrollBar::handle:hover { background: #8f9399; }
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; }
    QFrame[chatRole="assistant"] {
        background: #ffffff;
        border: 1px solid #e2e3e5;
        border-radius: 12px;
    }
    QFrame[chatRole="user"] {
        background: #e9eaec;
        border: none;
        border-radius: 12px;
    }
    QFrame#metricChip {
        background: #f2f3f4;
        border: 1px solid #e4e5e7;
        border-radius: 8px;
    }
    """
    if theme == "dark":
        stylesheet += """
        * { color: #e8eaed; }
        QMainWindow, QDialog, QWidget#appSurface { background: #202124; }
        QFrame#topBar, QFrame#panelSurface, QFrame#cardSurface,
        QFrame#chapterSidebar, QFrame#manuscriptPanel, QFrame#plotChatPanel,
        QFrame[chatRole="assistant"] {
            background: #292a2d;
            border-color: #3c4043;
        }
        QLabel#mutedLabel, QLabel#sectionEyebrow { color: #aeb2b7; }
        QPushButton, QToolButton, QFrame#metricChip {
            background: #303134;
            border-color: #45474a;
        }
        QPushButton:hover, QToolButton:hover { background: #3c4043; }
        QPushButton:pressed, QToolButton:pressed { background: #484b4f; }
        QPushButton:disabled { color: #777b80; background: #292a2d; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QListWidget,
        QTreeWidget, QTableWidget, QTabWidget::pane {
            background: #292a2d;
            border-color: #45474a;
            selection-background-color: #4b4d51;
            selection-color: #ffffff;
        }
        QTreeWidget#chapterTree { background: transparent; border: none; }
        QTreeWidget#chapterTree::item:has-children { background: transparent; }
        QTreeWidget#chapterTree::item:!has-children {
            background: #333538;
            border-color: #45474a;
        }
        QTreeWidget#chapterTree::item:!has-children:hover { background: #3c3f43; }
        QTreeWidget#chapterTree::item:!has-children:selected {
            background: #4b4e53;
            border-color: #62666c;
            color: #ffffff;
        }
        QHeaderView::section { background: #303134; border-bottom-color: #45474a; }
        QTabBar::tab { color: #aeb2b7; }
        QTabBar::tab:selected { color: #ffffff; border-bottom-color: #ffffff; }
        QSplitter::handle { background: #3c4043; }
        QSplitter#chapterSectionSplitter::handle:vertical { background: #5a5e64; }
        QFrame[chatRole="user"] { background: #3c4043; }
        QToolButton#briefHelpButton {
            color: #aeb2b7;
            border-color: #858a91;
        }
        QToolButton#briefHelpButton:hover {
            background: #3c4043;
            color: #ffffff;
            border-color: #d2d5da;
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #686c72; }
        QScrollBar::handle:hover { background: #858a91; }
        """
    if density == "compact":
        stylesheet += """
        * { font-size: 12px; }
        QPushButton, QToolButton { padding: 4px 8px; border-radius: 7px; }
        QLineEdit, QComboBox, QSpinBox { min-height: 24px; padding: 0 6px; }
        QPlainTextEdit, QTextEdit { padding: 6px; }
        QHeaderView::section { padding: 5px; }
        QTabBar::tab { padding: 6px 9px; }
        """
    elif density == "comfortable":
        stylesheet += """
        * { font-size: 14px; }
        QPushButton, QToolButton { padding: 8px 12px; }
        QLineEdit, QComboBox, QSpinBox { min-height: 36px; padding: 0 10px; }
        QPlainTextEdit, QTextEdit { padding: 11px; }
        QHeaderView::section { padding: 9px; }
        QTabBar::tab { padding: 10px 13px; }
        """
    return stylesheet
