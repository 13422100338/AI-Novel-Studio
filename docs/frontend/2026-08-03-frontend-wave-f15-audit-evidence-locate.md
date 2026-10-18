# Frontend Wave F15 交付记录（审校证据定位）

> 分支：`codex/frontend-wave-f1`（F14 提交之上）
> 日期：2026-08-03
> 范围：双击审校问题 → 跳转写作页并在编辑器中高亮证据；不改任何后端接口。

## 1. 交付内容

- `AuditListModel` 增加 `audit_at_row(row)`；
- Facade 新增 `revealAuditEvidence(row)`：
  - 取问题证据文本，在当前章节正文中精确查找位置；
  - 命中 → `setActiveNav("writing")` + 发 `evidenceRevealRequested(evidence, pos, len)`
    （PySide6 信号用 camelCase 以便 QML Connections 匹配）；
  - 未命中（正文已被修改）→ 状态栏提示「审校证据在当前正文中未找到」，不跳转；
- QML：
  - WritingPage 增加 `revealEvidence(position, length)`：聚焦编辑器并
    `select(pos, pos+length)` 高亮；
  - App 顶层 `Connections` 转发信号到写作页；
  - AuditPage 卡片 `MouseArea onDoubleClicked` 触发定位（保留单击选中语义）。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/models/readonly_list_models.py   AuditListModel.audit_at_row
├── bridge/mock_novel_studio_facade.py      revealAuditEvidence + camelCase 信号
├── qml/pages/WritingPage.qml               revealEvidence（select 高亮）
├── qml/App.qml                             Connections 转发
└── qml/pages/AuditPage.qml                 双击定位 + id:root（修复 root 未定义）
tests/ui_qml/test_readonly_views.py         模型审校夹具 + 定位/未命中（+3）
tests/ui_qml/test_qml_shell.py              编辑器选中文本断言（+1）
docs/frontend/2026-08-03-frontend-wave-f15-audit-evidence-locate.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 136 passed |
| 完整 `pytest` | 958 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

关键测试证据（真实模型审校 run + MODEL finding，evidence 为正文片段）：
- facade：定位成功 → 信号携带正确 position/length + 导航切到写作页；
  正文被改写后 → 「未找到」状态提示、不跳转；
- QML：触发定位后编辑器 `selectedText == "第二段。"`（offscreen 下 select 生效）。

## 4. 接线细节、风险与下一步

- 定位为**精确字符串匹配**：正文经编辑漂移后证据失配会如实提示，不强行近似定位
  （与方案 Phase 7「不因轻微编辑漂移而崩溃」一致，但精确度高匹配是第一步）；
- 修复了 F12 引入的 `AuditPage` `root` 未定义告警（缺失 `id: root`）；
- 下一步建议：
  1. 记忆记录详情面板（当前只读列表的下一层）；
  2. 或审校「忽略 / 误报」操作（需走 `ProjectAuditService.update_finding_status`，
     属于写操作接线）；
  3. 或草稿三视图的「编辑后接受」（基于现有 diff 块）。
