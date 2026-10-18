# AI Novel Studio Frontend C1.3：Agent 时间线纵向重叠修复

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 前置提交：`1a772fa`（C1.2 横向响应式）
> 性质：回归缺陷排查与修复，不进入 C2，不接真实 Agent 后端，不做视觉重构。

## 1. 只读审计（12 项问答）

按任务要求，先只读审计再修改。结论如下：

1. `ListView.delegate` 的根对象：`Loader`（`CreativeAgentPanel.qml`）。
2. delegate 的 `height` / `implicitHeight`：修复前均未显式设置，`height` 默认取
   `implicitHeight`，而 `Loader.implicitHeight` 跟随已加载项的 `implicitHeight`。
3. `Loader` 是否显式绑定 loaded item 高度：没有显式绑定，依赖 Loader 内置隐式
   高度传递（对其他卡片有效，见第 9 项）。
4. 动态加载后 delegate 高度是否会重算：对正确导出 `implicitHeight` 的组件有效；
   对不导出的组件恒为 0。
5. `AgentCard` 是否把内部 `ColumnLayout.implicitHeight` 传递到根节点：
   **没有**。内部 ColumnLayout 使用 `anchors.fill: parent`（由父高驱动），
   根节点没有任何 `implicitHeight` / `height`，默认值为 0。
6. `Flow` 换行后高度是否传递给卡片：`Flow` 本身能算出换行后的 `implicitHeight`，
   但 AgentCard 不导出它，因此无法到达 delegate。
7. 是否存在 `height: parent.height` / 错误 `Layout.fillHeight`：
   无显式 `height: parent.height`；`AgentCard` 没有错误 fillHeight。
8. 是否有组件只有 implicitHeight 而外层用固定 height：`AgentTextBlock /
   ToolCallCard / ChoiceCard` 有正确的 implicitHeight，且 Loader 正常继承；
   `AgentCard` 系（TextDiff / Confirmation / Form / ChangeSet）没有 implicitHeight。
9. `Loader.item` 高度变化是否触发外层重新布局：是，前提是 loaded item 导出
   implicitHeight（AgentTextBlock/ToolCallCard 实证成立）。
10. ListView 异常配置：无 `reuseItems`；`cacheBuffer` 仅测试钩子；`spacing: 8` 正常。
11. 哪类卡片最先出现高度错误：全部 `AgentCard` 系卡片（TextDiffCard /
    ConfirmationCard / FormCard / ChangeSetCard），复现时高度全部为 0。
12. C1.2 新增的 `AgentCard` 是否改变高度传播：是。C1.2 把四张卡片迁移到
    `AgentCard` 容器，但该容器未导出 implicitHeight，成为高度断点。

### 复现证据

修复前 harness（420px，7 项事件）：

```text
agentTextBlock   28px  OK
toolCallCard     34px  OK
textDiffCard      0px  BROKEN
confirmationCard  0px  BROKEN
formCard          0px  BROKEN
changeSetCard     0px  BROKEN
ListView contentHeight = 121（仅前两项 + 间距）
```

零高度卡片的内容仍会绘制（Text/Flow 可越过自身高度绘制），于是多张卡片叠在同一
纵向区域 —— 即真实运行中的纵向重叠。

## 2. 实际根因

`AgentCard.qml` 根节点未导出内容高度：

```qml
// 修复前
Rectangle {
    Layout.fillWidth: true
    implicitWidth: parent ? parent.width : 320
    // 没有 implicitHeight！
    ColumnLayout { anchors.fill: parent; ... }
}
```

内部 ColumnLayout 用 `anchors.fill` 反被父高驱动，父高又无来源，形成
“父依赖子、子依赖父”的断环，最终所有 AgentCard 系卡片高度恒为 0。

## 3. 修复内容（单一高度权威链）

```text
卡片内部内容 implicitHeight
    ↓  AgentCard 导出
AgentCard.implicitHeight = body.implicitHeight + 20（上下 margin）
    ↓  Loader 内置隐式高度传递（实证有效）
delegate Loader.height = implicitHeight（显式绑定，防回归）
    ↓
ListView 布局 / contentHeight
```

具体改动：

1. `AgentCard.qml`：
   - 外层 ColumnLayout 增加 `id: body`；
   - 根节点 `implicitHeight: Math.max(40, body.implicitHeight + 20)`。
2. `CreativeAgentPanel.qml`：
   - delegate 增加 `height: implicitHeight`，把“delegate 高度=loaded implicitHeight”
     写进绑定，成为可审计的单一权威；
   - 新增 `Connections { target: Facade.agentTimeline; onRowsInserted →
     positionViewAtEnd() }`，多轮任务自动跟随底部，不改变已有卡片几何。
3. 测试辅助 objectName：`AgentRunStatus → agentRunStatus`、
   `ChoiceCard → choiceCard`、`AgentComposer → agentComposer`、
   `SlidingDrawer → slidingDrawer`（供截图脚本驱动真实抽屉宽度）。

未改动 C1.2 的宽度规则（`delegate width = timeline.width - scrollbar - safe margin`），
未使用任何固定卡片高度，未用 `clip` 掩盖问题，未减少事件/文本。

## 4. 为什么 C1.2 测试没有发现

C1.2 新增的 `test_timeline_cards_stay_within_content_width` 只断言横向边界：

```python
card.x + card.width <= timeline right edge
```

零高度卡片宽度仍等于 delegate 宽度，横向断言全部通过，但纵向高度从未被验证。
这是“只验证没有越过右边界，没有验证二维位置”的典型盲区，由 C1.3 的几何测试补齐。

## 5. 新增几何断言

新文件 `tests/ui_qml/test_agent_timeline_geometry.py`（5 个测试）：

1. `test_all_card_kinds_have_positive_height_and_no_overlap`
   - 每种卡片高度 / implicitHeight > 0；
   - delegate 高度 ≥ loaded implicitHeight；
   - 按 y 排序后 `next_y >= prev_y + prev_h + spacing - 2`；
   - 最后一项底部 ≤ contentHeight + 1；横向仍不越界。
2. `test_flow_wrap_grows_card_and_keeps_buttons_disjoint`
   - 520px → 220px 收窄后 ChangeSetCard 高度不缩小（Flow 换行）；
   - 三个按钮矩形两两不重叠。
3. `test_long_text_cards_scroll_without_overlap`
   - 500 字级 diff、长工具说明、长表单、8 行来源、长用户消息；
   - 无横向溢出、无纵向重叠、contentHeight 可滚动；
   - 滚动到底后最后一项完整可见；输入区不被时间线覆盖。
4. `test_dynamic_append_keeps_rows_ordered`
   - 按真实顺序逐条追加 8 类事件，每次等待布局稳定后校验相邻项。
5. `test_multi_turn_no_overlap_autoscroll_and_old_buttons`
   - 连续 3 轮 Mock 任务；contentHeight 单调增长；
   - 自动滚动到底（contentY > 0）；
   - 第一轮旧卡片的“确认替换”仍可点击，item 状态变为 APPLIED。

截图脚本 `scripts/capture_frontend_c13_after.py` 保存前同样执行：
“所有 delegate 高度 > 0、相邻不重叠、最后一项底部 ≤ contentHeight”。

## 6. 是否影响横向响应式

不影响。宽度规则原样保留，C1.2 的 `test_timeline_cards_stay_within_content_width`
继续通过（360/420/520/300px）。本轮只新增高度链，两者解耦。

## 7. 测试结果

```text
独立前端测试：120 passed, 35 skipped
  （skip 均为后端依赖模块级 importorskip 与真实项目 QML 用例，与 C1.1/C1.2 相同）
主仓库集成测试：196 passed, 0 skipped
新增纵向布局测试：5 passed
ruff：通过
mypy（strict，局部 override）：通过
```

缩放模拟（offscreen，QT_SCALE_FACTOR）：

```text
100%（基准）：27 项 delegate，contentHeight == 最后一项底部，无重叠
125%（QT_SCALE_FACTOR=1.25）：同上，OK
150%（QT_SCALE_FACTOR=1.5）：同上，OK
```

> 说明：offscreen 无法真正切换 Windows DPI；`QT_SCALE_FACTOR` 仅验证缩放后布局
> 逻辑仍成立。真机 100%/125%/150% 目检仍需用户在 Windows 上运行
> `.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml` 确认。

## 8. 截图（docs/frontend/screenshots/）

修复前（真实 App.qml，三轮任务）：

- `c1.3-before-real-multi-turn.png`

修复后（真实 App.qml，三轮任务 + 几何断言后保存）：

- `c1.3-after-real-multi-turn-360px.png`
- `c1.3-after-real-multi-turn-420px.png`
- `c1.3-after-real-multi-turn-520px.png`
- `c1.3-after-long-diff.png`
- `c1.3-after-form-and-changeset.png`

生成脚本：

- `scripts/capture_frontend_c13_before.py`
- `scripts/capture_frontend_c13_after.py`

## 9. 修改文件

```text
src/ai_novel_studio/ui_qml/qml/components/AgentCard.qml
src/ai_novel_studio/ui_qml/qml/components/CreativeAgentPanel.qml
src/ai_novel_studio/ui_qml/qml/components/AgentRunStatus.qml     （objectName）
src/ai_novel_studio/ui_qml/qml/components/ChoiceCard.qml         （objectName）
src/ai_novel_studio/ui_qml/qml/components/AgentComposer.qml      （objectName）
src/ai_novel_studio/ui_qml/qml/components/SlidingDrawer.qml      （objectName）
tests/ui_qml/test_agent_timeline_geometry.py                     （新增，5 个测试）
scripts/capture_frontend_c13_before.py                           （新增）
scripts/capture_frontend_c13_after.py                            （新增）
docs/frontend/2026-08-03-frontend-c1-3-agent-timeline-height-fix.md
```

## 10. 遗留风险

- 真机 DPI 100%/125%/150% 目检未由代理完成，需用户在 Windows 真机确认；
- 自动滚动当前无条件跟随底部（chat 风格）；若后续需要“用户上翻时暂停跟随”，
  需增加滚动方向检测，属于后续增强；
- `AgentCard.implicitHeight` 依赖内容列隐式高度；若未来加入固定高度子组件
  （如视频/表格），需显式加入该子组件高度。

## 11. 是否建议合并

建议合并（由用户决定时机）：修复经独立与集成两套测试验证，C1.2 横向回归零，
C1.3 完成标准（横向不裁切 + 纵向不重叠 + 动态追加正常 + 多轮正常 +
几何自动测试覆盖）已满足；真机 DPI 目检为唯一人工确认项。
