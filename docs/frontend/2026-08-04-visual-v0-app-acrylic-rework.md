# Visual V0 应用内 Acrylic 重做交付报告

> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 依据：《AI_Novel_Studio_Visual_V0实验页问题诊断与下一版重做要求.md》
> 性质：仅重做独立样板页 `VisualLab.qml`（`--visual-lab`）；正式 Shell、
> 后端、WebEngine 全部未改动。

## 1. 原实验页为何无法验证目标效果

- 旧布局是“组件陈列室”（左侧玻璃演示 + 中央正文 + 右侧独立卡片 + 底部
  按钮样板 + 顶部调试开关），不是产品布局，无法验证材质在真实四栏结构中
  的表现；
- 背景内容极弱（浅米色 + 极弱渐变），即使执行模糊，“模糊前后”肉眼无差异，
  无法证明 Acrylic 生效；
- Agent 卡片直接浮在窗口右侧，脱离 AI 面板宿主，破坏层级；
- 顶部调试开关占据视觉主体，干扰主画面观察。

## 2. 黑色区域的根因

旧版在系统 Mica 生效时把 `ApplicationWindow` 设为透明，QML 只在部分区域
绘制内容，透明窗口 + 未绘制区域暴露为纯黑：

```text
窗口透明
↓
BackdropLayer / 面板未覆盖的区域
↓
QML 未绘制 → 暴露默认清屏色 → 纯黑
```

`DwmSetWindowAttribute()` 返回 S_OK 只证明属性被接受，不能证明 Qt 客户区
合成链路让出了背景。本轮结论：**应用内不透明方案下不会出现黑色裸露区**，
系统 Mica 降级为可选实验（默认关），其视觉验收必须用真机截图，不以 API
返回值为依据。

## 3. BackdropLayer 覆盖结构

```text
ApplicationWindow（不透明，color = bgCanvas）
└── BackdropLayer（anchors.fill: parent，覆盖全窗口）
    ├── 主题渐变（paper / light / dark）
    ├── 低饱和冷暖色光团 + 极淡几何 + 手稿卡轮廓
    ├── 极轻噪声
    └── 可选 Mica wash（仅实验开关开启时）
```

- 最底层始终有 `Theme.tokens.color.bgCanvas` 实色回退，透明窗口只在 Mica
  实验开启且质量档非 Safe 时出现；
- 自动断言（截图脚本 + 测试）：`x==0, y==0, width==window.width,
  height==window.height`；窗口任意采样点不得为纯黑（<12 亮度）。

## 4. Acrylic 捕获链

```text
BackdropLayer（应用内专用背景源）
  ↑ sourceItem
AcrylicSurface（AI 面板）
  ├── ShaderEffectSource(sourceRect = 面板在背景层中的映射)
  ├── MultiEffect blur（Balanced blurMax 24 / Premium 40）
  ├── luminosity → tint → noise → highlight border
```

要求落实：

- `sourceItem` 只指向 BackdropLayer；不捕获面板自身/正文/Agent 卡片/
  WebEngine；
- `sourceRect` 与面板位置一致（`mapToItem` + 显式重算），Resize 后仍正确；
- 隐藏时关闭 capture（`enabled: effectActive`）；Safe 档完全关闭 Blur；
- 不在动画期间修改 `blurMax`。

## 5. PaperSurface 与 AcrylicSurface 的视觉差异

| 维度 | PaperSurface（正文） | AcrylicSurface（AI 面板） |
| --- | --- | --- |
| 不透明度 | 完全不透明 | 半透明（tint 0.62） |
| 底色 | 更暖的纸白（paperFill） | 中性 tint + 背景透出 |
| 纹理 | 轻纸张噪声 | 玻璃噪声 + 顶部内高光 |
| 阴影 | 柔和静态阴影 | 玻璃厚度阴影 |
| 模糊 | 无 | MultiEffect 实时模糊 |

正文区域在视觉上明显“更稳定、更安静、更实”；左右面板通过模糊后的背景
轮廓表达空间层次。

## 6. 质量档新定义

三档共享同一窗口、同一背景、同一布局、同一组件结构，只改强度：

| 档位 | Blur | Noise | 阴影 | 面板 |
| --- | --- | --- | --- | --- |
| Safe | 关闭 | 关闭 | 静态 | 实色 |
| Balanced（默认） | 轻度（blurMax 24） | 静态 | 少量 | Acrylic |
| Premium | 高质量（blurMax 40） | 更细 | 更精致 | Acrylic |

不再使用 `Safe=无 DWM / Balanced=Mica / Premium=Desktop Acrylic` 作为
质量档主体。Mica 实验开关默认关闭，位于实验控制面板内。

## 7. 实验控制面板

新增 `ExperimentControlPanel.qml`（右侧抽屉），主画面只保留标题和
“实验控制”入口。面板包含：

- 主题：paper / light / dark；
- 质量：safe / balanced / premium；
- 动效开/关（reduceMotion）；
- 系统 Mica 实验开关（默认关，调用 `BackdropBridge.apply()`，显示结果）；
- 调试叠加：背景原图 / sourceRect / blur 区域。

## 8. 自动测试结果

```text
pytest（独立前端）   157 passed, 35 skipped
ruff / mypy          通过
```

新增/更新断言（诊断文档 §13）：

- BackdropLayer 覆盖全窗口（x/y/width/height）；
- 窗口采样无纯黑裸露区（Safe/Balanced/Premium 各验一次）；
- 主面板（Acrylic、Paper）全部位于窗口边界内；
- Acrylic sourceItem == BackdropLayer，captureRect 与面板几何一致；
- Safe 关 Blur、Balanced/Premium 开 Blur；
- 切换质量档布局几何不变、不出现黑块；
- 实验面板开/关、主题/质量按钮联动；Mica 默认关闭。

## 9. 真机截图

`docs/frontend/screenshots/`：

```text
visual-v0-rework-safe.png
visual-v0-rework-balanced.png
visual-v0-rework-premium.png
visual-v0-rework-paper.png
visual-v0-rework-dark.png
visual-v0-rework-resized.png
```

截图前自动断言全窗口覆盖与无纯黑区域（`scripts/capture_frontend_visual_lab.py`）。
离屏截图已通过；真机视觉以 `--windowed` 截图 + 用户确认为准。

## 10. 遗留问题

- 真机视觉（玻璃与纸张的层次、模糊柔化程度）仍需用户确认；
- Mica 实验在任何环境都默认关闭；若启用，仍需真机截图确认合成链路；
- 当前实验页为静态数据，未接 Facade/WebEngine，正式接入顺序见
  《玻璃化 UI 路线纠偏》文档 §11。

### 10.1 追加修复（2026-08-04）：实验控制改为顶部折叠条

真机反馈：右侧抽屉 + 全屏遮罩与 AI 助手面板“叠在一起”，且关闭困难。

- 根因：320px 抽屉从右缘覆盖 AI 面板（360px 列）大部分区域，加上全屏
  scrim 压暗，视觉上像叠层；遮罩/关闭按钮点击在真机上感知不可靠；
- 修复：`ExperimentControlPanel` 从“右侧抽屉 + 遮罩”改为**顶部折叠控制条**
  （诊断文档 §10 允许的“折叠区域”）：展开时四栏主体整体下移，不覆盖任何
  面板；关闭按钮标注“关闭（Esc）”，并支持 `Escape` 键关闭；
- 自动测试新增 `test_experiment_panel_never_covers_ai_panel`：控制条与
  AI 面板在窗口坐标系中零重叠；展开状态下全窗口无纯黑像素；
- 视觉复核（atlas-vision）：sidebar + main + right panel 结构完整，AI
  面板可见。

### 10.2 追加（2026-08-04）：背景光团 / FPS·渲染后端 / 主题黑块检查

按诊断文档补齐剩余要求：

- **§6.3 背景内容**：`BackdropLayer` 将低饱和色块升级为明确的
  「左上暖金色光团（warning 低 alpha）+ 右上淡蓝紫光团（thinkingA 低
  alpha）+ 中下灰蓝柔光（textSecondary 低 alpha）+ 极淡圆环/斜线几何
  轮廓」，全部低对比、颜色走 Theme tokens，让 Acrylic 模糊“前后差异”
  可感知；
- **§10 调试控制台**：实验控制条新增「FPS + 渲染后端」显示（VisualLab
  通过 `onFrameSwapped` 计数、1s 窗口估算 FPS；bootstrap 暴露
  `RenderBackendInfo`，真机显示 d3d11/opengl 等实际后端）；
- **§13.5**：新增 `test_theme_switch_produces_no_black_blocks`，遍历
  paper/light/dark 切换后截图断言无纯黑像素。

验证：前端 pytest 159 passed / 35 skipped；c9a2 集成 235 passed；
ruff / mypy 通过；六张 `visual-v0-rework-*.png` 重新生成并通过全窗口
覆盖 + 无纯黑断言。

### 10.3 追加（2026-08-04）：四类真机反馈修复

真机反馈与修复：

1. **只有 AI 栏随档位变化** → 导航轨、章节栏改为 `AcrylicSurface`
   （`labNavRail` / `labChapterSidebar`，`sourceItem: backgroundLayer`），
   三档现在同时作用于导航轨、章节栏、AI 面板；正文 PaperSurface 保持
   不透明（设计如此）。新增
   `test_quality_tiers_change_nav_sidebar_and_ai_glass`。
2. **Balanced 与 Premium 看不出区别** → 根因是 tint 基色（#FBF8F0）与
   背景几乎同色，alpha 差异被稀释；且 AI 面板下方背景缺少可辨认内容，
   blur 强弱无参照。修复：
   - 档位差距拉大：Blur 12 vs 56，tint 0.78 vs 0.42，Premium 微提亮；
   - BackdropLayer 在 AI 面板后方新增「可辨认手稿块 + 暖色点缀」，
     让 Premium（更透）能看到被模糊的背景内容，Balanced（更实）接近
     半透明面板（像素验证：AI 面板空带高频能量 Safe 0 / Balanced 0.35 /
     Premium 0.94，档位差异可测）。
3. **Mica 开关导致背景变黑** → `requestMica()` 失败时仍发送
   `micaChanged(true)`，窗口被无条件设为透明。修复：仅当
   `BackdropBridge.apply()` 返回成功才切透明；失败保持不透明、开关弹回
   关闭并显示「不可用」。新增 `test_mica_failure_keeps_window_opaque`。
4. **三个调试开关无效果** → 面板内点击只改了面板自身属性，单向绑定
   传不回 VisualLab。修复：新增 `debugBackdropToggled` /
   `debugSourceRectToggled` / `debugBlurRegionToggled` 信号回传。
   新增 `test_debug_overlay_toggles_propagate_to_window`。

验证：前端 pytest 162 passed / 35 skipped；c9a2 集成 238 passed；
ruff / mypy 通过；六张截图重新生成并通过断言。

## 11. 是否建议接入正式 Shell

暂不接入。先由用户在真机确认本版应用内 Acrylic 视觉与稳定性；通过后再按
纠偏文档 Step 6 性能门禁评估正式三栏接入（导航轨、章节栏、AI 面板统一
捕获同一 BackdropLayer；WebEngine 保持不透明并明确背景色）。
