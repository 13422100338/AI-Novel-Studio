# R0：恢复可运行基线与临时文件清理

完成日期：2026-10-05。功能验证与清理执行于 2026-10-04；本记录在次日完成复核。

## 交付位置

- 分支：`codex/novel-r0-baseline`。
- 基线：`f82bee07b27c706da5be510629f2fd67fb034173`。
- 工作区：[恢复版工作区](..)。
- 启动入口：[启动程序.bat](../启动程序.bat)，或该目录下的 `launch.bat`。
- 保全资料与清理清单：[恢复记录目录]。

本票建立了可启动、可编辑、可保存并重新打开项目的 QML 功能基线。主工作区仍保留原来的 `main`；本票没有将恢复分支合并到 `main`，没有继续实施 R1 的 Codex 接入。

## 最小修改

| 文件 | 修改目的 |
|---|---|
| `launch.ps1` | 双击入口转向 QML 界面；启动检查实际加载 QML；隐藏辅助控制台 |
| `scripts/resolve_python.ps1` | 当前工作树没有虚拟环境时，优先复用同仓主工作区的 `.venv`，避免误用系统 Python |
| `tests/unit/test_windows_scripts.py` | 覆盖工作树复用已有 Python 环境的回归行为 |
| `docs/CODEX_TRANSITION_ASSESSMENT_2026-10-04.md` | 纳入上一票资产评估，并更新旧集成工作树迁存后的路径 |
| 本文档 | 记录启动方式、验证结果、清理范围及剩余问题 |

没有修改小说领域逻辑、数据格式、模型路由或 AGENTS.md。编辑器依赖通过已有 npm 缓存离线安装，构建产物留在工作区，不纳入提交。

## 验证证据

- 启动脚本回归：修复前 `1 failed, 2 passed`，修复后 `3 passed`。
- Python 针对性验证：**110 passed in 28.61s**，其中已包含上述3项启动测试。
- 编辑器 TypeScript 检查与构建：`npm run build` 通过。
- 编辑器测试：**143 passed**。
- QML 启动检查：`AI_NOVEL_STUDIO_LAUNCH_SMOKE=1` 时加载到根窗口并正常退出。
- Ruff：修改的 Python 测试通过；Git 空白检查通过。
- Windows 原生界面：打开新建临时项目，显示章节与正文；在 WebEngine 编辑器中修改文字，保存后直接核对测试数据库与 Markdown，确认版本从1升到2；关闭软件、重新启动并再次打开项目，新文字仍正确显示。

原生验收只使用本轮创建的 `ui-validation/Novel-R0` 临时小说。未打开或修改用户小说，未调用真实模型。

复现本票窄测试：

```powershell
Set-Location -LiteralPath '<repo>/'
. .\scripts\resolve_python.ps1
$r0Python = Resolve-ProjectPython
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
$r0Temp = Join-Path ([IO.Path]::GetTempPath()) ('novel-r0-' + [guid]::NewGuid().ToString('N'))
& $r0Python -B -m pytest -q -p no:cacheprovider --basetemp $r0Temp `
  tests/ui_qml/test_project_wiring.py `
  tests/ui_qml/test_editor_bridge.py `
  tests/ui_qml/test_qml_shell.py `
  tests/ui_qml/test_editor_runtime.py `
  tests/ui_qml/test_editor_qml_metaobject.py `
  tests/unit/application/test_project_workspace_service.py `
  tests/integration/storage/test_recovery_services.py `
  tests/unit/test_windows_scripts.py
```

这是测试专用 PowerShell 会话。原生启动应使用另一个正常会话，避免继承 `QT_QPA_PLATFORM=offscreen`。

## C:\tmp 清理结果

顶层项目从 **844 项减到 13 项**，本轮处理以下内容：

| 类别 | 数量 | 处理方式 |
|---|---:|---|
| 旧 pytest 临时目录 | 798 | 移入回收站 |
| 带标准缓存标记的目录 | 8 | 移入回收站 |
| 空目录 | 1 | 移入回收站 |
| 旧应用日志 | 12 | 移入回收站 |
| 干净 Git 工作树 | 9 | 使用 `git worktree remove` 移除检出副本，保留分支与提交 |
| 含本地配置或未提交文档的工作树 | 3 | 使用 `git worktree move` 完整迁存到恢复记录目录 |

819项缓存/日志共包含130,491个文件，逻辑大小 **22,968,796,648 字节（约22.97 GB）**。它们目前在回收站中，**没有清空回收站，因此不宣称对应空间已经释放**。

批量永久删除在执行前被自动审批拒绝，返回 `blocked by policy`，没有提供更具体原因。本轮采用可恢复的回收站清理，并逐项记录结果；819项均成功，没有清理错误，复核时没有原路径残留。

完整迁存的工作树为 `codex-final-integration`、`opencode-docs`、`opencode-stack`。迁存前后的未提交状态保持一致；本地 `models.json` 校验和相同，其内容未输出。所有原有业务分支及提交均保留，`C:\tmp` 中已无该仓库登记的工作树。

剩余13项包括旧测试环境、无法仅凭目录信息确定用途的小说样本、诊断脚本、源码备份和少量记录。本轮保留它们，没有按名称推断为无用后删除。

另外，将 `b626` 工作树中的两个未提交恢复测试及一个散落源码备份复制到恢复记录目录，并验证文件哈希相同；原件保持不变。

清单入口：

- [缓存清理计划]
- [缓存清理结果]
- [工作树清理记录]
- [本票验证记录]

## 已知限制与下一步

1. 原生重开验收中，WebEngine 编辑区域右侧和底部出现黑边。正文加载、键盘编辑、保存和重开均成功；显示瑕疵仍需独立排查，本票不宣称界面视觉验收无缺陷。
2. 这是有限范围的基线恢复，没有运行全仓测试或真实模型验收。旧 Harness 的取消与崩溃恢复缺口仍存在。
3. 恢复版当前复用主工作区的 Python 环境；如迁走主工作区，需在恢复版工作区配置本地 `.venv`。编辑器修改后需重新执行其构建命令。
4. 下一票为 R1：在现有软件侧栏接入 Codex 会话，先完成真实对话、流式显示、中断和会话恢复。Novel MCP 只读工具继续按后续小票接入。
