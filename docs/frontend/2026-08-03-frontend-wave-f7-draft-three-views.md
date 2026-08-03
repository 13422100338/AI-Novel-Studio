# Frontend Wave F7 交付记录（草稿三视图与段落级采用）

> 分支：`codex/frontend-wave-f1`（F6 提交之上）
> 日期：2026-08-03
> 范围：AI 抽屉草稿三视图（当前正文 / AI 草稿 / 修改对比）+ 段落级采用；
> 不改任何后端接口。

## 1. 交付内容

- 新增确定性段落 diff（`bridge/paragraph_diff.py`，标准库 difflib）：
  - `split_paragraphs` / `diff_paragraphs`：按空行对齐当前正文与草稿，
    产出 `unchanged / replaced / inserted / deleted` 块；
  - `apply_diff_blocks`：仅应用「已接受」块重建正文；未处理/忽略块保留原段落，
    任意顺序接受结果一致；
- 新增 `DraftDiffModel`（QAbstractListModel，roles：blockId/kind/currentText/draftText）；
- Facade 三视图状态：
  - `draftViewEnabled`（项目模式草稿就绪）、`draftView`（current/draft/diff）、
    `draftBaseText`（生成时正文快照）、`draftText`、`draftDiff`；
  - `acceptDiffBlock(blockId)`：应用该段落到编辑器缓冲区 → DIRTY（后续经 F3 保存落盘）；
  - `rejectDiffBlock(blockId)`：仅忽略，正文不动；
  - 草稿就绪时基于「生成时正文快照」计算 diff，切章/重载/整章采用/放弃草稿时清空；
- QML SlidingDrawer：草稿存在时显示三视图切换（当前正文 / AI 草稿 / 修改对比），
  对比视图逐块展示「当前/草稿」文本与「采用此段 / 忽略此段」按钮；
  底部保留「采用整章 / 放弃草稿」（整章采用仍走 `GenerationAcceptanceService`）；
- AppButton 增加 `selected` 高亮态。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/paragraph_diff.py                 段落 diff + apply（新增）
├── bridge/models/draft_diff_model.py        diff 列表模型（新增）
├── bridge/mock_novel_studio_facade.py       三视图状态 + accept/reject 槽 + 生命周期清理
├── qml/components/AppButton.qml             selected 高亮
└── qml/components/SlidingDrawer.qml         三视图区 + diff 块卡片
tests/ui_qml/test_paragraph_diff.py          纯函数 diff/apply（新增 9）
tests/ui_qml/test_draft_diff_model.py        模型 roles/rebuild（新增 3）
tests/ui_qml/test_mock_facade.py             三视图/段落采用/整章采用清理（新增 6）
tests/ui_qml/test_qml_shell.py               QML 三视图切换 + 段落采用联动（新增 2）
docs/frontend/2026-08-03-frontend-wave-f7-draft-three-views.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 108 passed |
| 完整 `pytest` | 930 passed |
| Ruff / MyPy（197 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- diff 纯函数：替换/插入/删除/未变、忽略保留原文、任意顺序接受、空正文全量采用；
- facade：生成草稿后 diff 可用；接受替换段 → 正文更新 + DIRTY + 块移除；
  忽略 → 正文不变；接受全部块 → 正文 == 草稿；整章采用/切章 → diff 状态清空；
- QML：三视图按钮切换；diff 视图出现块卡片；接受替换段 → 编辑器更新 + DIRTY。

## 4. 接线细节、风险与下一步

- 段落级采用只改编辑器缓冲区（DIRTY），持久化走 F3 已有 `save_chapter` 路径，
  不新建后端接口、不直接写盘——符合「前端不另造采用逻辑」；
- diff 基线是「生成时正文快照」：生成后若用户先手动编辑正文，diff 视图仍对比
  快照而非最新编辑器内容，避免基线漂移；整章采用仍以后端草稿全文为准；
- 「编辑后接受」「查看生成依据」未做（延期）；方案 Phase 5 的字符级协同编辑
  明确不在第一版；
- 下一步建议：
  1. Token/费用显示（复用 `UsageSnapshot` 语义）；
  2. 或 F2 剩余只读接线（人物/记忆/审校数量概览与页面骨架）；
  3. 或打包前 QML 资源清单/入口评估（F6 打包票）。
