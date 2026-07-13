from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AgentTraceWindow(QMainWindow):
    def __init__(
        self,
        run: Any,
        turns: Iterable[Any],
        tool_calls: Iterable[Mapping[str, object]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("证据追踪")
        self.setMinimumSize(760, 520)
        self.resize(960, 700)

        run_id = str(getattr(run, "run_id", getattr(run, "id", "暂无")))
        status = getattr(getattr(run, "status", None), "value", str(getattr(run, "status", "")))
        turn_items = tuple(turns)
        tool_items = tuple(tool_calls)
        has_run = run_id not in {"", "暂无"} and status != "NO_RUN"

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QFrame(surface)
        header.setObjectName("traceHeader")
        header.setProperty("class", "panelSurface")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        heading_column = QVBoxLayout()
        title = QLabel("Agent 证据追踪", header)
        title.setObjectName("panelTitle")
        description = QLabel(
            "展示最近一次 Agent 运行实际保存的对话轮次、只读工具调用、证据来源与失败风险。",
            header,
        )
        description.setObjectName("mutedLabel")
        description.setWordWrap(True)
        heading_column.addWidget(title)
        heading_column.addWidget(description)
        header_layout.addLayout(heading_column, 1)
        self.status_badge = QLabel("尚无运行" if not has_run else status, header)
        self.status_badge.setObjectName("traceStatusBadge")
        header_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(header)

        self.status_label = QLabel(
            "尚未产生 Agent 运行记录。启用剧情商讨中的“工具检索”并发送消息后，"
            "这里才会出现可核查证据。"
            if not has_run
            else f"运行 ID：{run_id}  ·  状态：{status}  ·  "
            f"对话 {len(turn_items)} 轮  ·  工具调用 {len(tool_items)} 次",
            surface,
        )
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.trace_splitter = QSplitter(Qt.Orientation.Vertical, surface)
        self.trace_splitter.setObjectName("traceSplitter")
        self.trace_splitter.setChildrenCollapsible(False)
        self.trace_splitter.setHandleWidth(6)

        self.turn_table = self._table(("角色", "对话内容"), surface)
        self.turn_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.turn_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.turn_empty_label = QLabel("本次运行没有保存对话轮次。", surface)
        self.trace_splitter.addWidget(
            self._trace_card(
                "对话轨迹",
                "按实际执行顺序展示模型与工具看到的内容。",
                self.turn_table,
                self.turn_empty_label,
            )
        )

        self.tool_table = self._table(("工具", "状态", "结果字符", "证据来源 / 风险"), surface)
        for column in range(3):
            self.tool_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.tool_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tool_empty_label = QLabel("本次运行没有调用工具；普通聊天不会产生工具证据。", surface)
        self.trace_splitter.addWidget(
            self._trace_card(
                "工具调用",
                "记录工具名称、执行状态、返回规模以及可追溯来源或失败原因。",
                self.tool_table,
                self.tool_empty_label,
            )
        )
        self.trace_splitter.setSizes((330, 260))
        layout.addWidget(self.trace_splitter, 1)

        self._load_turns(turn_items)
        self._load_tool_calls(tool_items)
        self.turn_table.setVisible(bool(turn_items))
        self.turn_empty_label.setVisible(not turn_items)
        self.tool_table.setVisible(bool(tool_items))
        self.tool_empty_label.setVisible(not tool_items)
        self.setCentralWidget(surface)

    @staticmethod
    def _table(headers: tuple[str, ...], parent: QWidget) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setWordWrap(True)
        return table

    @staticmethod
    def _trace_card(
        title: str,
        description: str,
        table: QTableWidget,
        empty_label: QLabel,
    ) -> QFrame:
        card = QFrame(table.parentWidget())
        card.setObjectName("traceCard")
        card.setProperty("class", "cardSurface")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(7)
        heading = QLabel(title, card)
        heading.setObjectName("panelTitle")
        hint = QLabel(description, card)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        empty_label.setObjectName("traceEmptyState")
        empty_label.setWordWrap(True)
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setMinimumHeight(100)
        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addWidget(table, 1)
        layout.addWidget(empty_label, 1)
        return card

    def _load_turns(self, turns: tuple[Any, ...]) -> None:
        self.turn_table.setRowCount(len(turns))
        for row, turn in enumerate(turns):
            role = getattr(turn, "role", "")
            if not isinstance(role, str):
                role = getattr(role, "value", str(role))
            content = getattr(turn, "content", "")
            self.turn_table.setItem(row, 0, QTableWidgetItem(role))
            self.turn_table.setItem(row, 1, QTableWidgetItem(str(content)))
        self.turn_table.resizeRowsToContents()

    def _load_tool_calls(self, tool_calls: tuple[Mapping[str, object], ...]) -> None:
        self.tool_table.setRowCount(len(tool_calls))
        for row, call in enumerate(tool_calls):
            values = (
                call.get("tool_name", ""),
                call.get("status", ""),
                call.get("result_chars", ""),
                call.get("omitted", ""),
            )
            for column, value in enumerate(values):
                self.tool_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.tool_table.resizeRowsToContents()
