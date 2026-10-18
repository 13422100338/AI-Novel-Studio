# AI Novel Studio Frontend C1.1 收尾修复交付

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 性质：C1 收尾修复；未进入 C2，未接真实 Agent 后端，未扩张功能范围。

## 1. 本轮目标

把 C1 已完成的界面与协议骨架修到可靠、可测试、可进入下一阶段：

- 修复导航返回正文路径；
- 统一两个 Agent 宿主到 `CreativeAgentPanel`；
- 修复 Agent Dock 开关/折叠/动画；
- 所有卡片按钮按 `itemId` 路由并有确定性 Mock 行为；
- 补 `form_card` / `change_set` 骨架；
- 选区引用做内容哈希、章节、修订三层校验；
- 跨段选区保留换行；
- 移除 mypy 全局 `ignore_missing_imports`；
- 截图前断言组件真实可见；
- 在含后端的环境中跑完整集成测试。

## 2. 修复明细

### P0-1 导航（完成）

- `_NAV_ALIASES` 删除错误别名 `"writing": "library"`；保留
  `writing / library / advanced / settings` 四个内部导航状态。
- `selectChapter`、`openProject`、`closeProject` 自动回到 `writing`。
- `revealAuditEvidence` 的 `setActiveNav("writing")` 现在真实进入写作页并定位选区。
- 新增返回写作入口：
  - 导航栏顶部“写作”按钮（`nav-writing`）；
  - 点击侧栏项目名返回写作；
  - 记忆详情“在正文中定位”按钮（`jumpToMemorySource`）。

### P0-2 Agent Dock（完成）

- `Layout.preferredWidth: open ? currentWidth : collapsedWidth`，折叠保留 34px 可见展开标签。
- 展开标签始终可点击，不再被零宽裁剪；新增 `openFromTab()` / `resetWidth()` 可测入口。
- 所有开关统一经 `Facade.toggleAiDrawer(...)`，QML 不再直接改 `root.open`。
- AI 面板标题栏新增关闭按钮（`agentCloseButton`）。
- 拖动宽度在 `minWidth(320) / maxWidth(45%窗口)` 内钳制；`Layout.minimumWidth/maximumWidth` 同步约束。
- 双击分隔线恢复 `defaultWidth(400)`。
- 宽度动画 `Behavior` 尊重 `Facade.reduceMotion`（为 true 时 duration=0）。

### P0-3 + P1-1 + P1-6 Agent 卡片（完成）

- `CreativeAgentPanel` delegate 改为显式 `id: delegateLoader`，`onLoaded` 使用
  `loadedItem`，消除变量遮蔽。
- 新增 Facade 接口（全部按 `itemId` 路由，替代旧无参方法）：
  `approveAgentItem / retryAgentItem / discardAgentItem / cancelAgentItem /
  submitAgentForm / skipAgentForm / editAgentChangeSet`。
- `TextDiffCard`：确认/再次修改/放弃全部接线；`ConfirmationCard`：确认/取消全部接线。
- 新增 `FormCard.qml`（1–3 个固定字段 + 保存/跳过/取消 + 回传 `itemId` 与表单值）
  与 `ChangeSetCard.qml`（对象/操作/修改前/修改后/风险/来源 + 确认/编辑/放弃），
  仅 Mock，不执行真实项目修改。
- Mock 时间线新增 `form_card`、`change_set` 两个阶段事件。
- 时间线事件增加稳定 `state` 字段（PENDING/RUNNING/COMPLETED/FAILED/CANCELLED/
  APPLIED/DISCARDED），approve/discard/cancel 后状态真实转换并回写模型。

### P1-2 宿主统一（完成）

- `SlidingDrawer`（TextArea）内容改为 `CreativeAgentPanel`，与 `AgentDock`（WebEngine）一致。
- 旧 `DiscussionPanel` 与 `sendDiscussion / clearDiscussion / discussionBusy /
  DiscussionMessageDto` 保留但全部标记 `DEPRECATED`，不再是默认渲染路径。

### P1-3 截图与组件断言（完成）

- 新增 `hash_utils.py`；截图前递归查找组件并断言 `visible === true` 且未被父级隐藏。
- 断言组件：`creativeAgentPanel`、`textDiffCard`、`confirmationCard`、
  `formCard`、`changeSetCard`、`selectionReferenceChip`、`agentExpandTab`、
  `agentSendButton`。
- 选区引用截图使用真实 FNV-1a 哈希，不再使用假哈希。
- 输出 7 张截图（shell×3、agent 面板、结构化卡片、选区 chip、折叠标签）。

### P1-4 选区引用加固（完成）

- Python 端重算并比对哈希（FNV-1a 与 SHA-256 均支持），格式合法但内容不符即拒绝。
- Facade 校验 `chapter_id == 当前章` 与 `base_revision == 当前修订`，过期引用被清除并提示。
- 拒绝：哈希不一致、非当前章、非当前修订、负位置、`to < from`、空文本、超长文本、非法哈希。
- 哈希工具收敛到 `bridge/hash_utils.py`，`editor_bridge` 复用。

### P1-5 跨段选区换行（完成）

- `editor-core.ts` 新增 `selectionText(state, from, to)`，块间用 `"\n"` 分隔；
  `editor.ts` 的 `getSelectionText` 改用它。引用文本与哈希基于真实带换行选区。

### P1-7 集成测试（完成，非破坏性）

- 独立 Mock 测试：`114 passed, 35 skipped`（skip 全部为依赖后端包的模块级
  `importorskip` 与真实项目 QML 用例，属合理环境 skip，逐项见第 4 节）。
- 后端环境集成测试：通过临时 `sitecustomize` 桥接，将独立前端 `src` 挂载进
  `c9a2` 后端环境（`ProjectWorkspaceService` 等真实后端服务可用），
  运行结果 `190 passed, 0 skipped`。
- 未触碰主仓库文件与 `.venv`（全程 `PYTHONDONTWRITEBYTECODE=1` + 只读导入）。

### P1-8 mypy（完成）

- 移除全局 `ignore_missing_imports = true`；
- `strict = true` 保持；仅 `application.* / domain.* / infrastructure.*`
  可选后端模块允许缺失导入；前端自身模块缺失导入仍会报错。

## 3. 建议清理项（一并处理）

- 3.1 旧剧情聊天路径已标记 deprecated（见 P1-2）。
- 3.2 Facade 过大：本轮未做大重构，Agent 状态机仍留在 Facade；C2 前可拆到
  `bridge/agent_coordinator.py`，已记录为后续重构点。
- 3.3 时间线事件已补 `state` 字段与 Mock 转换。

## 4. 测试结果

```text
独立前端测试：
  pytest tests/ui_qml            -> 114 passed, 35 skipped
  ruff check src tests scripts   -> All checks passed
  mypy (strict, 局部 override)   -> Success: no issues found in 37 source files
  npm test                       -> 129 passed
  npm run typecheck              -> ok
  npm run build                  -> editor bundle written to dist/

主仓库后端环境集成测试（c9a2 后端 + 独立前端 src 桥接）：
  pytest tests/ui_qml            -> 190 passed, 0 skipped
```

### skip 说明（独立模式 35 项）

- `test_draft_port / test_overview_counts / test_project_wiring /
  test_readonly_views`：模块级 `pytest.importorskip("ai_novel_studio.application")`，
  独立前端仓库不含后端包，属预期环境 skip。
- `test_editor_bridge`、`test_mock_facade`、`test_qml_shell` 中带
  `BACKEND_AVAILABLE` 分支的用例：需要真实后端项目工作区，独立模式下按设计跳过。
- 上述用例已在集成环境全部运行并全部通过（0 skip）。

## 5. 截图（docs/frontend/screenshots/）

- `c1-shell-paper.png` / `c1-shell-light.png` / `c1-shell-dark.png`
- `c1-agent-panel.png`（CreativeAgentPanel 展开）
- `c1-agent-timeline-cards.png`（TextDiffCard / ConfirmationCard / FormCard / ChangeSetCard）
- `c1-selection-reference-chip.png`（内容哈希校验后的选区引用 chip）
- `c1-agent-dock-collapsed.png`（折叠后的 34px 展开标签）

所有截图在保存前均完成“组件存在且可见”断言，找不到目标组件会非零退出。

## 6. 本轮修改文件

```text
src/ai_novel_studio/ui_qml/bridge/hash_utils.py                 （新增）
src/ai_novel_studio/ui_qml/bridge/models/selection_reference.py
src/ai_novel_studio/ui_qml/bridge/editor_bridge.py
src/ai_novel_studio/ui_qml/bridge/dtos.py
src/ai_novel_studio/ui_qml/bridge/models/agent_timeline_model.py
src/ai_novel_studio/ui_qml/bridge/mock_novel_studio_facade.py
src/ai_novel_studio/ui_qml/qml/components/CreativeAgentPanel.qml
src/ai_novel_studio/ui_qml/qml/components/FormCard.qml          （新增）
src/ai_novel_studio/ui_qml/qml/components/ChangeSetCard.qml     （新增）
src/ai_novel_studio/ui_qml/qml/components/TextDiffCard.qml
src/ai_novel_studio/ui_qml/qml/components/ConfirmationCard.qml
src/ai_novel_studio/ui_qml/qml/components/AgentDock.qml
src/ai_novel_studio/ui_qml/qml/components/SlidingDrawer.qml
src/ai_novel_studio/ui_qml/qml/components/DiscussionPanel.qml
src/ai_novel_studio/ui_qml/qml/components/NavigationRail.qml
src/ai_novel_studio/ui_qml/qml/components/ContextSidebar.qml
src/ai_novel_studio/ui_qml/qml/pages/MemoryLibraryPage.qml
src/ai_novel_studio/ui_qml/qml/pages/MemoryPage.qml
src/ai_novel_studio/ui_qml/qml/pages/WritingPage.qml
src/ai_novel_studio/ui_qml/editor_web/src/editor-core.ts
src/ai_novel_studio/ui_qml/editor_web/src/editor.ts
src/ai_novel_studio/ui_qml/editor_web/tests/editor-core.test.ts
tests/ui_qml/test_selection_reference.py
tests/ui_qml/test_agent_timeline.py
tests/ui_qml/test_mock_facade.py
tests/ui_qml/test_qml_shell.py
tests/ui_qml/test_draft_coordinator.py
scripts/capture_frontend_f1_screenshots.py
pyproject.toml
docs/frontend/2026-08-03-frontend-c1-1-delivery.md                （本文件）
```

## 7. 延期事项与未来接线点

- 真实 Agent Orchestrator / LLM 调用（C2 范围）；
- 真实选区替换与 ChangeSet 执行（当前仅 Mock，`itemId` 路由与状态机已就绪）；
- 真实表单持久化（`submitAgentForm` 目前只记录 Mock 文本）；
- `MockNovelStudioFacade` Agent 状态机拆分为 `bridge/agent_coordinator.py`；
- 主仓库后端重构分支完成后，将本分支挂载到最新后端重跑集成测试（本轮使用
  `c9a2` 7-17 快照环境，结果 190 passed / 0 skipped）。

## 8. 风险

- 本轮所有 Agent 写入仍为“提案/确认”面，未落盘任何项目数据；
- 集成测试使用的后端为 `c9a2` 快照（2026-07-17 前后），与最新后端重构分支
  的接口差异需在最终接线时复验；
- `DiscussionPanel` 等 deprecated 代码将在后续 Wave 移除。
