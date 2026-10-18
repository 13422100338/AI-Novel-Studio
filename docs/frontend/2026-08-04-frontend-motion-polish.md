# AI Novel Studio Frontend：动效审查与打磨（Motion Polish）

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 使用技能：`animation-vocabulary`、`apple-design`、`emil-design-eng`、
> `find-animation-opportunities`、`improve-animations`、`review-animations`

## 1. Recon（动效面清单）

- **栈**：PySide6/QML（QtQuick.Controls）+ 内嵌 WebEngine（Tiptap 编辑器）。
- **动效位置**：全部集中在 `ui_qml/qml/**`：`Behavior on`（宽度/透明度/x/颜色）、
  `NumberAnimation`、`ColorAnimation`、`SequentialAnimation`；
  `editor_web` 无任何 CSS transition/animation（静态主题变量）。
- **约定**：时长 token 已存在（`fast 120 / normal 180 / panel 220`，均 < 300ms）；
  `Facade.reduceMotion` 已在多处接入；**没有任何 easing 约定**（QML 默认线性）。
- **个性**：专业写作工具，应保持 crisp & fast，克制、无 bounce。
- **频率图**：导航/按钮 = 每天数十次；抽屉/侧栏/面板 = 偶尔；Agent 事件 =
  偶尔；主题切换 = 用户主动、低频。

## 2. review-animations 审计表（修复前 → 修复后）

| Before | After | Why |
| --- | --- | --- |
| `AppButton` 按压仅变色，无 scale 反馈 | `scale: pressed ? 0.97 : 1.0`，`Behavior on scale` 120ms `Easing.OutCubic` | 按压反馈是最高杠杆项（emil/apple：反馈发生在 pointer-down）；scale 属 GPU 属性 |
| `IconButton` hover/选中颜色瞬变、无按压反馈 | `Behavior on color` 120ms OutCubic + 按压 scale 120ms | 与 AppButton 同一套反馈语言（Cohesion） |
| `AgentRunStatus` 无限脉冲无视 `reduceMotion` | `running: busy && !Facade.reduceMotion` | 无障碍：reduce motion 时保留状态色、移除循环运动（apple-design §14） |
| `SlidingDrawer` / `AgentDock` / 侧栏动画用 QML 默认 linear | 全部补 `Easing.OutCubic` | 内置 linear 太弱；入场/折叠应 ease-out（AUDIT.md easing 决策序） |
| 选区引用 Chip 瞬间出现/消失 | 150ms 淡入淡出，`Easing.OutCubic` | 防跳变（teleporting state） |
| 新时间线卡片瞬间出现 | 150ms 淡入 + `scale 0.98→1`，不动 height | 列表项无桥接入；纯装饰、不阻塞、不触碰 C1.3 高度链 |

## 3. find-animation-opportunities 门禁

### 幸存项（按杠杆排序）

| # | Location | Today | Purpose | Frequency | Suggested motion |
| --- | --- | --- | --- | --- | --- |
| 1 | `AppButton.qml:20` | 无按压反馈 | Feedback | Tens/day | `scale 0.97`，120ms `Easing.OutCubic`（near-imperceptible，符合频率档） |
| 2 | `IconButton.qml` | 颜色瞬变、无反馈 | Feedback | Tens/day | 同上 + 颜色 120ms |
| 3 | `ContextReferenceChip` + `AgentComposer` | 瞬间出现 | Preventing a jarring change | Occasional | 150ms 淡入淡出 |
| 4 | 时间线 delegate（`CreativeAgentPanel.qml`） | 瞬间出现 | Preventing a jarring change | Occasional | 150ms fade + scale(0.98) |

### 被拒候选（必须记录）

- `GenerationConfigDialog` 开合 —— **拒绝**：Qt `Dialog` 自带平台默认过渡，无需自研。
- `StatusChip` tooltip —— **拒绝**：单例 tooltip，300ms 标准延迟已足够，无需动画。
- `editor_web` 主题/工具面 —— **拒绝**：高频编辑面，克制正确（apple-design：
  高频动作不加动效）。
- AgentDock 宽度动画 —— **接受但不修**：`Layout.preferredWidth` 是布局属性动画，
  非 GPU-only；但这是 QML 布局单元格的合理实现方式且低频，标记 LOW 保留。

## 4. 实现明细

- `AppButton.qml`：`MouseArea` 命名 `mouseArea`；`scale` 绑定按压；新增
  `Behavior on scale`（120ms OutCubic）；颜色 Behavior 补 OutCubic。
- `IconButton.qml`：新增颜色与 scale 两个 Behavior，绑定按压 scale。
- `AgentRunStatus.qml`：脉冲动画 `running: root.busy && !Facade.reduceMotion`。
- `SlidingDrawer.qml`：dim 透明度与 x 滑动均补 `Easing.OutCubic`。
- `App.qml`：侧栏折叠补 `Easing.OutCubic`。
- `AgentDock.qml`：宽度折叠补 `Easing.OutCubic`。
- `ContextReferenceChip.qml`：根节点 `Behavior on opacity`（150ms OutCubic）；
  `AgentComposer.qml` 的引用改为 `opacity: hasSelectionReference ? 1 : 0` +
  `visible: opacity > 0.01`。
- `CreativeAgentPanel.qml`：delegate 初始 `opacity: 0, scale: 0.98`，`onLoaded`
  末尾置 1；两个 Behavior 均 150ms OutCubic、尊重 `reduceMotion`；只动
  opacity/scale，不触碰 height（C1.3 几何保证）。

所有新增动画均 ≤ 220ms、只动 transform/opacity、尊重 `Facade.reduceMotion`。

## 5. 验证结果

```text
独立前端测试：120 passed, 35 skipped（skip 均为后端依赖，同前）
主仓库集成测试：196 passed, 0 skipped
ruff：通过；mypy（strict）：通过
C1.1 截图链：7/7 通过组件断言
C1.2 before/after + panel widths：全部生成
C1.3 after 几何断言截图链：5/5 通过
```

截图脚本修正：`capture_frontend_f1_screenshots.py` 的选区 chip 断言改为
“边 pump 边等入场动画完成”的轮询（offscreen 动画只随事件循环推进），
断言强度不变——组件最终必须可见，否则失败退出。

## 6. 风险

- offscreen 无法验证真实手感；按压 scale 与淡入的真实“感觉”需真机目检
  （`python -m ai_novel_studio.ui_qml`，可按 apple-design §17 放慢观察）。
- 时间线卡片入场是纯装饰；若未来启用 ListView 复用（`reuseItems`），
  `onLoaded` 只触发一次，复用实例不会重放动画（可接受，属于避免干扰）。

## 7. Verdict（review-animations 格式）

**Approve** —— 无 feel-breaking 回归：所有动效 ≤ 220ms、ease-out、
只动 transform/opacity、尊重 reduceMotion；未给高频动作加动效；
editor_web 保持克制。唯一 LOW 项（AgentDock 布局属性动画）为 QML 布局单元格
的合理实现，已记录不修。
