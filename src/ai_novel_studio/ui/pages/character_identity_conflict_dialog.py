from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityCandidateOrigin,
    CharacterIdentityCardSnapshot,
    CharacterIdentityReviewCandidate,
    RecentCharacterIdentityMerge,
)
from ai_novel_studio.domain.character_identity import CharacterIdentityMerge


class CharacterIdentityReviewService(Protocol):
    def list_review_candidates(self) -> tuple[CharacterIdentityReviewCandidate, ...]: ...

    def list_recent_applied_merges(
        self, *, limit: int = 20
    ) -> tuple[RecentCharacterIdentityMerge, ...]: ...

    def merge(
        self,
        source_character_id: str,
        target_character_id: str,
        *,
        reason: str,
        confirmed_by_user: bool,
    ) -> CharacterIdentityMerge: ...

    def undo(
        self, merge_id: str, *, confirmed_by_user: bool
    ) -> CharacterIdentityMerge: ...


class CharacterIdentityConflictDialog(QDialog):
    changed = Signal()

    def __init__(
        self,
        service: CharacterIdentityReviewService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self._candidates: tuple[CharacterIdentityReviewCandidate, ...] = ()
        self._recent_merges: tuple[RecentCharacterIdentityMerge, ...] = ()

        self.setWindowTitle("人物身份冲突")
        self.setMinimumSize(760, 560)
        self.resize(920, 680)
        layout = QVBoxLayout(self)

        title = QLabel("疑似重复人物卡", self)
        title.setObjectName("panelTitle")
        explanation = QLabel(
            "程序只按名称和别名列出候选，不会自动归并。请对照两侧资料并选择最终保留的主卡。",
            self,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")
        layout.addWidget(title)
        layout.addWidget(explanation)

        self.candidate_selector = QComboBox(self)
        self.candidate_selector.setAccessibleName("疑似重复人物候选")
        self.candidate_selector.currentIndexChanged.connect(self._render_candidate)
        layout.addWidget(self.candidate_selector)

        self.reason_label = QLabel(self)
        self.reason_label.setWordWrap(True)
        self.reason_label.setObjectName("mutedLabel")
        layout.addWidget(self.reason_label)

        comparison = QHBoxLayout()
        left_card, self.left_radio, self.left_details = self._card("保留左侧为主卡")
        right_card, self.right_radio, self.right_details = self._card("保留右侧为主卡")
        self.keep_group = QButtonGroup(self)
        self.keep_group.setExclusive(True)
        self.keep_group.addButton(self.left_radio)
        self.keep_group.addButton(self.right_radio)
        comparison.addWidget(left_card, 1)
        comparison.addWidget(right_card, 1)
        layout.addLayout(comparison, 1)

        actions = QHBoxLayout()
        self.merge_button = QPushButton("确认归并", self)
        self.merge_button.clicked.connect(self._merge_selected)
        actions.addStretch(1)
        actions.addWidget(self.merge_button)
        layout.addLayout(actions)

        recent = QFrame(self)
        recent.setObjectName("cardSurface")
        recent_layout = QVBoxLayout(recent)
        recent_layout.addWidget(QLabel("最近可撤销归并", recent))
        recent_actions = QHBoxLayout()
        self.recent_selector = QComboBox(recent)
        self.recent_selector.setAccessibleName("最近人物归并记录")
        self.undo_button = QPushButton("撤销所选归并", recent)
        self.undo_button.clicked.connect(self._undo_selected)
        recent_actions.addWidget(self.recent_selector, 1)
        recent_actions.addWidget(self.undo_button)
        recent_layout.addLayout(recent_actions)
        layout.addWidget(recent)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("mutedLabel")
        layout.addWidget(self.status_label)

        self.refresh()

    def refresh(self) -> None:
        self._candidates = self.service.list_review_candidates()
        self.candidate_selector.blockSignals(True)
        self.candidate_selector.clear()
        for candidate in self._candidates:
            origin = (
                "Agent 提案"
                if candidate.origin == CharacterIdentityCandidateOrigin.AGENT_PROPOSAL
                else "规则候选"
            )
            self.candidate_selector.addItem(
                f"{origin} · {candidate.left.character.canonical_name}  ↔  "
                f"{candidate.right.character.canonical_name}"
            )
        self.candidate_selector.blockSignals(False)
        self._render_candidate(self.candidate_selector.currentIndex())

        self._recent_merges = self.service.list_recent_applied_merges()
        self.recent_selector.clear()
        for recent in self._recent_merges:
            self.recent_selector.addItem(
                f"{recent.source_name} → {recent.target_name}", recent.merge.id
            )
        self.undo_button.setEnabled(bool(self._recent_merges))

    @staticmethod
    def _card(
        radio_text: str,
    ) -> tuple[QFrame, QRadioButton, QPlainTextEdit]:
        card = QFrame()
        card.setObjectName("cardSurface")
        card_layout = QVBoxLayout(card)
        radio = QRadioButton(radio_text, card)
        details = QPlainTextEdit(card)
        details.setReadOnly(True)
        card_layout.addWidget(radio)
        card_layout.addWidget(details, 1)
        return card, radio, details

    def _render_candidate(self, index: int) -> None:
        if index < 0 or index >= len(self._candidates):
            self.reason_label.setText("当前没有检测到需要人工确认的疑似重复人物卡。")
            self.left_details.clear()
            self.right_details.clear()
            self.left_radio.setChecked(False)
            self.right_radio.setChecked(False)
            self.merge_button.setEnabled(False)
            return
        candidate = self._candidates[index]
        origin = (
            "Agent 提案（尚未修改记忆库）"
            if candidate.origin == CharacterIdentityCandidateOrigin.AGENT_PROPOSAL
            else "程序规则候选"
        )
        self.reason_label.setText(f"来源：{origin}\n候选原因：{candidate.reason}")
        self.left_details.setPlainText(self._card_text(candidate.left))
        self.right_details.setPlainText(self._card_text(candidate.right))
        keep_left = candidate.recommended_character_id == candidate.left.character.id
        self.left_radio.setChecked(keep_left)
        self.right_radio.setChecked(not keep_left)
        self.merge_button.setEnabled(True)

    @staticmethod
    def _card_text(snapshot: CharacterIdentityCardSnapshot) -> str:
        character = snapshot.character
        aliases = "、".join(character.aliases) or "无"
        profile = character.profile.strip() or "无"
        lines = [
            f"姓名：{character.canonical_name}",
            f"别名：{aliases}",
            f"简介：{profile}",
            f"状态记录：{snapshot.state_count} 条",
        ]
        if snapshot.evidence:
            lines.append("\n最近章节证据：")
            lines.extend(
                f"- {item.chapter_title}：{item.summary}" for item in snapshot.evidence
            )
        else:
            lines.append("\n最近章节证据：无")
        return "\n".join(lines)

    def _merge_selected(self) -> None:
        index = self.candidate_selector.currentIndex()
        if index < 0 or index >= len(self._candidates):
            return
        candidate = self._candidates[index]
        target = candidate.left if self.left_radio.isChecked() else candidate.right
        source = candidate.right if self.left_radio.isChecked() else candidate.left
        answer = QMessageBox.question(
            self,
            "确认人物归并",
            f"将“{source.character.canonical_name}”归并到主卡“"
            f"{target.character.canonical_name}”。\n\n"
            "来源人物卡会被保留为可撤销记录；其状态和引用将移动到主卡。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.merge(
                source.character.id,
                target.character.id,
                reason=f"用户确认：{candidate.reason}",
                confirmed_by_user=True,
            )
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "人物归并失败", str(error))
            return
        self.refresh()
        self.status_label.setText(
            f"已归并“{source.character.canonical_name}”到“{target.character.canonical_name}”。"
        )
        self.changed.emit()

    def _undo_selected(self) -> None:
        index = self.recent_selector.currentIndex()
        if index < 0 or index >= len(self._recent_merges):
            return
        recent = self._recent_merges[index]
        answer = QMessageBox.question(
            self,
            "确认撤销人物归并",
            f"撤销“{recent.source_name} → {recent.target_name}”并恢复原人物卡及引用？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.undo(recent.merge.id, confirmed_by_user=True)
        except (KeyError, PermissionError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "撤销人物归并失败", str(error))
            return
        self.refresh()
        self.status_label.setText(
            f"已撤销“{recent.source_name} → {recent.target_name}”的人物归并。"
        )
        self.changed.emit()
