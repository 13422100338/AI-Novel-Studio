from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.core.context.context_manifest import ContextManifest


class ReferenceWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 参考内容 · AI Novel Studio")
        self.setMinimumSize(820, 560)
        self.resize(980, 680)

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("本次正文生成的 AI 参考内容", surface)
        title.setObjectName("panelTitle")
        explanation = QLabel(
            "这里显示 Context Manifest：正文模型实际采用、回退或因 Token 预算省略的上下文来源。"
            "它用于审查模型写作依据，不会修改正文或记忆库。",
            surface,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        self.status_label = QLabel("", surface)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("mutedLabel")
        self.table = QTableWidget(0, 5, surface)
        self.table.setHorizontalHeaderLabels(("状态", "类别", "来源", "选择理由", "估算 Token"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.warning_label = QLabel("", surface)
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("mutedLabel")

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.warning_label)
        self.setCentralWidget(surface)

    def bind_manifest(self, manifest: ContextManifest | None) -> None:
        self.table.setRowCount(0)
        if manifest is None:
            self.status_label.setText(
                "当前章节尚无 AI 参考记录。完成一次正文生成后，这里会显示实际使用的上下文。"
            )
            self.warning_label.clear()
            return

        self.status_label.setText(
            f"清单 {manifest.id[:12]} · 输入约 {manifest.estimated_input_tokens} Token · "
            f"输出上限 {manifest.output_token_limit} Token"
        )
        rows: list[tuple[str, str, str, str, str]] = []
        rows.extend(
            (
                "采用（摘要回退）" if item.used_fallback else "采用",
                item.category,
                f"{item.source_type} / {item.source_id}",
                item.rationale,
                str(item.estimated_tokens),
            )
            for item in manifest.selected
        )
        rows.extend(
            (
                "省略",
                item.category,
                f"{item.source_type} / {item.source_id}",
                item.reason,
                "—",
            )
            for item in manifest.omitted
        )
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.warning_label.setText(
            "" if not manifest.warnings else "警告：\n" + "\n".join(manifest.warnings)
        )

    def show_error(self, message: str) -> None:
        self.table.setRowCount(0)
        self.status_label.setText(f"AI 参考内容读取失败：{message}")
        self.warning_label.setText("原始清单未被修改。请重新生成正文或检查项目文件完整性。")
