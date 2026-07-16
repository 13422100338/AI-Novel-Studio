from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
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
            "它是生成当时的历史快照；修改模型设置后需重新生成正文才会建立新清单。",
            surface,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        self.status_label = QLabel("", surface)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("mutedLabel")
        self.table = QTableWidget(0, 5, surface)
        self.table.setHorizontalHeaderLabels(("状态", "类别", "来源", "选择理由", "估算 Token"))
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.detail = QPlainTextEdit(surface)
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        self.detail.setPlaceholderText("选择一条记录，查看未省略的完整来源与选择理由。")
        self._row_details: list[str] = []
        self.table.currentCellChanged.connect(self._show_row_detail)
        self.warning_label = QLabel("", surface)
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("mutedLabel")

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.detail)
        layout.addWidget(self.warning_label)
        self.setCentralWidget(surface)

    def bind_manifest(self, manifest: ContextManifest | None) -> None:
        self.table.setRowCount(0)
        self._row_details.clear()
        self.detail.clear()
        if manifest is None:
            self.status_label.setText(
                "当前章节尚无 AI 参考记录。完成一次正文生成后，这里会显示实际使用的上下文。"
            )
            self.warning_label.clear()
            return

        self.status_label.setText(
            f"清单 {manifest.id[:12]} · 输入约 {manifest.estimated_input_tokens} Token · "
            f"当时输入上限 {manifest.input_token_limit} Token · "
            f"输出上限 {manifest.output_token_limit} Token · "
            f"创建于 {manifest.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        rows: list[tuple[str, str, str, str, str]] = []
        rows.extend(
            (
                "采用（摘要回退）" if item.used_fallback else "采用",
                item.category,
                _source_label(item.source_type, item.source_id, item.source_revision),
                item.rationale,
                str(item.estimated_tokens),
            )
            for item in manifest.selected
        )
        rows.extend(
            (
                "省略",
                item.category,
                _source_label(item.source_type, item.source_id, item.source_revision),
                item.reason,
                "—",
            )
            for item in manifest.omitted
        )
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            self._row_details.append(
                "\n".join(
                    (
                        f"状态：{values[0]}",
                        f"类别：{values[1]}",
                        f"完整来源：{values[2]}",
                        f"选择理由：{values[3]}",
                        f"估算 Token：{values[4]}",
                    )
                )
            )
        self.table.resizeRowsToContents()
        self.warning_label.setText(
            "" if not manifest.warnings else "警告：\n" + "\n".join(manifest.warnings)
        )

    def show_error(self, message: str) -> None:
        self.table.setRowCount(0)
        self._row_details.clear()
        self.detail.clear()
        self.status_label.setText(f"AI 参考内容读取失败：{message}")
        self.warning_label.setText("原始清单未被修改。请重新生成正文或检查项目文件完整性。")

    def _show_row_detail(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if 0 <= current_row < len(self._row_details):
            self.detail.setPlainText(self._row_details[current_row])
        else:
            self.detail.clear()


def _source_label(
    source_type: str, source_id: str, source_revision: int | None
) -> str:
    revision = "未知" if source_revision is None else str(source_revision)
    return f"{source_type} / {source_id} / 修订 {revision}"
