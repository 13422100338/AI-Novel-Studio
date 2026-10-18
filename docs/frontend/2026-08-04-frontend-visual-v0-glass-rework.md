# Frontend Visual V0 玻璃化返工（实时 Acrylic 实验）

> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 起因：用户反馈 Visual V0 玻璃效果“一般般”，要求结合 design/animation skill 并
> 联网调研玻璃化（Glassmorphism）经验后返工。
> 性质：**仅改动独立样板页 `VisualLab.qml`（`--visual-lab`）**；正式界面
> `App.qml` / NavigationRail / CreativeAgentPanel 等全部未改动。

## 1. 联网调研结论（返工依据）

### 1.1 NNGroup《Glassmorphism: Definition and Best Practices》

- 玻璃态 = **不透明度 × 背景模糊** 两个特征缺一不可。仅做半透明 + 边框 + 噪声、
  没有模糊，看起来就是普通半透明面板——这正是原 `GlassSurface`“一般般”的根因。
- 最佳实践：① 文本必须满足对比度；② 模糊要足够强（约 25–100px），复杂背景更需要；
  ③ 允许用户调整透明度（对应质量档 Safe/Balanced/Premium 的设计）。
- 玻璃在**复杂/渐变背景**上才突出：实验页背景应是多色块、有内容的复杂背景。

### 1.2 Qt 官方博客《Qt Quick and Blurred Panels》

- 关键思路：**模糊的是面板背后的内容，不是面板本身**。
- 简单场景：`ShaderEffectSource(sourceItem=背景层, sourceRect=面板区域)`
  + `MultiEffect(blurEnabled, autoPaddingEnabled:false, blurMax)`；
- 高级场景：用 `maskEnabled/maskSource`（layer 化的圆角矩形）实现非矩形模糊；
- 性能：模糊像素越少越好；`autoPaddingEnabled:false` 防止效果跑到窗口外。

### 1.3 PyHuskarUI `HusAcrylic.qml`（Fluent Acrylic 分层参考）

- 分层顺序：`ShaderEffectSource` 捕获背后 → `MultiEffect blurMax≈32`
  → 亮度层（luminosity）→ 色调层（tint，opacity≈0.65）→ 平铺噪声 PNG（opacity≈0.02）；
- `sourceRect` 必须按组件在源层坐标系中的位置映射（本项目用 `mapToItem` 并显式
  在几何变化时重算，避免 QML 绑定无法追踪函数结果的问题）。

### 1.4 Qt MultiEffect 文档 / 社区性能经验

- `blur: 0..1`，`blurMax` 有效范围 2–64（默认 32）；饱和/亮度为 0 时无变化；
- `maskSource` 可指向 `layer.enabled` 的 Item；阈值/扩散控制边缘柔和度；
- 性能门禁：blur/shadow 最重；不在动画中改 `blurMax`/`autoPaddingEnabled`；
  空闲时关闭效果（`enabled:false`）避免 GPU 常驻开销；
- 探测验证：本机 Qt 6.11.1 在 offscreen + software 后端下 MultiEffect 模糊正常
  渲染（面板区域像素出现红蓝交界混合色，未模糊时为纯蓝）。

## 2. 返工实现

### 2.1 新组件 `qml/surfaces/AcrylicSurface.qml`

- `sourceItem`（必填）：被模糊的背景层；调用方传入**不包含本面板**的层，
  从构造上杜绝 ShaderEffectSource 自捕获递归；
- `ShaderEffectSource(sourceRect=面板在背景层中的映射区域, enabled=effectActive)`
  + `MultiEffect(blurMax 24/40, mask 圆角, autoPaddingEnabled:false)`
  → 亮度层 → 色调层（`acrylicTint` + `glassTintOpacity 0.62`）→ 顶部内高光 /
  底部深边 → `NoiseOverlay`；
- 质量档：
  - **Safe**：完全实色（`bgSurface`），无 Shader、无 MultiEffect；
  - **Balanced**：`blurMax 24`，中性饱和/亮度；
  - **Premium**：`blurMax 40`，light 主题微去饱和 + 提亮（frost 质感）；
- 性能门禁：`visible=false` 或 Safe 时 `capture.enabled=false`、
  `MultiEffect.enabled=false`；背景层为静态内容，不每帧重算；
- 测试钩子：`effectActive` / `blurEnabled` / `captureRect` / `fillColor`。

### 2.2 `VisualLab.qml` 实验页

- 新增 `labBackgroundLayer`：主题化渐变底 + 竖格线 + 低饱和色块 + 手稿摘录卡
  + 大纲卡（“复杂背景”让玻璃可感知；保持低对比、不 RGB 化）；
- AI 主面板改用 `AcrylicSurface`（实时模糊），保留模拟 `GlassSurface` 对比；
- 材质对比行扩为三项：**玻璃（模拟） / Acrylic（实时） / 实色**；
- 文案同步修正（原“所有表面均不实时模糊”已不准确）。

### 2.3 Design Tokens（`bridge/theme_provider.py`）

`material` 新增：`acrylicTint`、`acrylicLuminosity`、`glassBlurBalanced`(24)、
`glassBlurPremium`(40)、`glassTintOpacity`(0.62)、`glassSaturation`、
`glassBrightness`；仅实验页消费，正式 Shell 不受影响。

## 3. 六个 design/animation skill 的应用

- **agent-reach**：联网路由（Exa/网页/Jina Reader/GitHub API）完成上述调研；
- **animation-vocabulary / find-animation-opportunities**：本次是材质返工而非新增
  动效；三列 50ms stagger 入口保留，未给高频元素加动画（沿用既有决策）；
- **apple-design §12 材质**：半透明材料用于层次而非注意力；不叠放浅色透明表面；
  高对比文本；reduce-motion 不受影响（材质不随动效开关变化）；
- **emil-design-eng**：克制——背景装饰全部低饱和度低透明度；无新增动画；
- **improve-animations / review-animations**：本 diff 未新增/修改任何动画，
  既有动效（stagger/fade/glow 2.8s）维持原评审结论（Approve）。

## 3.1 系统背板模式（Mica：底板透壁纸，面板不透）

用户方向：底板可以微微透出窗口后面的桌面壁纸，但各个面板只保留玻璃质感、
**不**透出壁纸。已按此在实验页落地：

- 新增 `bridge/windows_backdrop.py`：`DwmSetWindowAttribute(38, DWMSBT_MAINWINDOW=2)`
  请求 DWM 在整窗后面绘制 Mica（壁纸模糊采样）；仅 Windows 11 22621+ 生效，
  任何失败静默返回 False（规范 12：系统材质必须可回退，不影响正常渲染）；
- `bootstrap.py --visual-lab` 启动时应用 Mica 并把结果写入
  `systemBackdrop` 属性；QML 据此分支：
  - **Mica 模式**：窗口底色透明（`color: "transparent"`），底板绘制
    半透明主题色辅助层（近似 Mica 自身的着色 + 噪声，保证文字可读），
    隐藏应用内装饰背景；AI 面板切换为 `GlassSurface.opaque`
    （实色底 + 顶部内高光 + 细边 + 噪声——有玻璃质感但绝不透壁纸）；
    材质对比行显示「玻璃（模拟） / Mica 底板 / 实色」；
  - **无系统背板**（Win10 / offscreen / 调用失败）：完全保持原有路径
    （复杂背景 + 实时 Acrylic 面板），行为与上轮一致；
- `GlassSurface.qml` 新增 `opaque` 属性（默认 false，正式 Shell 不用）；
- 截图脚本新增 `--windowed` 参数，用于真机捕获 Mica 效果；默认 offscreen
  模式不受影响。

质量档在 Mica 模式下必须肉眼可区分（用户反馈“三档看不出区别”后的返工）：

- **Safe**：`DwmSetWindowAttribute(38, DWMSBT_NONE)` 关闭系统背板 + 窗口
  恢复不透明主题色——壁纸完全不透出，回到应用内 Acrylic 路径（Safe 渲染为
  实色面板）；
- **Balanced**：Mica（`DWMSBT_MAINWINDOW`），窗口透明，壁纸经半透明主题
  洗白层透出（wash alpha 0.80），面板为不透壁纸的玻璃；
- **Premium**：Desktop Acrylic（`DWMSBT_TRANSIENTWINDOW`，更亮），洗白层
  更薄（alpha 0.66），壁纸透出更明显；
- 档位切换时 Python 监听 `Theme.quality_changed` 重新下发对应 DWM 背板
  （失败静默忽略，窗口保持正常渲染）；
- 顶栏新增「系统背板」状态芯片，实时显示 `Safe 关闭 / Mica / Desktop Acrylic`，
  用于确认 DWM 调用是否真的生效（offscreen 路径自动隐藏）。

真机诊断（2026-08-04，Win11 + 壁纸为 Windows 聚焦风景图）：

- `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)` 返回 **S_OK (0x0)**，
  系统背板调用一直成功；
- Qt 6.11 透明 QQuickWindow 的 ExStyle 为 `0x100`，**未设置 WS_EX_LAYERED**，
  不存在 layered 冲突；
- 因此此前“一团灰、换档只变深浅”的根因是：底板上叠加的 0.8 不透明度
  主题洗白层把 Mica 完全盖住（Safe 档没有该层所以正常）。

修复：洗白层大幅调淡——Balanced `wash 0.80 → 0.32`，Premium `0.66 → 0.18`，
让壁纸的模糊色彩真正透出；Premium 使用更薄的洗白层以拉开与 Balanced 的
档位差异。

## 4. 验证

```text
pytest（独立前端）    154 passed, 35 skipped
pytest（c9a2 集成）   230 passed
ruff                 通过
mypy                 通过（42 files）
```

- 新增测试：Safe 档关闭 blur/实色降级、Balanced/Premium 开启 blur、
  `captureRect` 跟随面板几何、`sourceItem` 指向背景层、新 token 断言、
  `systemBackdrop` 切换（透明窗口 + 不透壁纸玻璃面板 + Mica 对比件）、
  DWM 常量与失败安全（非支持环境一律返回 False、永不抛异常）；
- 像素验证：Safe 前后截图在面板区域完全一致（无回归）；Balanced 空白区
  sd 36.9 → 24.2（细节被模糊抹平）且整体变暗（tint 0.62 叠加），证明实时
  背景模糊生效。

真机 Mica 验证（需要 Windows 11 22H2+，且能直接看到壁纸透出）：

```powershell
.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml --visual-lab
# 或真机截图：
.\.venv\Scripts\python.exe scripts\capture_frontend_visual_lab.py --windowed
```

截图（`docs/frontend/screenshots/`，旧图为 before，`*-glass-*` 为 after）：

| before | after |
| --- | --- |
| `visual-lab-paper-balanced.png` | `visual-lab-glass-paper-balanced.png` |
| `visual-lab-paper-safe.png` | `visual-lab-glass-paper-safe.png` |
| `visual-lab-dark-premium.png` | `visual-lab-glass-dark-premium.png` |
| `visual-lab-light-safe.png` | `visual-lab-glass-light-safe.png` |
| `visual-lab-paper-glow-success.png` | `visual-lab-glass-paper-glow-success.png` |

## 5. 边界与接线点

- 正式界面零改动；`GlassSurface`（模拟玻璃）保留供对比；
- 实时 Acrylic 仍属**实验评估**：若用户认可方向，再按规范 Visual V1
  （静态材质统一）→ V4（可选 Windows Mica）推进，且需先过性能门禁
  （窗口 1080×680 起、缩放 100/125/150%、AI Dock 开关不重绘 WebEngine）；
- 规范 9.3：任何情况下不得对 WebEngineView 施加实时 Blur/大面积 MultiEffect；
- 未来若接入真实窗口背景，可将 `sourceItem` 指向 Shell 的背景层并保持
  “背景层不含面板”的约束。

## 6. 下一步（待用户确认）

1. 本机运行 `.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml --visual-lab`，
   切换质量档观察 Acrylic 效果（正式界面入口不受影响）；
2. 若认可 → 讨论 Visual V1 中哪些表面启用实时 Acrylic、哪些保持模拟玻璃；
3. 若仍需调整 → 在本样板页迭代（tint 透明度 / blurMax / 噪声 / 背景复杂度）。
