def application_stylesheet() -> str:
    return """
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
