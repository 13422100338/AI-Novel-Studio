# Frontend Wave C1 — 只读审计报告

> 仓库：`13422100338/AI-Novel-Studio-Frontend`；基线 `main` @ `fdbb2fa`
> 日期：2026-08-03
> 本阶段禁止修改代码；报告为 C1 实施范围与顺序的依据。

## 1. 当前主窗口的信息架构

```text
ApplicationWindow
├── RowLayout
│   ├── NavigationRail      六项：写作/人物/记忆/线索/审校/设置
│   ├── ContextSidebar      项目信息 + 卷章树（280px，可折叠）
│   ├── Rectangle           中央 StackLayout（6 页）
│   │   ├── WritingPage     （默认，写作）
│   │   ├── CharactersPage / MemoryPage / Clues占位 / AuditPage / Settings占位
│   └── DockableAiDrawer    WebEngine 模式停靠抽屉（340px 固定）
├── 状态栏                   侧栏折叠/字数/自动保存/任务/模型/Token/费用/缓存/数据源/动效/主题
└── SlidingDrawer           TextArea 模式浮层（DiscussionPanel 内容）
```

问题：六个顶级导航把“写作”也当作平级入口；人物/记忆/线索/审校分散；
正文页顶部/底部堆叠大量按钮与状态芯片；AI 面板固定宽度、内容仅是“剧情商讨”聊天。

## 2. 正文区控件去留

| 控件 | 判定 | 去向 |
|---|---|---|
| 卷名/章节路径 | 保留 | 标题行 |
| 章节标题 | 保留 | 标题行 |
| WebEngine 编辑器 | 保留 | 中央 |
| 字数 | 保留 | 底部状态栏 |
| 保存状态 / 修订冲突 | 保留 | 底部状态栏 + 冲突恢复按钮 |
| 保存按钮 | 合并 | 标题行右侧“···”菜单 + 底部仅保留冲突恢复（减少重复） |
| 生成草稿 / 取消生成 | 移出 | AI 助手（AgentComposer 快捷命令） |
| AI 参考 | 移出 | 右侧 Agent Dock 常驻/可收起，不再需要顶部入口 |
| 章节信息 | 移出 | 标题行“···”菜单 |
| 模型/Token/费用/缓存 | 移出 | Agent 面板顶部可折叠运行信息 |
| 数据源/动效/主题 | 移出 | 状态栏仅保留“···”或设置页（主题/动效归设置） |
| 长篇说明文字 | 删除 | — |

## 3. 当前 AI 面板数据模型与限制

- `DiscussionMessageDto(id, role, text)` + `DiscussionMessageListModel`：仅支持
  `user/assistant` 纯文本；无状态、工具、卡片、Diff、确认等结构化事件；
- `sendDiscussion()` 是同步 Mock（追加一条回复），无忙碌流式、无停止；
- `DockableAiDrawer` 固定 340px，不可拖动、不可恢复默认宽度、无收起入口（只有关闭）；
- 内容被 `DiscussionPanel` 独占，无法容纳 Codex 式复杂卡片时间线。

## 4. WebEngine 选区事件现状

- `editor.ts` 的 `pythonBridge` 接口声明了 `selectionChanged(from, to)`，但**页面尚未在
  选区变化时调用**（仅类型声明）；
- Python `EditorBridge.selection_changed` 只携带 `(from, to)`，无章节、修订、
  选中文本与哈希；
- 无“替换选区”下行协议（只有 `revealRange`）；
- 结论：选区链路只完成了类型骨架，未打通数据。

## 5. Facade 职责评估

`mock_novel_studio_facade.py`（约 1200 行）承担：项目/章节/保存/冲突、字数、
草稿端口与协调器、候选层与 diff、用量、概览计数、只读列表、人物/记忆/审校详情、
审校写操作、AI 讨论。**职责过重**，但 C1 不做大规模拆分（属长期方向，
见 10 独立前端边界）。C1 仅新增 Agent 时间线与选区引用状态，保持既有职责不动。

## 6. 本轮预计修改文件

```text
src/ai_novel_studio/ui_qml/qml/App.qml
src/ai_novel_studio/ui_qml/qml/components/NavigationRail.qml
src/ai_novel_studio/ui_qml/qml/components/AgentDock.qml          （新增）
src/ai_novel_studio/ui_qml/qml/components/CreativeAgentPanel.qml （新增）
src/ai_novel_studio/ui_qml/qml/components/AgentComposer.qml      （新增）
src/ai_novel_studio/ui_qml/qml/components/AgentTextBlock.qml
src/ai_novel_studio/ui_qml/qml/components/AgentRunStatus.qml
src/ai_novel_studio/ui_qml/qml/components/ToolCallCard.qml
src/ai_novel_studio/ui_qml/qml/components/ChoiceCard.qml
src/ai_novel_studio/ui_qml/qml/components/TextDiffCard.qml
src/ai_novel_studio/ui_qml/qml/components/ConfirmationCard.qml
src/ai_novel_studio/ui_qml/qml/components/ContextReferenceChip.qml
src/ai_novel_studio/ui_qml/qml/components/qmldir
src/ai_novel_studio/ui_qml/qml/pages/WritingPage.qml
src/ai_novel_studio/ui_qml/qml/pages/MemoryLibraryPage.qml      （新增容器）
src/ai_novel_studio/ui_qml/qml/pages/AdvancedCreationPage.qml   （新增容器）
src/ai_novel_studio/ui_qml/qml/pages/qmldir
src/ai_novel_studio/ui_qml/bridge/dtos.py                       （Agent 时间线 DTO、选区引用 DTO）
src/ai_novel_studio/ui_qml/bridge/models/agent_timeline_model.py（新增）
src/ai_novel_studio/ui_qml/bridge/models/selection_reference.py  （新增）
src/ai_novel_studio/ui_qml/bridge/mock_novel_studio_facade.py   （Agent 事件、选区引用状态、导航收束）
src/ai_novel_studio/ui_qml/bridge/editor_bridge.py              （selection_reference_changed + 校验）
src/ai_novel_studio/ui_qml/editor_web/src/editor.ts             （选区上报）
src/ai_novel_studio/ui_qml/editor_web/src/editor-core.ts        （选区哈希/引用构造，纯函数可测）
tests/ui_qml/*                                                    （新增 agent/selection 测试 + 导航测试更新）
scripts/capture_frontend_*.py                                    （截图扩展）
docs/frontend/*                                                  （审计/实施/接线点）
```

## 7. 必须延期

- 真实 Agent 后端（`CreativeAgentPort`）；
- 真实 ChangeSet 执行（C3）；正文选区真实替换（C4）；新小说向导（C5）；
- 人物/记忆/审校页面完整迁移到记忆库/高级创作（C1 用容器页复用现有页面）；
- 完全独立安装（后端 Port 拆分，见第 10 节）；
- Agent 隐藏推理展示（禁止）。

## 8. 与后端重构的冲突面

- 零冲突：C1 不修改后端文件、不调用后端新接口；
- 唯一注意：独立仓库 Facade 顶层导入后端包（`application.*`/`domain.*`），
  C1 将做**最小可选导入**改造（后端缺失时 Mock 模式可运行、真实模式延迟注入），
  不复制后端代码、不改后端接口；
- 现有依赖后端的旧测试保留，在独立仓库标注为“需后端仓库运行”，不删除。

## 9. 需保留为行为合同的旧测试

- 项目打开/切章/保存/冲突（`test_project_wiring.py` 依赖后端 → 主仓库运行）；
- Facade 草稿端口/协调器/候选层（`test_draft_*.py`、`test_mock_facade.py` 大部分）；
- 只读列表/概览（`test_overview_counts.py`、`test_readonly_views.py`）；
- QML Shell 基础（`test_qml_shell.py` 中编辑器/保存/抽屉/主题等）；
- editor_web npm 全套（黄金样本/压力/核心）。

## 10. 独立前端边界建议（本轮只出方案）

```text
QML / Facade
    ↓
Frontend Port Protocol（ProjectWorkspacePort / DraftPort / CreativeAgentPort /
                        ReadonlyMemoryPort / AuditPort / SettingsPort）
    ↓
运行时注入 Backend Adapter（主程序注入；Mock 模式不依赖后端包）
```

C1 最小落地：把 Facade 顶层 `application/domain` 导入改为 try/except 可选导入，
并新增 `agent_backend_available` 风格标记；禁止复制后端代码到前端仓库。

## 11. 实施顺序与风险

1. 后端可选导入改造（让独立仓库可加载/可测）→ 低风险，先行；
2. 顶级导航收束（记忆库/高级创作/设置）→ 中风险（路由/测试），容器页复用旧页；
3. 正文减负（WritingPage 精简 + “···”菜单）→ 中风险（旧 QML 测试断言按钮），逐步更新测试；
4. Agent Dock（可拖宽度/收起/复位）→ 低-中风险（WebEngine 不覆盖：继续停靠布局）；
5. Agent 时间线模型 + 卡片组件（Loader/组件映射）→ 低风险，纯新增；
6. AgentComposer（多行/Enter/Shift+Enter/停止/引用 chip）→ 中风险（IME/按键测试）；
7. 选区引用协议（JS 上报 → Bridge 校验 → Facade 状态 → chip → Mock Agent TextDiffCard）；
8. Mock Agent 事件流（确定性、可停止）；
9. 测试/截图/文档 → 门禁后独立 commit。

风险集中在 2/3（旧测试合同）与 7（WebEngine 真机验证）；其余为纯前端新增。
