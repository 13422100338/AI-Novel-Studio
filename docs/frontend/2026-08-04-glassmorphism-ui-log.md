# AI Novel Studio 玻璃化 UI（Glassmorphism）思路与过程记录

> 分支：`codex/frontend-agent-c1`
> 状态：**未达成用户目标，已暂停（2026-08-04）**。实验页的“应用内实时
> Acrylic”已可用；但“底板透出桌面壁纸”的系统 Mica 路线在真机上仍
> 未达到预期视觉效果（详见 §5 诊断与 §7 遗留问题）。本文档是日后恢复
> 该方向时的完整思路记录。
> 工作树：`<local-workspace>`

## 1. 目标与约束

### 1.1 用户需求（按时间澄清后的最终版）

1. Visual V0 样板页的玻璃效果“一般般”，要求联网调研玻璃化（Glassmorphism）
   经验与技术后再返工；
2. 关键澄清：**底板（窗口底层）可以微微透出程序后面的图像（桌面壁纸）**；
3. 关键澄清：**各个面板要有玻璃质感，但不要透出程序后面的图像**；
4. 正式界面（App.qml / NavigationRail / CreativeAgentPanel 等）不得改动，
   只做 `--visual-lab` 独立实验页；
5. 质量档 Safe / Balanced / Premium 必须可回退（规范 11）；
6. 前后端保持隔离；改动只落在 frontend-clean worktree。

### 1.2 本轮可接受范围

- 实验页可引入系统级材质（Mica / Desktop Acrylic）评估方向；
- 正式 Shell 不做透明窗口 / 系统背板（WebEngine 风险，见 §7.3）；
- 所有高级效果失败时静默回退到普通主题色。

## 2. 联网调研结论（返工依据）

### 2.1 NNGroup《Glassmorphism: Definition and Best Practices》

- 玻璃态 = **不透明度 × 背景模糊**，两个特征缺一不可；
- 仅做半透明 + 边框 + 噪声、没有模糊，看起来只是普通半透明面板
  （这正是第一版 `GlassSurface`“一般般”的根因）；
- 模糊要足够强（约 25–100px），复杂背景上效果更明显；
- 文本必须满足对比度；可让用户调整透明度（对应 Safe/Balanced/Premium）。

### 2.2 Qt 官方博客《Qt Quick and Blurred Panels》

- 模糊的是**面板背后的内容**，不是面板本身；
- 简单场景：`ShaderEffectSource(sourceItem=背景层, sourceRect=面板区域)`
  + `MultiEffect(blurEnabled, autoPaddingEnabled:false, blurMax)`；
- 高级场景：`maskEnabled/maskSource`（layer 化圆角矩形）实现非矩形模糊；
- 性能：模糊像素越少越好；`autoPaddingEnabled:false` 防止效果跑出窗口。

### 2.3 PyHuskarUI `HusAcrylic.qml`（Fluent Acrylic 分层）

- 顺序：捕获背后 → `MultiEffect blurMax≈32` → 亮度层（luminosity）
  → 色调层（tint，opacity≈0.65）→ 平铺噪声 PNG（opacity≈0.02）；
- `sourceRect` 必须按组件在源层坐标系中的位置映射。

### 2.4 Qt MultiEffect 文档

- `blur: 0..1`，`blurMax` 有效 2–64（默认 32）；`saturation/brightness`
  为 0 时无变化；
- `maskSource` 可指向 `layer.enabled` 的 Item；
- 性能：blur/shadow 最重；不在动画中改 `blurMax`/`autoPaddingEnabled`；
  空闲时关闭效果（`enabled:false`）；
- 离屏 software 后端也能渲染 MultiEffect（本机 Qt 6.11.1 已验证）。

### 2.5 微软 DWM 系统背板（透壁纸的关键 API）

- `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE=38)`；
- `DWMSBT_MAINWINDOW (2)` = Mica（整窗后壁纸模糊采样，材质低调）；
- `DWMSBT_TRANSIENTWINDOW (3)` = Desktop Acrylic（更亮）；
- `DWMSBT_TABBEDWINDOW (4)` = Mica Alt；
- `DWMSBT_NONE (1)` = 关闭；
- 要求 Windows 11 build 22621+；此前需用未公开的 `DWMWA_MICA_EFFECT`。

### 2.6 社区线索（部分未验证）

- win32mica：Win32 应用透明背景要求“extended composition”，Mica 行为不保证；
- AutoHotkey / MicaForEveryone 线索：窗口**保持不透明**、背景纯黑时，
  DWM 会用 Mica 替换黑色像素——“不透明窗口 + 纯黑背景”是一条备选路径；
- Qt 论坛：QML 透明窗口 + Mica 有白块、resize 后才透明等怪癖
  （“phantom white box”、6.10/6.11 均有报告）。

## 3. 两条技术路线

| 路线 | 原理 | 现状 |
| --- | --- | --- |
| A. 应用内实时 Acrylic | `ShaderEffectSource` 捕获应用内背景层 → `MultiEffect` 模糊 | **可用**（实验页） |
| B. 系统级 Mica / Desktop Acrylic | DWM 在窗口后面绘制壁纸模糊 | DWM 调用成功，**视觉未通过** |

最终用户目标对应 **B（底板透壁纸）+ A 的“面板玻璃质感但绝不出壁纸”**
组合：B 只在窗口底板层生效，面板使用不透明的玻璃装饰（实色底 + 高光 +
细边 + 噪声）。

## 4. 实现历程（按提交）

### 4.1 `0247556` — Visual V0 玻璃返工（实时 Acrylic 实验）

- 新增 `qml/surfaces/AcrylicSurface.qml`：
  - `sourceItem`（必填）= 被模糊的背景层，调用方保证不含面板本身，
    杜绝自捕获递归；
  - `ShaderEffectSource(sourceRect=mapToItem 结果, enabled=effectActive)`
    + `MultiEffect(blurMax 24/40, mask 圆角, autoPaddingEnabled:false)`
    → 亮度层 → 色调层（tint 0.62）→ 高光/深边 → `NoiseOverlay`；
  - Safe 档完全实色（无 Shader、无 MultiEffect）；
  - 性能门禁：`visible=false` 或 Safe 时 `capture.enabled=false`。
- `VisualLab.qml`：新增 `labBackgroundLayer`（渐变 + 格线 + 低饱和色块 +
  手稿卡 + 大纲卡），AI 主面板与材质对比行改用 Acrylic；
- tokens：`acrylicTint`、`glassBlurBalanced(24)`、`glassBlurPremium(40)`、
  `glassTintOpacity(0.62)` 等。

### 4.2 `5091910` — 修复背景黑块（QML 类型坑）

- 现象：底板“一块白一块黑”；
- 根因：`tint()` 辅助函数参数未声明类型，`Theme.tokens.*` 是字符串，
  `Qt.rgba(undefined,...)` 静默输出黑色；
- 修复：参数声明为 `color` / `real`，中间渐变档也走同一函数。

### 4.3 `710e13d` — Mica 系统背板（透壁纸方向）

- 新增 `bridge/windows_backdrop.py`：`DwmSetWindowAttribute(38, Mica=2)`，
  Win11 22621+ 才生效，失败静默 False；
- `bootstrap.py --visual-lab` 启动时应用并把结果写入 `systemBackdrop`；
- `GlassSurface.qml` 新增 `opaque` 属性（实色底 + 玻璃装饰，不透壁纸）；
- `VisualLab.qml`：Mica 模式下窗口透明 + 主题洗白层 + 隐藏应用内装饰
  背景；AI 面板切 `GlassSurface.opaque`；对比行显示 Mica 底板；
- 截图脚本新增 `--windowed`（真机截图）。

### 4.4 `af7e2a8` — 质量档在 Mica 模式下可区分

- 用户反馈“三档看不出区别”（原因：三档当时渲染成同一块不透明玻璃）；
- Safe = `DWMSBT_NONE` + 不透明窗口；Balanced = Mica；Premium =
  Desktop Acrylic；
- `theme.quality_changed` → Python 重新下发对应 DWM 背板；
- 顶栏新增「系统背板」状态芯片（Safe 关闭 / Mica / Desktop Acrylic）。

### 4.5 `f0c6dfa` — 调薄洗白层（当前 HEAD）

- 用户反馈“一团灰，档位间只是灰色深浅不同，透不出壁纸”；
- 真机诊断（见 §5）证明 DWM 调用成功、窗口非 layered，灰色来自我们
  自己的 0.8 不透明度主题洗白层；
- 修复：洗白层 Balanced `0.80 → 0.32`、Premium `0.66 → 0.18`；
- 当前状态：**该修复尚未经用户真机确认，用户选择暂停玻璃化方向**。

## 5. 失败诊断（重要证据，2026-08-04 真机）

复现命令：`scripts\diagnose_windows_backdrop.py`（已入库，真机运行）。

探针结果：

```text
wallpaper path: <local-workspace>
Client.CBS_cw5n1h2txyewy\LocalCache\Microsoft\IrisService\
4702723315681337929\134301076053937913.jpg   <- Windows 聚焦多彩风景图
WS_EX_LAYERED: False 0x100                    <- Qt 透明窗口未被设成 layered
DwmSetWindowAttribute(Mica) hr: 0x0 S_OK      <- DWM 系统背板调用成功
SetWindowCompositionAttribute(AcrylicBlurBehind): 0 FAILED  <- 旧 API 不可用
```

结论：

- “没接上”不成立：DWM 调用返回 S_OK，且窗口不是 layered（不存在常见冲突）；
- 当时看到“一团灰”的直接原因是 **0.8 不透明度主题洗白层把 DWM 背板
  完全盖住**（Safe 档没有该层所以正常）；
- 洗白层已调薄（0.32 / 0.18），但用户尚未验证；此外 Mica 材质本身
  偏低调，调薄后可能仍不够“毛玻璃感”。

## 6. 当前代码结构

```text
src/ai_novel_studio/ui_qml/
  bridge/windows_backdrop.py        # DWM 系统背板封装 + 质量档→类型映射
  bootstrap.py                      # --visual-lab 接线；quality_changed→DWM
  qml/surfaces/AcrylicSurface.qml   # 应用内实时 Acrylic（路线 A）
  qml/surfaces/GlassSurface.qml     # opaque 属性（不透壁纸的玻璃装饰）
  qml/VisualLab.qml                 # backgroundLayer / micaActive / wash / 状态芯片
tests/ui_qml/
  test_visual_lab.py                # Mica 三档断言、captureRect、opaque 切换
  test_windows_backdrop.py          # DWM 常量与失败安全
scripts/
  diagnose_windows_backdrop.py      # 真机诊断探针（本次入库）
  capture_frontend_visual_lab.py    # --windowed 真机截图
docs/frontend/
  2026-08-04-frontend-visual-v0-glass-rework.md   # 交付记录
  2026-08-04-glassmorphism-ui-log.md              # 本文档
```

关键 QML 决策：

- `micaActive = systemBackdrop && Theme.visualQuality !== "safe"`：
  Safe 永远不透壁纸（规范 11 实色背景）；
- 窗口透明只在 Mica 生效时开启：`color: micaActive ? "transparent" :
  Theme.tokens.color.bgCanvas`；
- 洗白层（可读性层）只覆盖底板，不覆盖面板。

## 7. 遗留问题与未来方向（恢复点）

### 7.1 待用户真机确认

```powershell
cd <local-workspace>
.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml --visual-lab
# 或真机截图：
.\.venv\Scripts\python.exe scripts\capture_frontend_visual_lab.py --windowed
```

确认点：

1. 洗白层 0.32 / 0.18 后，Balanced / Premium 是否能看到壁纸模糊色彩透出；
2. 顶栏状态芯片是否显示 Mica / Desktop Acrylic（确认 DWM 生效）；
3. 面板是否保持“有玻璃质感但看不到壁纸内容”。

### 7.2 若仍无法透出壁纸：候选方案（按优先级）

1. **不透明窗口 + 纯黑背景（DWM 替换）**：窗口不透明、背景色纯黑，
  由 DWM 用 Mica 替换黑色像素（AutoHotkey / MicaForEveryone 路径）。
  最接近 Win32 语义，需实验 Qt 黑色像素是否被替换；
2. **Qt 层自绘壁纸模糊**：读取壁纸文件（`SPI_GETDESKWALLPAPER`）或截取
  屏幕 → 缩放 + `MultiEffect` 模糊 → 作为窗口背景层。100% 可控、不依赖
  DWM 合成，可作为 Premium 备选（注意壁纸换用/多显示器/性能）；
3. **DComp / CompositionTarget 系统背板**（`Window::set_dcomp_backdrop`
  等价物）：更底层、工作量更大，最后考虑；
4. **放弃系统透壁纸**：只保留应用内实时 Acrylic（路线 A，已可用），
  面板玻璃质感 + 应用内复杂背景。

### 7.3 正式 Shell 接入注意事项（未来如果要做）

- WebEngine 透明窗口风险高（黑底 / 合成异常 / 输入问题），规范 9.3 禁止
  对 WebEngineView 施加实时 Blur/大面积 MultiEffect；
- 必须提供一键回退（`--no-backdrop` 或设置项），失败自动回退普通主题色；
- 性能门禁：窗口 1080×680 起、缩放 100/125/150%、AI Dock 开关不重绘
  WebEngine、空闲特效停止渲染；
- 规范 12：Mica 只作用于窗口底层；Windows 10 / 调用失败时用普通 Canvas；
- 不为 Mica 改无边框窗口；不破坏 Snap / 最大化 / DPI / 标题栏行为。

## 8. 验证与复现命令速查

```powershell
cd <local-workspace>
$env:PYTHONPATH='src'; $env:QT_QPA_PLATFORM='offscreen'; $env:QT_QUICK_BACKEND='software'
.\.venv\Scripts\python.exe -m pytest tests/ui_qml -q --basetemp .test-temp/pytest-base
.\.venv\Scripts\python.exe -m ruff check src tests scripts
$env:MYPYPATH='src'; .\.venv\Scripts\python.exe -m mypy
# 集成（只读桥接）
$tmp=Join-Path $env:TEMP 'frontend-integration-bridge'
$env:PYTHONPATH="$tmp;<local-workspace>"
& '<repo>/.venv/Scripts/python.exe' -m pytest tests/ui_qml -q
# 真机诊断 / 实验页 / 真机截图
.\.venv\Scripts\python.exe scripts\diagnose_windows_backdrop.py
.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml --visual-lab
.\.venv\Scripts\python.exe scripts\capture_frontend_visual_lab.py --windowed
```

最近一次验证基线：前端 pytest 154 passed / 35 skipped，c9a2 集成
230 passed，ruff / mypy 通过（均在 `f0c6dfa`）。

## 9. 一句话总结

应用内 Acrylic（模糊面板背后的应用内容）已实现并验证；系统级 Mica
（窗口后面透壁纸）的 DWM 调用本身成功，但视觉受洗白层掩盖影响，调薄后
尚未确认，方向暂缓。恢复时从 §7 开始：先真机看 `f0c6dfa` 效果，不行再按
§7.2 的候选方案（首选“不透明窗口 + 纯黑背景”）。

## 10. 追加（2026-08-04）：路线纠偏已确认

用户提供《AI_Novel_Studio_玻璃化UI路线纠偏与后续实施任务》，正式采纳：

- **主路线**：不透明 Qt 窗口 + 应用内 `BackdropLayer` + 应用内
  `AcrylicSurface` 面板 + 不透明 `PaperSurface` 正文；
- **系统 Mica / Desktop Acrylic**：降级为可选实验，不再作为 Premium 核心
  或正式 Shell 依赖；`windows_backdrop.py` / 诊断脚本 / 洗白层调参保留；
- 质量档 Safe / Balanced / Premium 共享同一窗口合成模式与组件结构，
  只改变模糊、Noise、阴影、动效强度；
- 本轮已执行的最小动作：新增独立 `BackdropLayer.qml`（VisualLab 背景层
  提炼）、VisualLab 标注“主路线：应用内 Acrylic；Mica：可选实验”、纠偏
  文档入库 `docs/frontend/2026-08-04-glass-ui-course-correction.md`；
- 正式 Shell / 后端 / WebEngine 全部未改动；完整恢复顺序见纠偏文档 §11。

## 11. 追加（2026-08-04）：Visual V0 应用内 Acrylic 重做完成

按《Visual V0 实验页问题诊断与下一版重做要求》重做实验页（交付报告：
`docs/frontend/2026-08-04-visual-v0-app-acrylic-rework.md`）：

- VisualLab 从“组件陈列室”改为**四栏产品布局**：导航轨 / 章节栏 /
  正文 PaperSurface / AI Acrylic 面板（纯 QML 静态数据）；
- **不透明窗口**为主路线：BackdropLayer 覆盖全窗口 + 实色回退，杜绝
  黑色裸露区；自动断言全窗口覆盖与无纯黑像素；
- 调试控件移入 `ExperimentControlPanel`（右侧抽屉）；系统 Mica 降为
  默认关闭的实验开关，通过 `BackdropBridge.apply()` 按需启用；
- 质量档 Safe/Balanced/Premium 共享同一布局，仅改变 Blur/Noise/阴影强度；
- 自动测试：157 passed / 35 skipped；截图脚本输出
  `visual-v0-rework-*.png` 六张并自动断言。

## 12. 追加（2026-08-04）：iOS 26 Liquid Glass 层叠调研与实验页实装

用户提问：能否做到 iOS 最新版（Liquid Glass）的玻璃效果；现有 Premium 在
dark 下明显、light 下几乎看不出。本轮结论：**视觉近似可行，完全复刻不现实**。

### 12.1 调研结论（网上指导汇总）

- Apple HIG Materials：Liquid Glass 是动态材质，须克制使用、不要用在内容层；
  背景较亮时可叠 35% 黑色 dim 层保证可读性。
- UIKit（iOS 26）：`UIGlassEffect`（tintColor、isInteractive）+
  `UIGlassContainerEffect` 的 spacing 让相邻玻璃元素融合（Qt 无直接等价）。
- SwiftUI：`.glassEffect(.regular.interactive(), in: .rect(cornerRadius: 16))`，
  需 iOS 26 gating + 非玻璃回退。
- Flutter `cupertino_liquid_glass` 0.6.x：blur ≈ 40、tint ≈ 0.3；
  **specular 斜向高光、edge lighting、inner shadow、noise grain、vibrancy
  boost**；light = matte & bright，dark = deep & contrasty。
- Floatica / DeepWiki：saturate(180%) 即约 +80% 饱和增强；多层 specular 与
  shape-aware edge glow 是 Liquid Glass 与普通毛玻璃的关键区别。

### 12.2 现有实现缺的四层（light 下看不出的根因）

1. 无斜向 specular 高光（"sheen"）——液态感的核心；
2. 无顶/左边缘光与底/右内阴影——厚度感；
3. light 主题饱和度为负（-0.1）——把背景颜色洗掉；
4. 浅色背景自身过白，blur+tint 没有颜色可透。

### 12.3 本轮改动（仅实验页 VisualLab / AcrylicSurface / 主题 token）

- `AcrylicSurface.qml`：新增单个静态 Canvas 一次绘制五层
  （斜向 specular、顶/左边缘光、底/右内阴影），用既有圆角 mask 裁切；
  Safe 档全隐藏，Balanced/Premium 强度由 token 控制（Premium 严格更强）。
- `theme_provider.py`：新增 `glassSpecular*` / `glassEdgeLight*` /
  `glassInnerShadow*` token；light 饱和度改为 +0.40、玻璃色调改为冷白
  `#F5F8FB`、Premium 透明度调回 0.52；背景光晕强度 token 化
  （`backdropGlowWarm/Cool`），light 调强（0.22/0.19）让 blur 有颜色可透。
- 验证：前端 pytest 165 passed / 35 skipped；ruff 通过；mypy（项目配置）
  通过；截图脚本新增 light 两档并增加 resize 后有界等待。

### 12.4 像素验证摘要（真机 windowed 截图）

- dark premium：面板顶缘亮度 83 vs 面板本体 41（+40），specular 上区 59 vs
  下区 43——边缘光与高光清晰可见。
- light premium：面板上部 ~230（偏冷蓝）vs 纸张 252，面板与纸张明显分离；
  premium 与 balanced 仅玻璃区有差异（avg diff 2.39，纸张区 0.0）。

### 12.5 已知限制与后续

- 无法复刻：多玻璃容器融合（UIGlassContainerEffect）、交互折射/形态变化、
  Fresnel rim 等，需要自定义 shader 或 WebEngine 的 WebGPU/CSS 路径，本轮不做。
- 正式 Shell / 后端 / WebEngine 未改动；方向确认后再考虑从
  `AcrylicSurface` 平移到正式 UI。
- light 下玻璃的“明显程度”由背景丰富度决定，token（specular/edge/glow）
  都可单独微调，不需要逐个按钮改魔法数字。

## 13. 追加（2026-08-04）：LiquidLights 抽取、卡片共享材质、扁平化收束

用户反馈第二轮：dark 斜向高光过于明显生硬、paper/light 又不够明显；既然
做了边缘光/内阴影，其他框（卡片）也该统一。第三轮追加：阴影整体要很微弱，
样式更趋于扁平化。

### 13.1 结构改动

- 新增共享组件 `surfaces/LiquidLights.qml`：一个静态 Canvas 一次绘制
  斜向 specular + 顶/左边缘光 + 底/右内阴影，自带圆角 clip（Canvas 2D
  roundedRect path + ctx.clip），替代原来 AcrylicSurface 内联的
  Canvas + MultiEffect mask 组合。
  - specular 渐变端点延伸到 `(w*1.15, h*0.75)`、亮带停靠拉宽，斜向光带
    变得宽而柔，不再是一条硬斜线。
- `AcrylicSurface.qml` 改挂 `LiquidLights`（radius/specular/edge/inner 全部
  由 token 驱动），面板外投影从 5px/3px 降到 3px/2px（扁平化）。
- `AgentCard.qml` 挂载淡 `LiquidLights`：卡片共享“光从左上落”的材质语言，
  只用边缘光 + 内阴影（specular 保持 0，不往内容上画高光）；Safe 档隐藏。
  三张实验卡片（TextDiff/ChangeSet/Form）与正式 CreativeAgentPanel 共用
  同一容器，一处改动全部生效。

### 13.2 强度收束（token，三主题）

- dark specular premium 0.26 → 0.16（柔和化）；paper 0.30 → 0.42、
  light 0.52 → 0.62（浅色下更明显，配合亮带拉宽）。
- glass 内阴影 premium 0.28/0.36/0.32 → 0.14/0.16/0.15；边缘光同步下调。
- 卡片内阴影 0.07/0.12/0.07 → 0.04/0.05/0.04，边缘光 0.14/0.12/0.16 →
  0.09/0.08/0.10——只保留极淡层次，扁平化。

### 13.3 验证

- 前端 pytest 166 passed / 35 skipped（新增卡片共享材质测试）；ruff 通过；
  mypy（项目配置）通过。
- 真机 windowed 像素：light/dark 面板底部内阴影亮度差收敛到 ~8-10/255
  （此前层级明显更深）；卡片内阴影 ~0.04-0.05，肉眼为极淡层次。

## 14. 追加（2026-08-04）：删除斜向高光、三栏边缘统一、背景光为光源

用户反馈第四轮：
1. 三个主窗口（导航轨 / 章节侧栏 / AI 面板）边缘设计不统一——有的有阴影、
   有的没有；
2. 斜向高光不要再加了；
3. 玻璃的光改为来自背景板（BackdropLayer）的背景光。

### 14.1 结构改动

- `LiquidLights.qml`：删除 `specularOpacity` 属性与斜向高光绘制逻辑，组件只
  保留顶/左边缘光 + 底/右内阴影，自绘圆角 clip 不变。注释明确：光来自
  BackdropLayer 背景光晕，不在面板表面画高光。
- `AcrylicSurface.qml`：删除 `elevated` 属性与外投影 Rectangle——三个玻璃
  面板统一为 1px 边框 + LiquidLights 边缘光/内阴影，不再出现"有的面板带投影、
  有的没有"；删除 specular 绑定。
- `VisualLab.qml`：移除导航轨/章节侧栏的 `elevated: false`（属性已删除）。
- `theme_provider.py`：移除 `glassSpecular*` token；paper/light 背景光晕
  增强（0.14/0.12、0.28/0.24）补偿浅色下失去 specular 后的可读性。

### 14.2 验证

- 前端 pytest 167 passed / 35 skipped（新增"三栏统一边缘材质"测试：断言
  共享表面无 `elevated` 开关、三栏 LiquidLights 强度一致）；ruff / mypy 通过。
- 真机 windowed 像素：AI 面板左上与右上亮度相近（light 220/225、dark 42/46），
  斜向高光消失；顶部边缘光保留（dark 71.8 vs 底部 47.6）；面板右侧外沿无
  阴影渐变，外投影已彻底移除。

## 15. 追加（2026-08-04）：中央正文工作区统一为玻璃样式

用户反馈第五轮：最中间的文本框（正文工作区）也应该改成相同的玻璃样式。

### 15.1 改动

- `VisualLab.qml`：中央正文从不透明 `PaperSurface` 换成 `AcrylicSurface`
  （objectName 保留 `labPaperSurface`），`sourceItem: backgroundLayer`、
  `radius: r12`，与 AI 面板一致；内部章节标题/正文段落/状态行布局不变。
  Safe 档自动回退为不透明 `bgSurface`（AcrylicSurface 既有行为）。
- `test_visual_lab.py`：统一材质测试从三栏扩展为四面板
  （`test_four_main_panels_share_unified_edge_material`），断言正文面板
  `elevated` 不存在、LiquidLights 强度与 AI 面板一致、`sourceItem` 为
  `labBackgroundLayer`。

### 15.2 验证

- 前端 pytest 167 passed / 35 skipped；ruff 通过；mypy（项目配置）通过。
- 真机 windowed 像素：正文顶部边缘光与 AI 面板一致（dark 72.8 vs 71.2、
  light 246.7 vs 240.9），正文区域呈现玻璃质感（dark body 56、light 230，
  半透明透出背景冷调光晕）。

## 17. 追加（2026-08-04）：滑动条范本 GlassSlider + SliderTemplateDock

用户要求“做一个作为范本的滑动条 UI 在实验页面”，并明确调用相关 skill。本轮
按用户指定使用：frontend-design（组件设计质量）、emil-design-eng（打磨与动效
决策）、apple-design（手势/弹簧）、animation-vocabulary（动效术语），最后用
review-animations 对成品做自审（结论见 17.4）。

### 17.1 GlassSlider（可复用滑动条组件）

- 拖动：指针按下立即响应、拖动全程 1:1 跟手（apple-design §1/§2 直接操作），
  数值在按下瞬间即更新，不等到松开。
- 数值：任何赋值都走统一校验（clamp + stepSize 取整），程序赋值与指针输入
  同一路径；Safe / Balanced / Premium 均可用（玻璃 UI 文档 §12.3：业务功能
  不依赖视觉效果）。
- 动效：拇指 x 用可打断 Behavior + SpringAnimation（spring 2.5 / damping 0.9，
  拖动中禁用保证 1:1），按下 scale 1.18（反馈在 pointer-down），松开弹簧回弹
  （damping 0.7，仅因拖动带动量才允许轻微过冲）；数值气泡从 scale(0.95) +
  opacity 进入（emil：禁止 scale(0)），110/160ms 均 < 300ms。
- 档位：Safe 实色拇指/轨道、无玻璃 rim；Balanced 常规；Premium 轨道渐变 +
  弹簧。气泡为玻璃药丸（LiquidLights 边缘光 + 内阴影）。
- reduceMotion：`springEnabled` 统一控制，关闭弹簧/行为、气泡 opacity 变 0ms，
  Facade 不可用时兜底为启用弹簧（AppButton 同款守卫模式）。
- 命名：用 `interactive` 而非 `enabled`，避免覆盖 Item 内置 `enabled` 属性
  （Qt 警告），这是实现过程中修掉的一个真实问题。

### 17.2 SliderTemplateDock（范本展示）

- 从底部上翻（与 ExperimentControlPanel 同款模式，不遮挡工作区），Escape /
  关闭按钮收起，收起无动画（工具条高频动作，emil：不动画）。
- 四个样例：生成强度（实时气泡 · 弹簧）、章节字数目标（步进 100 · 常显数值）、
  面板透明度（禁用态）、氛围温度（自定义 accent · 负区间）。
- 入场：四列 40ms 间隔 stagger（fade + 6px 上浮，180ms OutCubic），
  reduceMotion 时直接显示。

### 17.3 接入与验证

- Header 新增“滑动条范本”按钮；dock 挂在 ColumnLayout 底部。
- qmldir 注册 GlassSlider / SliderTemplateDock。
- 新增 5 个 QML 测试：dock 开关、数值→拇指 1:1 映射与 clamp/step、禁用态与
  Safe 档功能、reduceMotion 降级、dock 边缘光统一。
- 前端 pytest 176 passed / 35 skipped；ruff 通过；mypy（项目配置）通过。
- 真机 windowed 截图：`visual-v0-rework-slider-template.png`（paper premium）
  与 `visual-v0-rework-slider-template-dark.png`（dark premium）；像素采样确认
  底部 dock 区域存在多个彩色 thumb（饱和像素占比 ~2%）。

### 17.4 review-animations 自审结论

| Before（朴素基线） | After（本轮实现） | Why |
| --- | --- | --- |
| 拇指改值瞬间跳变 | Behavior on x + Spring（拖动中禁用） | 手势动效必须可打断、跟手（apple-design §3/§4） |
| 气泡从 scale(0) 出现 | scale 0.95→1 + opacity 110ms | 万物不从“无”出现（emil） |
| 按下无反馈 | 拇指 pointer-down 即 scale 1.18 | 反馈发生在按下而非松开（apple §1） |
| 四列同时出现 | 40ms stagger（180ms OutCubic） | 成组入场读作级联而非一次性 |
| 直接读 Facade.reduceMotion | springEnabled 统一守卫 | reduceMotion 生效且上下文缺失时安全 |

**Verdict: Approve**——全部动效 ≤180ms、仅 transform/opacity、手势弹簧可打断、
reduceMotion 完整降级、无 scale(0)/ease-in、工具条关闭无动画。

## 18. 追加（2026-08-04）：方向纠正——上下划动窗口的条（DragSheet）

用户指出 §17 理解错了：要的是“上下划动窗口的条”（iOS 底部 sheet / 控制中心
式、带抓手条、可上下拖动展开收起的面板），不是横向滑块。本轮：

### 18.1 结构改动

- 删除 `GlassSlider.qml`、`SliderTemplateDock.qml` 及两张旧截图；
  qmldir 改注册 `DragSheet`。
- 新增 `DragSheet.qml`：底部浮出的玻璃面板（半透明底 + LiquidLights 边缘，
  顶部 16 圆角），顶部是 36×4 的 grabber 圆条 + 标题行，整条 header 可拖。
  - 拖动：指针按下即记录起点，移动时面板 1:1 跟随（`setFromPointer`）；
  - 吸附：松手按“位置最近档 + 甩动速度”落到 收起(0) / 预览(0.5) / 展开(1)，
    向上甩跳一档、向下甩退一档（`snapTarget`，momentum 简化版）；
  - 弹簧：吸附用可打断 `SpringAnimation`（spring 2.4 / damping 0.86），
    拖动中禁用保证跟手；只用 `transform.translate`（GPU 友好）；
  - 橡皮筋：拖过上下边界时位移阻尼减半，松手弹回档位；
  - reduceMotion：吸附瞬间完成；Safe/Balanced/Premium 均可拖动。
- `VisualLab.qml`：Header 按钮改为“拖拽面板范本”（`labDragSheetButton`），
  DragSheet 悬浮于窗口底部（声明在 ColumnLayout 之后），Escape / 按钮关闭。
- 截图脚本新增展开（paper）与收起（dark）两张范本图。

### 18.2 实现中发现并修复的三个真实坑

1. **`Facade === null` 恒为 true**：QML 里把上下文属性对象与 `=== null`
   比较，PySide6 包装的 QObject 恒判等，导致 `springEnabled` 被静默禁用。
   改为只用 `typeof Facade === "undefined"` 判断（实验脚本实测确认）。
2. **Theme token 字符串取 `.r` 得 undefined**：`Qt.rgba(undefined,…)`
   静默产生纯黑——DragSheet 面板一度整块黑（截图脚本 6~36 个黑像素告警）。
   修复：先声明 `property color glassColor: Theme.tokens.color.bgSurface`，
   再取分量（BackdropLayer 注释里同样警示过的坑）。
3. **PySide6 读 QML bool 返回 float**：测试里 `property("springEnabled")
   is False` 恒失败（读回 0.0），统一用 `bool(...)` 断言。

### 18.3 review-animations 自审

| Before（朴素基线） | After（本轮实现） | Why |
| --- | --- | --- |
| 面板直接显隐 | grabber 拖动 1:1 跟随 | 直接操作：内容与指针同步（apple §2） |
| 松手就近落点 | 位置 + 甩动速度双判据吸附 | 甩动应投影到目标（momentum） |
| 硬边界卡死 | 越界阻尼减半（橡皮筋） | 真实物体先减速再停（apple §9） |
| 固定时长动画 | 可打断 SpringAnimation | 拖动中随时反向无断档（apple §3） |
| 改 width/height | 仅 transform.translate | 只动合成属性，不触发布局 |
| 直接读 Facade | typeof 守卫 | `=== null` 恒真坑（§18.2） |

**Verdict: Approve**——1:1 跟手、弹簧可打断、橡皮筋阻尼、仅 transform、
reduceMotion 降级、无黑块；工具条关闭无动画（高频动作）。

### 18.4 验证

- 前端 pytest 177 passed / 35 skipped（新增/替换 7 个 DragSheet 测试：开关、
  progress↔translate 1:1、clamp、snapTarget 逻辑、reduceMotion、边缘光）；
  ruff 通过；mypy（项目配置）通过。
- 真机 windowed 截图：展开（paper）与收起（dark）两张，底部区域 0 黑像素；
  grabber 行亮度正常（paper 亮 / dark 灰条可见）。

## 19. 追加（2026-08-04）：再次纠正——垂直滚动条范本（窗口最右侧）

用户第三次澄清：要的是**滚动条**（vertical scrollbar，一般在窗口最右侧），
不是横向滑块（§17），也不是底部可拖面板（§18）。本轮：

### 19.1 结构改动

- 删除 `DragSheet.qml`（并补删上一轮遗留未提交的 `GlassSlider.qml`、
  `SliderTemplateDock.qml` 删除状态）；qmldir 注册 `GlassScrollbar` 与
  `ScrollbarTemplate`。
- 新增 `GlassScrollbar.qml`：垂直滚动条（宽 14px），
  - thumb 高度 = 视口/内容比例，位置 = contentY 归一化映射，双向往 1:1
    同步（contentY→thumb 绑定、拖 thumb→写回 contentY，含抓取偏移）；
  - 点击轨道按方向翻一屏（不跳远）；拖过边界由 Flickable StopAtBounds 收住；
  - hover 只做 opacity 0.55→1.0（120ms，仅合成属性，reduceMotion 时 0）；
  - 档位：Safe 实色 thumb 无轨道 / Balanced 半透明玻璃 thumb + 淡轨道 /
    Premium 渐变 thumb + 顶部 1px 高光（light catching the material）；
  - 内容不超高时整条隐藏（功能完整但无可滚动内容）。
- 新增 `ScrollbarTemplate.qml`：窗口最右侧固定列（230px），玻璃面板内放
  18 段长 Mock 文稿（Flickable），右缘贴 GlassScrollbar。
- `VisualLab.qml`：四栏之后追加第五列 `labScrollbarTemplate`（最右贴窗缘），
  删除 DragSheet 按钮/属性/声明。
- 截图脚本：删除 drag-sheet 两张，新增 scrollbar 两张（paper/dark，滚动到
  40% 让 thumb 可见）。

### 19.2 实现中处理的真实坑

- offscreen/software 下 Flickable `contentHeight` 布局延迟（早期为 0，
  thumb 高度一度 56 万像素）：测试等待 250ms 后再断言；组件本身在
  contentHeight=0 时整条隐藏（§12.3 功能不依赖视觉）。
- `springEnabled` 守卫改为 `typeof Facade !== "undefined" && Facade ? ...`，
  消除 QML null 访问告警。
- PySide6 把 QML bool 读回为 float：断言统一 `bool(...)`。

### 19.3 review-animations 自审

| Before（朴素基线） | After（本轮实现） | Why |
| --- | --- | --- |
| thumb 位置硬编码 | contentY 归一化 1:1 绑定 | 直接操作：内容与 thumb 同步（apple §2） |
| hover 突现/突隐 | opacity 0.55→1.0，120ms | 只在合成属性上做短淡入，<300ms |
| 点击轨道跳任意位置 | 按方向翻一屏 | 可预测、不丢失上下文 |
| 直接读 Facade | typeof+truthy 守卫 | 避免 null 访问告警与静默禁用 |

**Verdict: Approve**——拖动 1:1、动效仅 opacity 且 ≤120ms、reduceMotion 降级、
无 scale(0)/ease-in、内容不超高自动隐藏。

### 19.4 验证

- 前端 pytest 176 passed / 35 skipped（5 个滚动条测试：右缘位置、thumb 比例
  与隐藏、contentY↔thumb 1:1、reduceMotion、档位几何不变）；ruff 通过；
  mypy（项目配置）通过。
- 真机 windowed 截图：`visual-v0-rework-scrollbar.png` /
  `visual-v0-rework-scrollbar-dark.png`；范本列 0 黑像素，右缘 thumb 区域
  有渲染（饱和像素 paper 1578 / dark 970）。

## 20. 追加（2026-08-04）：正式 Shell 玻璃整合

用户确认“现在可以试着整合到前端”。本轮把 VisualLab 验证过的玻璃路线
（BackdropLayer + AcrylicSurface + LiquidLights）接入正式 `App.qml`，
保持最小改动、正文/WebEngine 不透明、Safe 可回退。

### 20.1 改动

- `App.qml`：新增 `import "surfaces"`；窗口最底层加 `BackdropLayer`
  （objectName `f1BackgroundLayer`，`washEnabled: false`，窗口仍不透明）；
  侧栏宿主 `sidebarHost` 从实色 Rectangle 换成 `AcrylicSurface`
  （`sourceItem: backgroundLayer`，radius 0，折叠仍一步切换，遵守
  ideal-UI spec 10.1）；NavigationRail 与 AgentDock 传入
  `backdropSource: backgroundLayer`；中央工作区加 objectName
  `workspaceHost`（保持 `bgCanvas` 实色，正文 WebEngine 不透明）。
- `NavigationRail.qml`：新增 `property Item backdropSource: null`；传入时
  使用 AcrylicSurface（radius 0），否则保留原实色背景（向后兼容）。
- `AgentDock.qml`：新增 `backdropSource`；`panelSurface` 在传入时为半透明
  玻璃底（premium 0.86 / 其它 0.94，类型化 glassColor 避免 Qt.rgba
  undefined 黑块坑），并挂载 LiquidLights（card 级边缘光/内阴影）；
  宽度切换仍一步完成，面板 fade/scale 进入动画不受影响。

### 20.2 测试与验证

- 新增 2 个正式 Shell 测试：玻璃整合（BackdropLayer 覆盖全窗、导航/侧栏/
  Dock 共用同一背景源、中央工作区不透明、Safe 档降级为不透明）与
  sidebar 折叠一步切换。
- 前端 pytest 178 passed / 35 skipped；ruff 通过；mypy（项目配置）通过。
- 正式 shell 截图（offscreen，c1-shell-paper/light/dark 等 7 张）重新生成：
  像素确认侧栏左右色差（paper 238→245、dark 51→46）即背景光晕透出——
  玻璃生效；正文区保持实色。

### 20.3 遗留项

- offscreen 软件渲染下，侧栏 `projectPath`（ElideMiddle）区域左右两端有
  少量纯黑像素（基线已有，非本轮引入，真机需复核）；不影响功能，列入
  后续清理。
- 正式 Shell 尚无质量档 UI（沿用 ThemeProvider 默认 balanced）；后续可在
  设置页暴露 Safe/Balanced/Premium。

## 21. 追加（2026-08-04）：正文框米色修复 + 中间框玻璃升级

用户反馈：中间正文框在 dark/light 下都是米色；并要求给中间框也做玻璃升级。

### 21.1 米色根因

WebEngine 编辑器页面（`editor_web/src/style.css`）把 `.novel-editor` 的
`--editor-bg` 默认写死为 `#fffdf7`（米白），而 `NovelEditorView.applyTheme`
虽然存在（含 `apply_theme_script` 助手）却**从未被调用**——主题切换只改了
Qt 侧画布色，页面内部 html/body 与 ProseMirror 一直落在默认米白。

### 21.2 改动

- `NovelEditorView.qml`：新增 `applyCurrentTheme()`，把
  `--editor-bg/--editor-text/--editor-accent/--editor-muted` 四个 CSS 变量
  从 Theme tokens（bgEditor/textPrimary/accent/textSecondary）推给页面；
  `Connections target: Theme onTokensChanged` 与页面 `editorLoaded` 时各推
  一次——dark 下页面背景变 `#292A2D`、light 变 `#FFFFFF`、paper 保持
  `#FFFDF7`，滚动条轨道与正文同步。
- `WritingPage.qml`：正文容器从实色 Rectangle 换成 `AcrylicSurface`
  （objectName `manuscriptHost`，`sourceItem: root.backdropSource`，
  radius r16）：TextArea 模式正文直接坐在玻璃上；WebEngine 模式页面背景
  （随主题）保持不透明以保证阅读，圆角边缘与背景光晕读作玻璃（WebEngine
  禁用实时 blur 的既有约束不变）。
- `App.qml`：`WritingPage` 传入 `backdropSource: backgroundLayer`。

### 21.3 验证

- 新增 2 个测试：`manuscriptHost` 为玻璃（sourceItem=f1BackgroundLayer、
  blurEnabled、Safe 降级不透明）；WebEngine 主题接线契约 + 三主题 bgEditor
  token（paper #FFFDF7 / light #FFFFFF / dark #292A2D）。
  WebEngineView 无法 offscreen 实例化，故用源码契约 + token 断言锁定。
- 前端 pytest 180 passed / 35 skipped；ruff 通过；mypy（项目配置）通过。
- 正式 shell 截图（TextArea 模式）：正文容器顶部边缘 vs 内部
  （dark 66.7 vs 41.0、light 216 vs 245、paper 221 vs 249）——玻璃边缘光与
  背景光晕生效；dark 下内部为深色（不再米色）。

## 22. 追加（2026-08-05）：状态光带“泛白亮点沿边框移动”（comet）

用户要求：AI 商讨模型 thinking / cancel / error 状态卡的光带（彩色边框）
上，增加一个更亮、泛白的光点沿光带移动，凸显灵动感。本轮按要求调用
animation-vocabulary / apple-design / emil-design-eng /
find-animation-opportunities / improve-animations / review-animations，
并先按 vision-bridge 尝试读用户截图（atlas-vision 与 view_image 均不可用，
改用结构性 + 像素证据）。

### 22.1 效果定位

词汇表定位：沿路径匀速移动的高亮点 = **Orbit / 沿路径移动的亮点**（恒定
速度、单一高亮元素、reduceMotion 降级）。现有 `StreamingGlowBorder` 只有
1.5px 边框颜色渐变（thinkingA↔thinkingB，2.8s），没有亮点移动——新增
comet 层。

### 22.2 实现（StreamingGlowBorder.qml）

- 三层同心圆构成亮点：外圈状态色 halo（α0.40）、中圈泛白高光（白 α0.55）、
  内圈近白 core（直径 4.4）——“更亮泛白”由中圈+core 实现，颜色家族仍
  跟随状态（thinking 紫 / cancelled 灰 / error 红）。
- 位置：`pathPoint(t,w,h,r)` 把圆角矩形周长分成 4 直线 + 4 角弧，
  `cometPosition(progress)` 返回 0..1 对应的边框中心线坐标；修掉一个真实
  bug——角弧曾用起始角圆心导致路径在 ~0.33 处折返，改为目标角圆心后
  闭环正确。
- 移动：`NumberAnimation` 驱动 `cometProgress` 0→1 循环（2200ms，
  **Linear** 恒定速度）；亮点用 `transform.translate` + 属性绑定驱动
  （软件渲染下 Canvas requestPaint 不随动画重绘，已实测排除），不触发
  布局、只动合成属性。
- reduceMotion：`cometRunning` 为 false，亮点静止（gentler，不是零动效，
  apple-design §14）；thinking/cancelled/error 三状态都跑 comet。
- VisualLab：AI 面板新增一行三张小状态卡（思考中/已取消/出错），各挂
  StreamingGlowBorder（active + 对应 state），lab 里三种状态都有 comet
  演示；原有 diff 卡 glow 同样带 comet。

### 22.3 验证

- 新增/扩展测试：三状态卡 comet 均在运行；路径函数全程贴边框、四边全覆盖、
  连续、闭环；reduceMotion 停止 comet。前端 pytest 182 passed / 35 skipped；
  ruff 通过；mypy（项目配置）通过。
- 像素证据（offscreen 抓图）：cometVisual 绑定位置随 progress 变化
  （0.1→右边缘 (105,18)、0.5→底边、0.9→左边缘）；16×16 采样确认白色
  core 与状态色 halo 出现在期望边框位置；两帧差分确认亮点在移动。

### 22.4 review-animations 自审

| Before（朴素基线） | After（本轮实现） | Why |
| --- | --- | --- |
| 边框只有颜色渐变 | 颜色渐变 + 白亮 comet 沿边框匀速绕行 | 状态指示更“活”（orbit，恒定速度） |
| 无 reduceMotion 分支 | cometRunning 关闭、亮点静止 | 动效降级但保留状态色（apple §14） |
| Canvas requestPaint 驱动 | transform.translate + 属性绑定 | 软件渲染下 requestPaint 不随动画重绘（实测） |
| 直线循环（若有） | 圆角矩形 4 直线 + 4 角弧分段 | 与卡片圆角一致，不切角 |

**Verdict: Approve**——仅移动一个高亮元素、Linear 匀速、只动 transform、
reduceMotion 降级、单实例成本可控（一次最多 1-2 个 live 卡）、无
scale(0)/ease-in；路径连续性有测试锁定。

## 23. 追加（2026-08-05）：纠正——光带上的移动体改为“车厢胶囊”而非泛白点

用户澄清：§22 的“泛白亮点”不对。正确理解是——原有光带像**火车轨道**，
移动体是一节**车厢**（俯视）：宽度比轨道略宽一点点，车头车尾两端向轨道
收缩（胶囊/纺锤形），且形状会有微小变化。不是做成火车的图形，是形状
语言。并且**不要再泛白**。

### 23.1 改动（StreamingGlowBorder.qml）

- 删除三层同心圆（状态色 halo + 泛白中圈 + 白色 core），改为**胶囊车厢**：
  - 长轴沿轨道切线（默认 26px），宽度 3.5px（比 1.5px 轨道宽 ~1px/侧）；
  - 两端圆头自然向轨道收缩（胶囊端部渐窄）；
  - 颜色 = 状态色本身微亮（`Qt.lighter(staticColor, 1.18)`），thinking 紫 /
    cancelled 灰 / error 红，**不再有白色**；
  - 外层加同形柔光（状态色 α0.30，放大 1.55）体现“宽度稍微超过轨道”。
- 切向跟随：新增 `pathAngle(t)`，直线段保持 0°/90°/180°/270°，角弧在相邻
  角度间线性过渡；胶囊 `rotation` 绑定该角度，过弯时车身转向。
- 形状微变：新增 `pulsePhase`（1500ms InOutSine 循环），长度 ±6%、
  宽度 ±10%、不透明度 0.85..1.0 轻微呼吸——移动中形状持续微小变化。
- reduceMotion：绕行与呼吸都冻结（车厢静止、形状固定），颜色保留。
- 软渲染坑沿用 §22 结论：全部由 x/y/rotation/width/height/opacity 属性
  绑定驱动，不用 Canvas requestPaint。

### 23.2 验证

- 新增/扩展测试：胶囊比例（长 >> 宽、宽 > 轨道 1.5px 且 < 8px）、颜色为
  状态色族且非白、切向角度单调 0→90→180→270→回绕且四方向都经过、
  呼吸推进 pulsePhase 时长度/宽度确实变化、reduceMotion 停止呼吸。
- 前端 pytest 184 passed / 35 skipped；ruff 通过；mypy（项目配置）通过。
- 像素证据（offscreen 抓图，progress=0.5 底边）：车厢区域出现
  166,154,252（thinkingA 微亮紫）的水平胶囊——中段纯色、两端渐变为
  179,168,250→227,222,243 圆头收缩，宽度约 3-4px 超出轨道，无白色 core。

### 23.3 review-animations 自审（针对本轮纠正）

| Before（§22 泛白点） | After（§23 车厢胶囊） | Why |
| --- | --- | --- |
| 白色 core + 泛白中圈 | 状态色微亮 + 无白色 | 用户明确：不要泛白，颜色跟随状态 |
| 圆形光点 | 沿切线拉长胶囊，两端圆头收缩 | “车厢”俯视：宽于轨道、两端收窄 |
| 仅位置移动 | 位置移动 + 切向旋转 + 形状呼吸 | 车厢过弯转向、形状微小变化（用户要求） |
| 单一周期 | 移动 2200ms + 呼吸 1500ms 双周期 | 绕行与形态变化解耦，灵动但不喧闹 |

**Verdict: Approve**——纯状态色、胶囊两端收缩、切向旋转、双周期微变、
全部属性绑定驱动（无布局动画）、reduceMotion 冻结移动与呼吸。

## 24. 追加（2026-08-05）：霓虹流光重做——回滚胶囊/短横条方案

用户明确否定 §23 的“顶部彩色胶囊/短横条”：需要的是**一颗带渐变拖尾和
柔和辉光的光点沿圆角矩形边框完整周长连续、匀速漂移**（霓虹灯管能量流动）。
本轮按用户 15 条规格 + 推荐实现重做，并在独立 Visual Lab 验证。

### 24.1 实现（StreamingGlowBorder.qml 整文件重写）

- **单层 Canvas 一次绘制**（用户推荐 ShaderEffect；Qt6 ShaderEffect 只接受
  qsb 预编译 URL，内联 GLSL 报错且软渲染不可靠，改为 Canvas 等价实现）：
  - 光点核心：状态色满 alpha 圆（coreRadius 3 → 直径 6px，规格 4-8px）；
  - 拖尾：沿 -tangent 后方采样 24 个圆，alpha 按 (1-k)^1.8 指数衰减、
    半径递减，总长 30px（规格 20-40px）；
  - 外辉光：核心处低透明（α0.14）半径 10px 圆（规格“外围低透明辉光，
    不能形成实色胶囊”）。
- **完整周长**：`pathPoint`（4 直线 + 4 角弧，先前 §22 已修目标角 bug）与
  `pathAngle`（直线 0/90/180/270、角弧线性过渡）驱动 phase 0..1，光点
  依次经过上/右/下/左边，贴合边框中心线（圆角处自动转向）。
- **状态机**（规格 8-13）：thinking/generating 循环（Linear 2.2s）；
  success/error 单次扫过（loops:1，播完 `singleFinished` 停止，静态边框
  保留）；cancelled 只淡出一次（OutCubic 700ms）；idle/非 active 仅静态
  边框；reduceMotion 退化为静态高亮边框。
- **生命周期**（规格 14）：`neonActive = active && visible && !reduce &&
  windowVisible && !singleFinished && !cancelFaded`；窗口最小化/隐藏、
  组件不可见、任务结束（active=false）均停动画。offscreen 下窗口 visible
  绑定不可靠，测试用组件可见性断言，真机由 windowVisible 兜底。
- **布局隔离**（规格 6-7）：效果层 anchors.fill 覆盖卡片，无 MouseArea，
  不参与 width/height/implicitHeight；测试断言动画前后几何完全不变。
- **并发**（规格 15）：lab 演示一次仅一个状态实例；测试枚举运行实例 ≤2。

### 24.2 Visual Lab 演示

- 新增 320×160 圆角演示卡（neonDemoCard）+ 状态按钮行
  （idle/thinking/generating/success/error/cancelled/reduced，
  `labNeonMode-*`），默认 thinking 循环；移除旧的胶囊小状态卡与
  diff 卡流光（diff 卡改普通静态边框），保证同一时刻唯一运行实例。

### 24.3 验证

- 新增 8 个测试：默认 thinking 循环、shader/Canvas 源契约（core+tail+halo、
  无胶囊残留标识符）、状态机各模式、单次扫过、reduceMotion 回退、几何
  不变、不可见停止、并发 ≤2。前端 pytest 187 passed / 35 skipped；ruff
  通过；mypy（项目配置）通过。
- **连续截图验收**（offscreen 精确帧 + windowed 真机帧，各 4 张
  `visual-v0-rework-neon-{top,right,bottom,left}.png`）：亮斑重心
  phase 0.05→(159.5, 0.7) 顶边、0.45→(318.0, 79.3) 右边、
  0.70→(159.3, 158.3) 底边、0.90→(1.0, 79.5) 左边——明确经过四条边；
  截图脚本抓帧前把 flowDuration 拉长冻结相位，避免动画覆盖。

### 24.4 review-animations 自审

| Before（§23 胶囊） | After（§24 霓虹流光） | Why |
| --- | --- | --- |
| 实色胶囊/短横块 | 核心+指数衰减拖尾+低透明辉光 | 用户要求“霓虹灯管能量”，无实色块 |
| 顶部移动或形状块 | phase 驱动沿完整周长匀速 | 规格 1-2：四边+圆角、贴合中心线 |
| 布局相关对象 | Canvas 覆盖层 anchors.fill | 规格 6-7：不参与布局、不遮挡内容 |
| 单一状态 | thinking/generating 循环、success/error 单次、cancelled 淡出、idle 静态 | 规格 8-13 状态机 |
| 无条件运行 | active/visible/windowVisible/reduce 全闸 | 规格 14-15：生命周期与并发上限 |

**Verdict: Approve**——匀速线性、指数衰减拖尾、仅覆盖层绘制（无布局/无
交互影响）、状态机与生命周期完整、reduceMotion 回退、四边多帧像素证据。

## 16. 追加（2026-08-04）：Header 玻璃化、控制条边缘统一、资源门禁

“做下一波”收尾：实验页剩余大容器统一玻璃语言，并补齐资源/几何门禁测试。

### 16.1 改动

- `VisualLab.qml`：Header 顶栏从实色 Rectangle 换成 `AcrylicSurface`
  （objectName `labHeader`，`sourceItem: backgroundLayer`，radius 0），与
  四栏共用同一材质；标题与“实验控制”按钮布局不变。
- `ExperimentControlPanel.qml`：主体保持高不透明度（可读性优先），挂载
  `LiquidLights`（card 级边缘光 + 内阴影），控制条与卡片/面板共享同一
  边缘语言。
- `AcrylicSurface.qml`：`capture` 增加 `objectName: "acrylicCapture"`，
  供资源门禁测试直接断言。

### 16.2 新增测试（4 个）

- Header 为 Acrylic 且边缘强度与 AI 面板一致；
- 隐藏面板或切到 Safe 时 `ShaderEffectSource.enabled` 关闭（玻璃 UI 文档
  §12.1：隐藏后不得继续渲染）；
- 窗口 resize 后所有 Acrylic `captureRect` 与面板几何保持同步（文档 §13）；
- 实验控制条挂载统一边缘光。

### 16.3 验证

- 前端 pytest 171 passed / 35 skipped；ruff 通过；mypy（项目配置）通过。
- 真机 windowed 像素：Header 透出背景冷暖光晕（dark 左 76 vs 中 41，
  light 左 206 / 右 223），不再是实色 bgCanvas。
