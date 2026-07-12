import difflib
from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.model_tasks import StyleAuditResult
from ai_novel_studio.ui.demo_data import WorkspaceDemoData


class AuditWindow(QMainWindow):
    deterministic_audit_requested = Signal()
    model_audit_requested = Signal()
    evidence_activated = Signal(str)
    finding_status_requested = Signal(str, str)
    repair_proposal_requested = Signal(str, str, str)
    repair_apply_requested = Signal(str)
    repair_reject_requested = Signal(str)

    def __init__(self, data: WorkspaceDemoData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("审校工作台 · AI Novel Studio")
        self.setMinimumSize(860, 640)
        self.resize(1040, 760)
        self.current_proposal_id: str = ""

        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("独立审校工作台", surface)
        title.setObjectName("panelTitle")
        explanation = QLabel(
            "确定性检查负责频率和格式；模型审校负责知识边界、动机、节奏和声音。"
            "任何修复都必须先显示差异。",
            surface,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        self.error_label = QLabel("", surface)
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)

        deterministic = [row for row in data.audit_findings if row[0] == "确定性"]
        model = [row for row in data.audit_findings if row[0] == "模型"]
        self.tabs = QTabWidget(surface)
        self.deterministic_table = self._finding_table(deterministic, self.tabs)
        self.model_table = self._finding_table(model, self.tabs)
        self.deterministic_table.cellDoubleClicked.connect(
            lambda row, _column: self._activate_evidence(self.deterministic_table, row)
        )
        self.model_table.cellDoubleClicked.connect(
            lambda row, _column: self._activate_evidence(self.model_table, row)
        )
        self.deterministic_table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column: self._select_finding(
                self.deterministic_table, row
            )
        )
        self.model_table.currentCellChanged.connect(
            lambda row, _column, _old_row, _old_column: self._select_finding(
                self.model_table, row
            )
        )
        self.tabs.addTab(self.deterministic_table, "确定性检查")
        self.tabs.addTab(self.model_table, "模型审校")

        self.run_deterministic_audit_button = QPushButton("运行确定性检查", surface)
        self.run_deterministic_audit_button.setAccessibleName("运行当前章节确定性审校")
        self.run_deterministic_audit_button.clicked.connect(
            self.deterministic_audit_requested
        )
        self.reject_finding_button = QPushButton("忽略问题", surface)
        self.reject_finding_button.clicked.connect(
            lambda: self._request_status("REJECTED")
        )
        self.false_positive_button = QPushButton("标记误报", surface)
        self.false_positive_button.clicked.connect(
            lambda: self._request_status("FALSE_POSITIVE")
        )
        self.repair_button = QPushButton("生成局部修复建议", surface)
        self.repair_button.setEnabled(False)
        self.repair_button.setToolTip("阶段 6 接入有边界的局部修复后可用")
        self.repair_button.clicked.connect(self._request_repair_proposal)
        self.repair_target = QPlainTextEdit(surface)
        self.repair_target.setPlaceholderText("选中问题后显示对应原文证据")
        self.repair_target.setMaximumHeight(90)
        self.repair_replacement = QPlainTextEdit(surface)
        self.repair_replacement.setPlaceholderText("填写建议替换文本；不会直接修改正文")
        self.repair_replacement.setMaximumHeight(90)
        self.repair_status_label = QLabel("尚未生成修复建议", surface)
        self.repair_status_label.setObjectName("mutedLabel")
        self.repair_diff = QPlainTextEdit(surface)
        self.repair_diff.setReadOnly(True)
        self.repair_diff.setPlaceholderText("生成建议后在这里显示局部 diff")
        self.repair_diff.setMaximumHeight(130)
        self.apply_repair_button = QPushButton("确认采用", surface)
        self.apply_repair_button.setEnabled(False)
        self.apply_repair_button.clicked.connect(
            lambda: self.repair_apply_requested.emit(self.current_proposal_id)
        )
        self.reject_repair_button = QPushButton("拒绝建议", surface)
        self.reject_repair_button.setEnabled(False)
        self.reject_repair_button.clicked.connect(
            lambda: self.repair_reject_requested.emit(self.current_proposal_id)
        )
        self._selected_finding_id = ""
        self.run_model_audit_button = QPushButton("运行模型审校", surface)
        self.run_model_audit_button.setAccessibleName("使用审校模型检查当前章节")
        self.run_model_audit_button.clicked.connect(self.model_audit_requested)
        actions = QHBoxLayout()
        actions.addWidget(self.run_deterministic_audit_button)
        actions.addWidget(self.reject_finding_button)
        actions.addWidget(self.false_positive_button)
        actions.addWidget(self.run_model_audit_button)
        actions.addStretch(1)
        actions.addWidget(self.repair_button)

        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.error_label)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(QLabel("局部修复原文", surface))
        layout.addWidget(self.repair_target)
        layout.addWidget(QLabel("建议替换文本", surface))
        layout.addWidget(self.repair_replacement)
        layout.addWidget(QLabel("局部差异", surface))
        layout.addWidget(self.repair_diff)
        layout.addWidget(self.repair_status_label)
        repair_actions = QHBoxLayout()
        repair_actions.addStretch(1)
        repair_actions.addWidget(self.reject_repair_button)
        repair_actions.addWidget(self.apply_repair_button)
        layout.addLayout(repair_actions)
        layout.addLayout(actions)
        self.setCentralWidget(surface)

    @staticmethod
    def _finding_table(findings: list[tuple[str, str, str]], parent: QWidget) -> QTableWidget:
        table = QTableWidget(max(1, len(findings)), 4, parent)
        table.setHorizontalHeaderLabels(("来源", "问题", "证据", "状态"))
        table.horizontalHeader().setStretchLastSection(True)
        if not findings:
            findings = [("", "", "")]
        for row, values in enumerate(findings):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        return table

    def apply_model_audit(self, result: StyleAuditResult) -> None:
        self.model_table.setRowCount(len(result.findings))
        for row, finding in enumerate(result.findings):
            values = (finding.category, finding.issue, finding.evidence)
            for column, value in enumerate(values):
                self.model_table.setItem(row, column, QTableWidgetItem(value))
        self.run_model_audit_button.setEnabled(True)
        self.run_model_audit_button.setText("重新运行模型审校")

    def apply_saved_model_findings(self, findings: Iterable[object]) -> None:
        findings = tuple(findings)
        self.model_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            source = getattr(getattr(finding, "source", ""), "value", "MODEL")
            category = getattr(getattr(finding, "category", ""), "value", "")
            severity = getattr(getattr(finding, "severity", ""), "value", "")
            explanation = str(getattr(finding, "explanation", ""))
            evidence = str(getattr(finding, "evidence", ""))
            status = getattr(getattr(finding, "status", ""), "value", "")
            values = (
                str(source),
                f"{category} / {severity}: {explanation}",
                evidence,
                str(status),
            )
            for column, value in enumerate(values):
                self.model_table.setItem(row, column, QTableWidgetItem(value))
            finding_id = str(getattr(finding, "id", ""))
            source_item = self.model_table.item(row, 0)
            if finding_id and source_item is not None:
                source_item.setData(Qt.ItemDataRole.UserRole, finding_id)
        self.run_model_audit_button.setEnabled(True)
        self.run_model_audit_button.setText("重新运行模型审校")

    def apply_deterministic_findings(self, findings: Iterable[object]) -> None:
        findings = tuple(findings)
        rows = []
        for finding in findings:
            source = getattr(
                getattr(finding, "source", ""),
                "value",
                getattr(finding, "source", ""),
            )
            category = getattr(
                getattr(finding, "category", ""),
                "value",
                getattr(finding, "category", ""),
            )
            severity = getattr(
                getattr(finding, "severity", ""),
                "value",
                getattr(finding, "severity", ""),
            )
            explanation = getattr(finding, "explanation", "")
            evidence = getattr(finding, "evidence", "")
            rows.append(
                (
                    str(source or "DETERMINISTIC"),
                    f"{category} / {severity}: {explanation}",
                    str(evidence),
                )
            )
        self.deterministic_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.deterministic_table.setItem(row, column, QTableWidgetItem(value))
            finding_id = str(getattr(findings[row], "id", ""))
            if finding_id:
                source_item = self.deterministic_table.item(row, 0)
                if source_item is not None:
                    source_item.setData(Qt.ItemDataRole.UserRole, finding_id)
            status = getattr(getattr(findings[row], "status", ""), "value", "")
            self.deterministic_table.setItem(row, 3, QTableWidgetItem(str(status)))
        self.run_deterministic_audit_button.setEnabled(True)
        self.run_deterministic_audit_button.setText("重新运行确定性检查")

    def _activate_evidence(self, table: QTableWidget, row: int) -> None:
        item = table.item(row, 2)
        if item is not None and item.text().strip():
            self.evidence_activated.emit(item.text().strip())

    def _request_status(self, status: str) -> None:
        table = self.tabs.currentWidget()
        if not isinstance(table, QTableWidget):
            return
        row = table.currentRow()
        item = table.item(row, 0) if row >= 0 else None
        finding_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(finding_id, str) and finding_id:
            self.finding_status_requested.emit(finding_id, status)

    def mark_finding_status(self, finding_id: str, status: str) -> None:
        for table in (self.deterministic_table, self.model_table):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == finding_id:
                    table.setItem(row, 3, QTableWidgetItem(status))
                    return

    def show_error(self, message: str) -> None:
        self.error_label.setText(f"审校结果未保存：{message}")
        self.run_model_audit_button.setEnabled(True)
        self.run_model_audit_button.setText("重新运行模型审校")

    def _select_finding(self, table: QTableWidget, row: int) -> None:
        source_item = table.item(row, 0) if row >= 0 else None
        evidence_item = table.item(row, 2) if row >= 0 else None
        finding_id = (
            source_item.data(Qt.ItemDataRole.UserRole)
            if source_item is not None
            else None
        )
        self._selected_finding_id = finding_id if isinstance(finding_id, str) else ""
        self.repair_target.setPlainText(
            evidence_item.text() if evidence_item is not None else ""
        )
        self.repair_button.setEnabled(bool(self._selected_finding_id))

    def _request_repair_proposal(self) -> None:
        target = self.repair_target.toPlainText().strip()
        replacement = self.repair_replacement.toPlainText().strip()
        if self._selected_finding_id and target and replacement:
            self.repair_proposal_requested.emit(
                self._selected_finding_id, target, replacement
            )
        else:
            self.repair_status_label.setText("请选择问题并填写建议替换文本")

    def show_repair_proposal(self, proposal: object) -> None:
        self.current_proposal_id = str(getattr(proposal, "id", ""))
        status = getattr(getattr(proposal, "status", ""), "value", "")
        risk = str(getattr(proposal, "risk_note", ""))
        self.repair_status_label.setText(f"建议状态：{status}；{risk}")
        target = str(getattr(proposal, "target_text", ""))
        replacement = str(getattr(proposal, "replacement_text", ""))
        diff = difflib.unified_diff(
            target.splitlines(),
            replacement.splitlines(),
            fromfile="原文",
            tofile="建议",
            lineterm="",
        )
        self.repair_diff.setPlainText("\n".join(diff))
        self.apply_repair_button.setEnabled(status == "VALIDATED")
        self.reject_repair_button.setEnabled(status == "VALIDATED")

    def show_repair_error(self, message: str) -> None:
        self.repair_status_label.setText(f"修复建议未生成：{message}")

    def mark_repair_applied(self) -> None:
        self.repair_status_label.setText("修复已采用，正文已创建新版本并记录来源")
        self.apply_repair_button.setEnabled(False)
        self.reject_repair_button.setEnabled(False)

    def mark_repair_rejected(self) -> None:
        self.repair_status_label.setText("修复建议已拒绝，正文未修改")
        self.apply_repair_button.setEnabled(False)
        self.reject_repair_button.setEnabled(False)
