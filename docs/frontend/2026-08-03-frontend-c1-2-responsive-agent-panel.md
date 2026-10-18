# AI Novel Studio Frontend C1.2：CreativeAgentPanel 响应式布局修复

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 性质：公共布局修复，不改变功能范围、不接真实后端。

## 1. 问题

AI 面板在窄宽度（360–420px）下右侧内容被裁切：

- ListView delegate 直接使用 `timeline.width`，未扣除垂直 ScrollBar 宽度，
  卡片右缘伸到滚动条下方；
- 卡片内容用固定宽度/不换行文本，操作按钮行用不可换行的 RowLayout；
- 快捷命令行在窄面板下溢出。

## 2. 修复方案（公共容器优先，不做逐按钮魔法数字）

### 2.1 共享卡片容器 `AgentCard.qml`

新增基础组件，统一承载所有时间线卡片：

- `Layout.fillWidth: true` + `implicitWidth: parent ? parent.width : 320`，
  卡片只跟随 delegate 宽度；
- 标题区与内容区均为 `ColumnLayout`，所有直接子项继承统一的
  `fillWidth + WordWrap` 规则；
- 默认属性透传到内容列，卡片内部不再各自声明 `width/radius/color/border`。

### 2.2 CreativeAgentPanel 公共宽度规则

```qml
property int scrollbarWidth: 10
property int contentSafeMargin: 12

delegate width = max(0, timeline.width - scrollbarWidth - contentSafeMargin)
```

一条规则覆盖全部卡片；禁止任何卡片使用超过该可用区域的固定宽度。
`ScrollBar.policy = AsNeeded`，不增加横向滚动条，`clip: true` 保留。

### 2.3 操作按钮行：RowLayout → Flow

`TextDiffCard / ConfirmationCard / FormCard / ChangeSetCard` 的按钮行统一改为
`Flow { Layout.fillWidth: true; Layout.alignment: Qt.AlignRight }`，
空间不足时自动换行；`AgentComposer` 快捷命令行同样改为 Flow。

### 2.4 长文本统一换行

- `TextDiffCard / ConfirmationCard / FormCard` 正文：`Layout.fillWidth + WordWrap`；
- `ChangeSetCard` 全部值列（目标/修改前/修改后/风险/来源）加
  `Layout.fillWidth + WordWrap`；
- `ToolCallCard` 从 `ElideRight` 改为 `WordWrap`。

### 2.5 AgentDock 默认尺寸

- `defaultWidth: 420`、`minWidth: 360`（加宽是辅助手段，不是修复本身）。

### 2.6 诊断钩子

- `timelineCacheBuffer`、`timelineDelegateFullWidth` 仅供测试/截图脚本
  驱动布局断言与 before/after 对比，正常运行均为默认值。

## 3. 测试

新增 `test_timeline_cards_stay_within_content_width`：

- 在 360 / 420 / 520 / 300px 面板宽度下逐张驱动 6 类卡片进入视图；
- 断言每张卡片 `x + width` 不超过时间线可见右缘（含 12px 安全边距）；
- 断言时间线本身不越过面板右缘减 12px；
- 不通过放宽阈值掩盖溢出；找不到组件即失败。

```text
独立前端：115 passed, 35 skipped（skip 均为后端依赖，与 C1.1 相同）
集成环境：191 passed, 0 skipped
ruff / mypy：通过
```

## 4. 截图（docs/frontend/screenshots/）

### 修复前（模拟旧 delegate 宽度规则）

- `c1.2-before-360px.png`
- `c1.2-before-420px.png`
- `c1.2-before-520px.png`

### 修复后

- `c1.2-after-360px.png`
- `c1.2-after-420px.png`
- `c1.2-after-520px.png`

生成脚本：

- `scripts/capture_frontend_c12_before_after.py`（同一时间线、同宽度、同窗口尺寸，
  仅 delegate 宽度规则不同，可逐像素对比）；
- `scripts/capture_frontend_c12_panel_widths.py`（修复后 360/420/520 常规截图）。

Windows 100%/125%/150% 缩放下，布局基于逻辑像素与 Flow 换行自适应，不引入
新的固定像素依赖；建议在真机各缩放档目检（offscreen 截图不受 DPI 缩放影响）。

## 5. 修改文件

```text
src/ai_novel_studio/ui_qml/qml/components/AgentCard.qml        （新增）
src/ai_novel_studio/ui_qml/qml/components/CreativeAgentPanel.qml
src/ai_novel_studio/ui_qml/qml/components/TextDiffCard.qml
src/ai_novel_studio/ui_qml/qml/components/ConfirmationCard.qml
src/ai_novel_studio/ui_qml/qml/components/FormCard.qml
src/ai_novel_studio/ui_qml/qml/components/ChangeSetCard.qml
src/ai_novel_studio/ui_qml/qml/components/ToolCallCard.qml
src/ai_novel_studio/ui_qml/qml/components/AgentComposer.qml
src/ai_novel_studio/ui_qml/qml/components/AgentDock.qml
src/ai_novel_studio/ui_qml/qml/components/AgentTextBlock.qml
src/ai_novel_studio/ui_qml/qml/components/qmldir
tests/ui_qml/test_qml_shell.py
scripts/capture_frontend_c12_before_after.py                  （新增）
scripts/capture_frontend_c12_panel_widths.py                  （新增）
docs/frontend/2026-08-03-frontend-c1-2-responsive-agent-panel.md
```

## 6. 后续

- 真机 100%/125%/150% 缩放下目检（offscreen 无法模拟 DPI 缩放）；
- 若后续引入更窄的抽屉宿主，复用同一 delegate 宽度规则即可，无需改卡片。
