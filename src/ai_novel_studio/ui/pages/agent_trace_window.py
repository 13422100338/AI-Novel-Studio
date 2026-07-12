from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
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
        self.resize(820, 560)
        status = getattr(getattr(run, "status", None), "value", str(getattr(run, "status", "")))
        self.status_label = QLabel(f"Run: {getattr(run, 'run_id', '')} · {status}", self)
        self.turn_table = QTableWidget(0, 2, self)
        self.turn_table.setHorizontalHeaderLabels(("角色", "内容"))
        self.tool_table = QTableWidget(0, 4, self)
        self.tool_table.setHorizontalHeaderLabels(("工具", "状态", "结果字符", "省略/风险"))
        self._load_turns(tuple(turns))
        self._load_tool_calls(tuple(tool_calls))

        surface = QWidget(self)
        layout = QVBoxLayout(surface)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("对话轨迹", self))
        layout.addWidget(self.turn_table, 1)
        layout.addWidget(QLabel("工具调用", self))
        layout.addWidget(self.tool_table, 1)
        self.setCentralWidget(surface)

    def _load_turns(self, turns: tuple[Any, ...]) -> None:
        self.turn_table.setRowCount(len(turns))
        for row, turn in enumerate(turns):
            role = getattr(turn, "role", "")
            if not isinstance(role, str):
                role = getattr(role, "value", str(role))
            content = getattr(turn, "content", "")
            self.turn_table.setItem(row, 0, QTableWidgetItem(role))
            self.turn_table.setItem(row, 1, QTableWidgetItem(str(content)))

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
