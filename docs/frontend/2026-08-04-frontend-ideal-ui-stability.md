# AI Novel Studio Frontend：理想 UI 规范「当前阶段」稳定性实施

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 依据：《AI_Novel_Studio_理想UI方向与现有架构渐进式实现规范》
> 性质：只做规范第 15/18 节「当前阶段」的稳定性准备，不做 Visual V0 全面美化；未改后端。

## 1. 本轮范围

对照规范第 18 节「近期可以立即执行的小改动」逐项落地：

| 规范条目 | 本轮状态 | 落地位置 |
| --- | --- | --- |
| 5. ThemeProvider 继续作为唯一色彩来源 | 完成 | `theme_provider.py` 新增 `color.scrim`、`duration.panelFade`；`SlidingDrawer` 遮罩色改用 token |
| 3. AI Dock 开关几何瞬切 + 内容淡入 | 完成 | `AgentDock.qml` 移除 `Behavior on Layout.preferredWidth`，改为几何一步到位 + 面板内容淡入淡出 |
| 4. 拖动面板宽度松手提交（不实时 resize WebEngine） | 完成 | `AgentDock.qml` 拖动改为「预览线 1:1 跟随 → 松开一次性提交宽度」 |
| 6. AgentTimelineModel 增加 `update_item()` | 完成 | `agent_timeline_model.py` 新增精确 `dataChanged` 更新 |
| 7. 流式输出 33–50ms UI 合并预留 | 完成 | 新增 `streaming_timeline.py`（合并、run_id/序号防陈旧） |
| 2. WebEngine 明确背景 | C1.5 已做 | 本轮未改 |
| 1. NovelEditorView backgroundColor | C1.5 已做 | 本轮未改 |
| 9. 删除 F1/Mock 开发痕迹 | 延后 | 功能冻结后处理 |
| 8. Agent 卡片二维几何验证 | 已覆盖 | C1.2/C1.3 测试继续全绿 |

另按规范第 10.1 条，把左侧栏 `Behavior on Layout.preferredWidth` 一并移除（此前仅在 WebEngine 模式禁 Dock 动画，现在所有模式都禁止围绕 WebEngine 的几何动画）。

## 2. 改动的文件

### 源码

- `src/ai_novel_studio/ui_qml/qml/components/AgentDock.qml`
  - 移除 `Behavior on Layout.preferredWidth`，开关几何一步到位；
  - 面板内容 `opacity + scale(0.97→1)` 从右缘（`Qt.RightEdge`）入场，退出反向；
  - 拖动改为 `dragPointerX` 状态机：预览线 1:1 跟随，松开一次性提交；小于 3px 视为点击不改变宽度；
  - 所有动画可打断（`stop()` 后从当前值重定向）。
- `src/ai_novel_studio/ui_qml/qml/App.qml`：侧栏宽度移除动画；Dock 不再传 `animateWidth`。
- `src/ai_novel_studio/ui_qml/qml/components/SlidingDrawer.qml`：遮罩色改为 `Theme.tokens.color.scrim`。
- `src/ai_novel_studio/ui_qml/bridge/theme_provider.py`：新增 `color.scrim`、`duration.panelFade`（140ms）。
- `src/ai_novel_studio/ui_qml/bridge/models/agent_timeline_model.py`：新增 `update_item(item_id, **changes)`，单行 `dataChanged`，不再整表 reset。
- `src/ai_novel_studio/ui_qml/bridge/dtos.py`：`AgentTimelineItemDto` 增加 `run_id` / `sequence_number`（流式身份预留）。
- `src/ai_novel_studio/ui_qml/bridge/mock_novel_studio_facade.py`：Mock Agent 每轮生成唯一 `run_id` 与单调序号；`_replace_agent_item` 改用 `update_item()`。
- `src/ai_novel_studio/ui_qml/bridge/streaming_timeline.py`（新增）：33–50ms 合并缓冲，`accept_chunk` / `flush` / `drop_run`。

### 测试

- `tests/ui_qml/test_agent_timeline.py`：`update_item` 精确更新、run_id/序号身份；
- `tests/ui_qml/test_streaming_timeline.py`（新增）：合并、单次 dataChanged、陈旧/异 run 丢弃、drop_run、定时 flush；
- `tests/ui_qml/test_qml_shell.py`：Dock 一步到位 + 拖动预览/松手提交（含最小宽钳制、点击不改变宽度）；
- `tests/ui_qml/test_theme_provider.py` / `test_editor_web_page.py`：token 与 Dock 无宽度动画断言。

### 截图脚本

- `scripts/capture_frontend_ideal_ui_dock.py`（新增）：离屏断言 + 截图折叠/展开/拖动预览/提交/关闭五态。

## 3. 六个 design/animation skill 的应用与评审

### 3.1 animation-vocabulary（术语对齐）

本轮涉及的术语：**Fade in / Fade out**（面板内容进出）、**Drag**（预览线直接操控）、**Layout thrashing**（禁用宽度动画的根因，见规范 10.1）、**Asymmetric easing**（进入 140ms / 退出 120ms）、**Spatial consistency**（内容从右缘进出）、**Reduced motion**（`Facade.reduceMotion` 降级为静态切换）。

### 3.2 apple-design（交互原则）

- **响应**：拖动开始即显示预览线，反馈发生在 press 与拖动过程中，不是松手后；
- **直接操控**：预览线与指针 1:1（`dragPointerX`），并保留 grab 偏移（从 handle 位置换算宽度）；宽度在松手时一次提交，这是 WebEngine 相邻布局下对「1:1 几何」的正确折中（规范 10.1 优先于连续 resize）；
- **空间一致性**：面板从右缘（Dock 所在边）入场/退场，`transformOrigin: Qt.RightEdge`；
- **打断性**：所有 NumberAnimation 用 `stop()` 后从当前值重定向，不做 keyframes；
- **reduced motion**：时长归零，退化为静态 opacity/scale 切换（规范允许静态回退）。

### 3.3 emil-design-eng（频率与时长）

- Dock 开关属「Occasional」档 → 允许标准动画，但只保留 140/120ms 的 opacity+scale；
- 全部时长 ≤ 140ms（预算表 UI < 300ms）；
- 退出（系统响应）比进入更快（120ms vs 140ms），符合「release should be snappy」；
- 只动 `opacity` 与 `scale`（GPU 友好），宽度/高度类属性一律不动画；
- 删除的侧栏宽度动画属于「tens/day + WebEngine 相邻」→ 按「Remove or drastically reduce」处理。

### 3.4 find-animation-opportunities（机会与拒绝）

**Part 1 — 机会表**（本轮存活建议，均已实现）

| # | 位置 | 今天 | 目的 | 频率 | 建议动效 |
| --- | --- | --- | --- | --- | --- |
| 1 | `AgentDock.qml` 面板内容 | 几何瞬切后内容直接出现 | Preventing a jarring change | Occasional | `opacity 0→1` + `scale 0.97→1`，`transformOrigin: Qt.RightEdge`，140ms OutCubic |
| 2 | `AgentDock.qml` 拖动 handle | 拖动实时 resize WebEngine | Feedback / 直接操控 | Occasional | 2px accent 预览线 1:1 跟随，松手一次提交；无动画（直接操控） |

**Part 2 — 拒绝清单**

- `App.qml` 侧栏收起/展开：**拒绝——tens/day 且紧邻 WebEngine，几何动画 = layout thrash**；改为瞬时切换。
- Dock 宽度拖动实时跟随：**拒绝——每帧 resize WebEngine，触发黑边/卡顿**；用预览线代替。
- 导航切换页面过渡：**拒绝——规范明确 Visual V0 前不做全面美化**。
- 流光边框 / 玻璃材质：**拒绝——规范第 8/15 节明确延后到 Visual V1/V3**。

**Part 3 — 结论**：写作工具每周都会被高频使用，动效预算应极端克制；本轮唯一高杠杆动作是「删除围绕 WebEngine 的几何动画 + 用内容淡入替代」，已完成。

### 3.5 improve-animations（八类审计）

按 AUDIT.md 八类快速审计本轮 motion surface：

| 类别 | 结论 |
| --- | --- |
| 1. Purpose & frequency | Dock 开关 Occasional；宽度动画已删，无键盘触发动画 |
| 2. Easing & duration | 全部 OutCubic，≤140ms；无 ease-in、无裸 ease/linear |
| 3. Physicality & origin | 入场 0.97→1，origin 右缘；无 scale(0) |
| 4. Interruptibility | 动画 stop/start 可重定向；无 keyframes |
| 5. Performance | 只动 opacity/scale；几何瞬切；无 `transition: all` |
| 6. Accessibility | reduceMotion → 0ms 静态切换（与仓库既有约定一致） |
| 7. Cohesion & tokens | 时长/颜色全部走 ThemeProvider；无新增硬编码值 |
| 8. Missed opportunities | 见 3.4；其余（玻璃、流光）属 Visual V1+，规范延后 |

### 3.6 review-animations（必填表格与结论）

**Part 1 — Findings table**

| Before | After | Why |
| --- | --- | --- |
| `AgentDock` 面板淡出 `Easing.InCubic` | `Easing.OutCubic`，120ms（`duration.fast`） | 进出都该 ease-out；ease-in 延迟用户正在注视的瞬间，显得迟钝 |
| 进入/退出同为 140ms 对称 | 进入 140ms（`panelFade`）/ 退出 120ms（`fast`） | 系统响应应比进入更干脆（asymmetric timing） |
| 纯 opacity 淡入，无初始形变 | `opacity 0→1` + `scale 0.97→1`，`transformOrigin: Qt.RightEdge` | 没有东西凭空出现；材质从 Dock 所在边缘「抵达」，空间一致 |
| Dock 宽度 `Behavior on Layout.preferredWidth`（220ms） | 移除 Behavior，几何一步到位；App 侧栏同样移除 | 围绕 WebEngine 动画 `width` 触发每帧布局/合成，黑边+卡顿 |
| 拖动实时 `root.currentWidth = ...` | `dragPointerX` 状态机：预览线跟随，松手一次提交 | 连续反馈但不制造每帧 WebEngine resize |
| reduceMotion 时长 0 | 保持 0（静态 opacity/scale 切换） | 与仓库既有约定一致；规范允许静态回退 |

**Part 2 — Verdict**

- **Feel-breaking regressions**：无（无 ease-in、无 >300ms、无 scale(0)）；
- **Missed simplifications**：侧栏宽度动画已删除；Dock 拖动已从实时 resize 简化为预览线；
- **Performance**：只动 `opacity`/`scale`；无 `transition: all`；
- **Interruptibility & timing**：可打断；进入/退出非对称；
- **Origin & cohesion**：右缘 origin；token 统一；
- **Accessibility**：`reduceMotion` 静态回退。

**结论：Approve。** 无 feel-breaking 回归，无应删而未删的动画，时长与 easing 在预算内，打断性、reduced-motion 均已处理。真实手感建议按 STANDARDS 用慢速回放复核一次（本次离屏验证覆盖几何与状态断言，动画观感留待真机确认）。

## 4. 验证结果

### 离线测试（frontend-clean 自身）

```text
pytest tests/ui_qml          138 passed, 35 skipped（后端不可用部分跳过）
ruff check src tests scripts  All checks passed
mypy                          Success: no issues found in 38 source files
npm test                      129 passed
npm run typecheck / build     通过，dist 产物已重建
```

### 主仓库集成（非破坏性桥接，c9a2 venv）

```text
pytest tests/ui_qml          214 passed, 0 skipped
```

### 真机 WebEngine（本机 Windows，`--disable-gpu` 软渲染）

```text
verify_webengine_edges.py --mode interact  OK interact scale=1.0
（20 次 AI 开关、20 次切章、Dock 360/420/520px；无黑边断言通过）
```

## 5. 截图

`docs/frontend/screenshots/`（离屏软件渲染，Dock 五态）：

- `ideal-ui-dock-collapsed.png` — 折叠展开标签；
- `ideal-ui-dock-open.png` — 420px 打开，内容淡入完成；
- `ideal-ui-dock-drag-preview.png` — 拖动中：Dock 仍 420px，右侧预览线跟随；
- `ideal-ui-dock-committed.png` — 松手提交 480px；
- `ideal-ui-dock-closed.png` — 关闭回 34px。

真机截图（WebEngine 模式）沿用 C1.5：`c1.5-startup.png` / `c1.5-ai-open.png` / `c1.5-ai-closed.png`（本次 interact 已重新生成覆盖）。

## 6. 延期事项与未来接线点

### 延后（按规范，非本轮范围）

- Visual V0 样板页（GlassSurface / PaperSurface / 流光边框 / Safe-Balanced-Premium）；
- Visual V1 静态材质统一（导航轨、章节栏、AI 面板玻璃质感）；
- Visual V2 真实 Agent 流式（当前只预留 buffer 与身份字段，未接模型流）；
- Visual V3 流光 / 状态边框；
- Visual V4 Windows Mica；
- 删除 F1/Mock 开发痕迹（功能冻结后）；
- 页面级导航过渡。

### 未来接线点（记录于前端文档，不触后端）

1. **Agent 流式接入**：真实模型事件需携带 `run_id` / `item_id` / `sequence_number` / `chapter_id`；离散结构事件走 `append_item()`，token 块走 `StreamingTimelineBuffer.accept_chunk()`（33–50ms 合并 → `update_item()`）；切章/取消后对旧 run 调用 `drop_run()` 并丢弃迟到事件。
2. **实时宽度拖动**（可选）：若未来要实时拖动而非预览线，必须节流（≥100ms 合并）或拖动期间暂停 WebEngine 重绘。
3. **VisualQualityProfile**：Balanced 默认，Safe/Premium 回退，接入 `Facade.reduceMotion` 与硬件检测。
4. **reduced-motion**：保持 0ms 静态回退约定；若未来引入流光，需按规范 8.1 退化为静态高亮。
