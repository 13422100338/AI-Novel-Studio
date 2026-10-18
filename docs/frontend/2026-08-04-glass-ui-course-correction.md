# AI Novel Studio 玻璃化 UI 路线纠偏与后续实施任务

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 当前分支：`codex/frontend-agent-c1`
> 当前工作树：`<local-workspace>`
> 当前已知 HEAD：`f0c6dfa`
> 依据文档：`2026-08-04-glassmorphism-ui-log.md`
> 本文性质：**视觉技术路线纠偏，不要求现在接入正式 Shell，不进入后端开发，不做全面视觉重构。**

---

# 1. 背景

此前已经尝试在 `--visual-lab` 独立实验页中实现玻璃化 UI，主要包含两条技术路线：

```text
路线 A：应用内实时 Acrylic
ShaderEffectSource
→ 捕获应用内背景
→ MultiEffect 模糊
→ Tint / Luminosity / Noise / Border
```

```text
路线 B：系统级 Mica / Desktop Acrylic
DwmSetWindowAttribute
→ Windows DWM 在窗口后绘制系统背板
```

现有日志表明：

- 路线 A 已经能够工作；
- 路线 B 的 DWM 调用返回成功；
- 但路线 B 的最终视觉效果未达到用户目标；
- 当前看到的主要表现仍是灰色、低对比、缺少明确玻璃层次；
- 最后一版将洗白层透明度从 `0.80 / 0.66` 降到 `0.32 / 0.18`，但尚未经过用户确认；
- 用户已暂停该方向。

本轮需要基于现有成果进行路线纠偏，而不是继续盲目调整 Mica 参数。

---

# 2. 用户真正想要的视觉效果

用户目标不是单纯的 Windows Mica，也不是整个窗口透明。

目标视觉结构应理解为：

```text
窗口底层
→ 有柔和色彩、空间感和轻微通透感

导航 / 章节栏 / AI 面板
→ 有真实玻璃质感
→ 可以看到应用内背景被模糊
→ 不能看清桌面、图标或其他程序

正文编辑区
→ 稳定、暖白、不透明
→ 像一张纸
→ 不参加毛玻璃与动态模糊

AI 工作状态
→ 有克制流光边框
→ 仅当前活动区域发光
→ 空闲时安静
```

整体气质：

> **暖色文学纸张 + 冷色智能玻璃。**

这与“让整个 Qt 窗口直接透出桌面壁纸”不是一回事。

---

# 3. 本次失败的核心原因

## 3.1 把 Mica 当成了主要视觉来源

Mica 的作用更接近：

```text
根据桌面壁纸和系统主题
生成低调、稳定的窗口环境色
```

它不是强烈的毛玻璃，也不会自然形成概念图中明显的层次和模糊。

即使 DWM 调用成功，最终也可能只表现为：

- 灰色；
- 米灰；
- 低饱和壁纸色；
- 很弱的材质变化。

因此：

> `DwmSetWindowAttribute()` 返回 `S_OK`，不等于最终视觉已经符合目标。

## 3.2 DWM 成功不代表完整合成链路成功

当前诊断仅证明：

- Windows 接受了系统背板属性；
- 当前系统版本支持；
- 窗口没有 `WS_EX_LAYERED`；
- API 返回成功。

但最终显示还经过：

```text
Windows DWM 背板
↓
Qt Quick Window
↓
ApplicationWindow 背景
↓
QML 根节点
↓
主题洗白层
↓
其他 Rectangle / Surface
↓
用户最终看到的像素
```

只要 QML 中间存在高透明度遮罩或不透明层，系统背板就会被盖住。

因此当前不能将“API 返回成功”直接等同于“Qt 客户区已经正确展示 Mica”。

## 3.3 洗白层过重

此前：

```text
Balanced wash opacity = 0.80
Premium wash opacity = 0.66
```

这几乎等于在系统背板上覆盖一层实色背景。

即使修改为：

```text
Balanced = 0.32
Premium = 0.18
```

也只能解决“被完全盖住”的问题，不能保证 Mica 本身会呈现理想的玻璃效果。

这项修改可以保留作为实验结果，但不能继续被视为主路线修复。

## 3.4 面板改成 opaque 后，失去了真正背景模糊

为满足：

```text
面板有玻璃质感
但不能透出桌面壁纸
```

现有实现将部分面板改成：

```text
GlassSurface.opaque
```

这能够避免桌面内容透出，但其本质可能变成：

```text
实色背景
+
边框
+
高光
+
噪声
```

如果没有模糊面板后方的应用内内容，它只是“玻璃装饰风格”，不是真正的 Acrylic。

最终容易出现：

```text
底层：低对比灰色 Mica
面板：普通米色卡片加高光
```

这与理想概念图存在明显差距。

## 3.5 质量档使用了不同系统材质，而不是同一效果的质量分级

当前设计：

```text
Safe       → 关闭系统背板
Balanced   → Mica
Premium    → Desktop Acrylic
```

这三档不是同一套视觉架构的强弱差异，而是三种不同的系统合成模式。

问题包括：

- 行为不一致；
- Windows 版本差异大；
- 难以比较；
- 难以复现；
- 难以维护；
- Bug 定位困难；
- 最终视觉不可控。

质量档应该共享相同的基础结构，只改变效果强度和成本。

---

# 4. 技术路线决策

## 4.1 主路线调整

停止将以下方案作为主要视觉路线：

```text
透明 Qt 窗口
+
系统 Mica / Desktop Acrylic
+
DWM 材质决定主要视觉
```

新的主路线应为：

```text
不透明 Qt Quick 窗口
+
应用内 BackdropLayer
+
应用内 Acrylic 面板
+
不透明 PaperSurface 正文
+
独立 StreamingGlowBorder
```

这是正式建议。

## 4.2 系统 Mica 的新定位

系统 Mica 可以保留为：

```text
可选实验
或低优先级增强
```

但不再作为：

- Premium 档核心；
- 正式 Shell 的必要能力；
- 达成概念图的主要手段；
- 窗口底板的唯一实现。

相关 DWM 封装、诊断脚本和实验记录可以保留，避免重复研究。

正式功能不得依赖它。

---

# 5. 建议保留的现有成果

保留以下模块与经验：

```text
AcrylicSurface.qml
GlassSurface.qml
NoiseOverlay
VisualQuality / Theme 质量档基础
VisualLab.qml
windows_backdrop.py
diagnose_windows_backdrop.py
真机截图脚本
DWM 兼容性与失败回退经验
```

保留原因：

- 应用内 Acrylic 已经被验证可用；
- 视觉实验页有继续迭代价值；
- DWM 调研和诊断结果可作为未来参考；
- 当前工作没有污染正式 Shell；
- 失败经验对正式接入非常重要。

不要无理由删除代码和文档。

---

# 6. 建议冻结的方向

以下内容不再继续主动扩大：

```text
透明 ApplicationWindow 作为正式默认
Mica 作为正式主背景
Desktop Acrylic 作为 Premium 核心
质量档切换不同 DWM 类型
为了显示 Mica 反复调整窗口透明属性
```

冻结的含义：

- 保留代码和实验入口；
- 不继续投入大量时间；
- 不接入正式 `App.qml`；
- 不阻塞后续功能开发；
- 不再用 Mica 视觉结果作为概念图验收标准。

---

# 7. 新的目标架构

## 7.1 BackdropLayer

新增或明确一个应用内背景层：

```text
BackdropLayer.qml
```

职责：

- 提供温暖渐变；
- 提供低对比冷暖色光团；
- 提供极轻纹理；
- 根据 paper / light / dark 主题变化；
- 为 Acrylic 面板提供可模糊的源；
- 不包含正文、卡片或面板本身；
- 避免自捕获递归。

示意结构：

```text
ApplicationWindow
├── BackdropLayer
├── NavigationRail AcrylicSurface
├── ContextSidebar AcrylicSurface
├── MainWorkspace
│   └── PaperSurface
└── AgentDock AcrylicSurface
```

## 7.2 AcrylicSurface

继续以当前成功路线为基础：

```text
ShaderEffectSource
→ 捕获 BackdropLayer 对应区域
→ MultiEffect blur
→ luminosity
→ tint
→ noise
→ highlight border
```

要求：

- `sourceItem` 只能是专用背景层；
- 不能捕获组件自身；
- `sourceRect` 必须正确映射；
- 圆角 Mask 必须稳定；
- 隐藏时关闭捕获与效果；
- Safe 档不创建高成本效果；
- 不在动画中修改 `blurMax`；
- 不对 WebEngineView 使用该效果。

## 7.3 PaperSurface

正文使用独立组件：

```text
PaperSurface.qml
```

要求：

- 完全不透明；
- 暖白；
- 极轻静态纹理；
- 柔和静态阴影；
- 不使用 ShaderEffectSource；
- 不使用实时 Blur；
- 不透出桌面或应用背景；
- WebEngine 明确设置背景色；
- 正文输入、滚动、切章稳定优先。

## 7.4 StreamingGlowBorder

流光与玻璃解耦。

新增或后期实现：

```text
StreamingGlowBorder.qml
```

仅用于：

- 当前活动 AI Dock；
- 当前运行中的 Agent 卡片；
- AI 输入框生成状态。

要求：

- 同时最多 1–2 个实例；
- 1–2px 细边；
- 2.4–3.2 秒周期；
- 空闲时停止；
- `reduceMotion` 时静态降级；
- Shader 失败时退化为普通状态边框；
- 不允许所有卡片同时发光。

---

# 8. 可选真实壁纸方案

如果未来仍希望底板微微带入用户桌面壁纸色彩，不建议使用透明窗口直接显示桌面。

推荐可选方案：

```text
读取当前桌面壁纸
→ 按当前显示器与窗口位置裁切
→ 大幅降采样
→ 预模糊
→ 叠加主题色
→ 作为 BackdropLayer 图像源
```

优势：

- 不会显示其他程序；
- 不会显示桌面图标；
- 不需要透明 WebEngine 窗口；
- Windows 10 / 11 都可支持；
- 视觉完全可控；
- 可以缓存；
- 不需要每帧更新；
- 截图可复现；
- 失败时回退应用内渐变。

更新时机：

```text
启动时
壁纸变化时
窗口切换显示器时
Resize 完成后
```

禁止每帧截图桌面或持续重新模糊。

此方案仅作为未来 Premium 可选背景源，不在当前阶段实现。

---

# 9. 重新定义质量档

## Safe

```text
不透明窗口
实色 Canvas
实色面板
无 Blur
无 Shader
无 Noise 动画
无流光
静态边框和阴影
```

## Balanced（默认）

```text
不透明窗口
应用内渐变 BackdropLayer
AcrylicSurface 使用轻度模糊
静态 Noise
少量静态阴影
AI 状态使用普通高亮边框
```

## Premium

```text
不透明窗口
更精细 BackdropLayer
可选静态壁纸采样
更高质量 Acrylic
更细腻 Noise 与阴影
StreamingGlowBorder
克制过渡动效
```

三档必须共享：

```text
同一窗口合成模式
同一组件结构
同一布局
同一交互
```

仅改变：

- 是否启用模糊；
- 模糊采样质量；
- Noise；
- 阴影；
- 动效；
- 背景源。

---

# 10. 当前阶段的具体行动

本轮不要继续做正式 UI 美化。

只需要：

1. 将本路线纠偏写入文档；
2. 保留现有 `--visual-lab`；
3. 在 VisualLab 中增加新的 BackdropLayer 实验方向；
4. 将路线 A 标为推荐主路线；
5. 将系统 Mica 标为可选实验；
6. 不修改正式 `App.qml`、`NavigationRail`、`WritingPage`、`CreativeAgentPanel`；
7. 不接入正式 WebEngine；
8. 不开发真实壁纸采样；
9. 不开发正式流光 Shader；
10. 等后端、Agent、C1–C5 和写作闭环完成后再重启 Visual V0。

若需要提交本轮文档与最小实验调整，建议独立提交：

```text
docs(frontend): redirect glass UI toward app-controlled acrylic
```

不得自动合并 `main`。

---

# 11. Visual V0 恢复后的实施顺序

## Step 1：重构实验页背景层

建立：

```text
BackdropLayer
```

包含：

- 主题渐变；
- 低饱和色团；
- 轻纹理；
- 多种测试背景复杂度。

## Step 2：验证 Acrylic

验证：

```text
导航样板
章节栏样板
AI 面板样板
普通 Agent 卡片
重点 Agent 卡片
```

所有 Acrylic 都捕获同一应用内 BackdropLayer。

## Step 3：验证正文纸张

加入：

```text
PaperSurface
```

对比：

```text
透明玻璃面板
+
稳定不透明正文
```

## Step 4：质量档

使用同一组件结构验证 Safe / Balanced / Premium。

## Step 5：流光样板

只在实验页实现一个活动 AI 边框。

## Step 6：性能门禁

通过后，才讨论正式 Shell 接入。

---

# 12. 性能与鲁棒性要求

## 12.1 Acrylic

- 模糊区域越小越好；
- 隐藏时关闭 capture；
- 不在空闲状态持续更新；
- 不对 WebEngine 使用；
- 不模糊整个窗口；
- 不为每张 Agent 卡片单独捕获完整背景；
- 优先共用背景源；
- 不在动画期间改变 `blurMax`。

## 12.2 WebEngine

正式接入时：

- 窗口保持不透明；
- `WebEngineView.backgroundColor` 明确；
- 网页根元素背景明确；
- AI Dock 不连续动画改变 WebEngine 宽度；
- Resize 采用瞬切、拖动预览线或节流；
- 不能因为视觉效果重新加载章节。

## 12.3 回退

任意以下情况：

```text
Shader 编译失败
MultiEffect 不可用
软件渲染后端
GPU 驱动异常
低性能设备
reduceMotion
用户关闭透明效果
```

都必须自动进入 Safe 或 Balanced。

业务功能不得依赖视觉效果。

---

# 13. 必须新增的验收场景

视觉实验页恢复后至少验证：

```text
Windows 10
Windows 11
100% / 125% / 150% / 200% DPI
1100×680
1440×900
1920×1080
普通核显
中端独显
软件渲染回退
```

检查：

- 玻璃面板后确实有应用内背景模糊；
- 看不到桌面图标和其他程序；
- 正文完全不透明；
- 三档区别清楚但结构一致；
- 不出现黑块；
- 不出现白块；
- 不出现自捕获递归；
- 不出现边缘错位；
- 不出现窗口 Resize 闪烁；
- Safe 档关闭全部高级效果；
- 隐藏面板后不继续渲染。

---

# 14. 当前禁止事项

禁止：

- 继续把 Mica 参数微调当成主要任务；
- 将透明窗口接入正式 Shell；
- 将 Desktop Acrylic 作为 Premium 唯一路线；
- 为了视觉效果修改后端；
- 对 WebEngine 使用实时模糊；
- 每张卡片单独建立昂贵 Blur；
- 读取桌面实时画面；
- 每帧截图壁纸；
- 自定义无边框窗口；
- 现在就全面替换正式 UI；
- 现在就开发完整流光系统；
- 因为实验失败推翻 QML + WebEngine 架构；
- 删除已经验证可用的 AcrylicSurface。

---

# 15. 最终结论

本次实验不是完全失败。

已经证明：

```text
应用内 Acrylic 可以工作
DWM 系统背板调用可以成功
Safe 回退机制可以建立
透明窗口和 Qt 合成存在额外风险
高透明度洗白层会掩盖系统材质
Mica 本身不足以承担理想 UI 的主要视觉
```

真正需要纠正的是主次关系。

错误路线：

```text
系统 Mica 是主角
应用内 Acrylic 是补充
```

正确路线：

```text
应用内 BackdropLayer + Acrylic 是主角
Mica 只是可选实验或增强
```

最终正式方案：

```text
不透明 Qt Quick 窗口
+
应用内受控背景
+
应用内 Acrylic 面板
+
不透明正文纸张
+
独立 AI 流光状态
+
所有效果可回退
```

一句话原则：

> **不要依赖系统窗口透明来制造高级感，而要由应用自己控制背景、玻璃、纸张和动态状态。**
