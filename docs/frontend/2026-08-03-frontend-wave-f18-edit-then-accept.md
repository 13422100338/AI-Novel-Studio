# Frontend Wave F18 交付记录（草稿「编辑后接受」）

> 分支：`codex/frontend-wave-f1`（F17 提交之上）
> 日期：2026-08-03
> 范围：草稿三视图差异卡片支持编辑草稿文本后采用；纯前端、不改任何后端接口。

## 1. 交付内容

- Facade 新增 `editAndAcceptDiffBlock(blockId, editedText)`：
  - 仅对 `replaced / inserted` 块生效（`unchanged / deleted` 拒绝）；
  - 空文本拒绝并提示「编辑后的文本不能为空」；
  - 用编辑文本替换该块 draft_text 后进入已接受集合，`apply_diff_blocks`
    以编辑结果重建正文 → DIRTY（经 F3 保存落盘）；
- QML SlidingDrawer 差异卡片：
  - `replaced / inserted` 块显示可编辑 TextArea（预填草稿文本）+「编辑后采用」按钮；
  - 顺带修复 F7 遗留瑕疵：`采用此段 / 忽略此段` 按钮仅对非 unchanged 块显示
    （此前 unchanged 块的隐藏按钮仍实例化，误点会造成无操作）；
- 测试新增「查找首个**可见** QML 项」helper（隐藏 delegate 的按钮不可误点）。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/mock_novel_studio_facade.py   editAndAcceptDiffBlock 槽
└── qml/components/SlidingDrawer.qml     编辑区 + 编辑后采用 + 按钮可见性修正
tests/ui_qml/test_mock_facade.py         编辑后采用/空文本拒绝（+2）
tests/ui_qml/test_qml_shell.py           QML 编辑→点击→正文更新（+1，含可见项 helper）
docs/frontend/2026-08-03-frontend-wave-f18-edit-then-accept.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 147 passed |
| 完整 `pytest` | 969 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- facade：编辑 replaced 块 → 正文替换为编辑文本、DIRTY、块移除；
  空文本 → 拒绝且正文不变；
- QML：可见编辑区预填草稿 → 输入自定义文本 → 点「编辑后采用」→
  编辑器正文含自定义文本 + DIRTY；
- 修正后 unchanged 块的隐藏按钮不再被误点（测试只找可见项）。

## 4. 接线细节、风险与下一步

- 编辑后采用只改编辑器缓冲区，持久化走 F3 保存路径（不新建后端接口）；
- 对 deleted 块不提供编辑（编辑无意义）；unchanged 块无操作按钮；
- 下一步建议：
  1. 审校「接受建议」修复（`RepairApplicationService` 候选层，含修订冲突）；
  2. 或状态栏 Token 芯片悬浮明细已做，可继续任务详情（取消/重试）；
  3. 或进入打包冒烟（PyInstaller onedir 构建 + 启动验证）。
