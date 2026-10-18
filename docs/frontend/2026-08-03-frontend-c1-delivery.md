# Frontend Wave C1 — Product Convergence and Agent UI Skeleton 交付记录

> 仓库：`13422100338/AI-Novel-Studio-Frontend`；分支 `codex/frontend-agent-c1`
> 基线：`main` @ `fdbb2fa`；日期：2026-08-03

## 1. 实施内容

1. **只读审计**：`docs/frontend/2026-08-03-frontend-c1-audit.md`（10 个问题全部回答）；
2. **顶级导航收束**：导航轨从六项改为「记忆库 / 高级创作 / 设置」三项；写作工作区成为
   默认主页（`activeNav=writing` 仍为内部状态）；人物/记忆并入记忆库容器页
   （角色/世界/剧情记忆/待处理），线索/审校并入高级创作容器页（六个 Tab 占位），
   设置独立页；旧 id（memory/characters/audit/clues）作为别名映射保留；
3. **正文减负**：WritingPage 顶部只剩卷名/章节标题 + “···”菜单（修订/章节信息/
   生成草稿/AI 助手）；生成草稿、AI 参考、章节信息、说明文字移出正文区；底部保留
   字数/状态/修订/保存状态/保存/取消生成/冲突恢复；全局状态栏只显示侧栏折叠/字数/
   自动保存/任务 + “···”菜单（主题/动效/Token/费用/缓存/数据源）；
4. **Agent Dock**：`AgentDock.qml`（可拖动左边缘改宽度 320–45%、双击复位 400、
   可收起并保留展开入口、不覆盖 WebEngine、`reduceMotion` 生效）；默认 400px；
5. **Agent 时间线**：`AgentTimelineItemDto` + `AgentTimelineModel`（10 种 kind）；
   `CreativeAgentPanel` 用 Loader + component map 渲染独立卡片组件（AgentTextBlock /
   AgentRunStatus / ToolCallCard / ChoiceCard / TextDiffCard / ConfirmationCard）；
6. **AgentComposer**：多行输入、Enter 发送、Shift+Enter 换行、停止按钮、快捷命令
   （重写/润色/精简/扩写/生成草稿）、选区引用 chip 与清除、忙碌时禁用发送；
7. **选区引用协议**：editor-core 纯函数 `buildSelectionReference`（含大小上限与哈希）；
   editor.ts 在选区变化时上报 JSON（空选区/切章发空串清引用）；EditorBridge 校验并
   发 `selection_reference_changed`；Facade 保存引用并暴露
   `hasSelectionReference / selectionReferenceLabel / selectionReferencePreview /
   clearSelectionReference`，切章自动清空；Mock Agent 在 `tool_result` 与
   `text_diff` 中使用引用文本；
8. **Mock Agent 事件流**：`startAgentTurn` 分阶段（QTimer）追加
   user_text → run_status → tool_call → tool_result → run_status → text_diff →
   confirmation；`stopAgentTurn` 停止并追加 warning；`agentReplyChoice` /
   `approveAgentChangeSet` / `discardAgentChangeSet` 追加 assistant_text；
9. **独立仓库可运行**：Facade/端口后端可选导入（`backend_availability`），后端缺失时
   Mock 模式可加载、可测试；依赖后端的旧测试保留并按可用性跳过；
10. 测试、截图与文档。

## 2. 修改文件

新增：
```text
src/ai_novel_studio/ui_qml/bridge/backend_availability.py
src/ai_novel_studio/ui_qml/bridge/models/agent_timeline_model.py
src/ai_novel_studio/ui_qml/bridge/models/selection_reference.py
src/ai_novel_studio/ui_qml/qml/components/AgentDock.qml
src/ai_novel_studio/ui_qml/qml/components/CreativeAgentPanel.qml
src/ai_novel_studio/ui_qml/qml/components/AgentComposer.qml
src/ai_novel_studio/ui_qml/qml/components/AgentTextBlock.qml
src/ai_novel_studio/ui_qml/qml/components/AgentRunStatus.qml
src/ai_novel_studio/ui_qml/qml/components/ToolCallCard.qml
src/ai_novel_studio/ui_qml/qml/components/ChoiceCard.qml
src/ai_novel_studio/ui_qml/qml/components/TextDiffCard.qml
src/ai_novel_studio/ui_qml/qml/components/ConfirmationCard.qml
src/ai_novel_studio/ui_qml/qml/components/ContextReferenceChip.qml
src/ai_novel_studio/ui_qml/qml/pages/MemoryLibraryPage.qml
src/ai_novel_studio/ui_qml/qml/pages/AdvancedCreationPage.qml
src/ai_novel_studio/ui_qml/qml/pages/SettingsPage.qml
tests/ui_qml/test_agent_timeline.py
tests/ui_qml/test_selection_reference.py
docs/frontend/2026-08-03-frontend-c1-audit.md
docs/frontend/2026-08-03-frontend-c1-delivery.md
```

修改：`App.qml`、`NavigationRail.qml`、`WritingPage.qml`、`SlidingDrawer.qml`、
`qmldir`（components/pages）、`dtos.py`、`mock_novel_studio_facade.py`、
`draft_port.py`、`overview_counts.py`、`readonly_views.py`、`editor_bridge.py`、
`bootstrap.py`、`editor.ts`、`editor-core.ts`、`pyproject.toml`（mypy
`ignore_missing_imports`）、`interface_contracts.md`、截图脚本与测试若干。
删除：`DockableAiDrawer.qml`（被 AgentDock 取代）。

## 3. 新增/改变的接口

- JS：`window.__novelEditor.getSelectionText()`；上行
  `pythonBridge.selectionReferenceChanged(payloadJson)`；
- Python：`EditorBridge.selection_reference_changed(str)`；
  `Facade.setSelectionReferenceJson(str)`、`startAgentTurn(str)`、
  `stopAgentTurn()`、`agentReplyChoice(int)`、`approveAgentChangeSet()`、
  `discardAgentChangeSet()`、`agentTimeline`、`agentBusy`、
  `hasSelectionReference`、`selectionReferenceLabel`、`selectionReferencePreview`、
  `clearSelectionReference()`；
- `GenerationConfig.mode/audit_policy` 由后端枚举改为字符串（BASIC/STANDARD/STRICT、
  MINIMAL/STANDARD/DEEP），真实端口在 prepare 时转换回后端枚举；
- 导航：`_NAV_IDS = ("writing","library","advanced","settings")`，旧 id 别名映射。

## 4. 延期事项

- 真实 `CreativeAgentPort` / Agent Orchestrator（C2 只读 Agent）；
- ChangeSet 执行（C3）、正文选区真实替换（C4）、新小说向导（C5）；
- 人物/世界/伏笔等页面完整迁移（C1 用容器页复用现有页面）；
- 完全独立安装（后端 Port 协议拆分，见审计第 10 节）；
- WebEngine 模式真机截图（offscreen 无法初始化 WebEngine；选区链路已用
  TextArea + 注入方式验证并截图，真机步骤见 phase1-manual-acceptance.md）。

## 5. 风险

- 导航/正文减负改变了部分 UI 断言（已同步更新测试；旧 id 别名保留兼容）；
- 独立仓库无后端包：依赖后端的测试被 `importorskip`/运行时 skip（保留合同），
  主仓库挂载后端后这些测试照常运行；
- Agent 时间线 QTimer 分阶段事件在无事件循环的纯 Python 下需 pump（测试已处理）；
- WebEngine 真机验收仍需本机执行（IME/滚动/选区上报）。

## 6. 测试命令与真实结果

```powershell
python -m pytest tests/ui_qml -q --basetemp .test-temp/pytest-base
# 102 passed, 35 skipped（skip 均为后端依赖用例；主仓库可全部运行）
python -m ruff check src tests scripts            # All checks passed
python -m mypy                                    # Success: 36 source files
cd src\ai_novel_studio\ui_qml\editor_web
npm test                                          # 127 passed
npm run typecheck                                 # 通过
npm run build                                     # dist 5 文件
```

## 7. 截图

`docs/frontend/screenshots/`：
- `c1-shell-paper.png` / `c1-shell-light.png` / `c1-shell-dark.png`（收束默认界面）
- `c1-agent-panel-textdiff.png`（Agent 时间线 + TextDiffCard）
- `c1-selection-reference-chip.png`（选区引用 chip）
- `02-shell-paper-ai-drawer.png`（旧套件保留）

## 8. 提交

独立 commit（本分支内多个增量提交，最终合为一个 C1 交付），不合并 main；
分支已推送到独立前端仓库 origin。
