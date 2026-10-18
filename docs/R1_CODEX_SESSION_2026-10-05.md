# R1：小说软件内的 Codex 会话

日期：2026-10-05。分支：`codex/novel-r1-codex-session`。基线：`d7e6c96`。

## 交付行为

在正常 QML 启动入口打开小说项目后，展开右侧助手栏即可使用 Codex 对话。已有文字会逐步显示，停止按钮发出真实的 `turn/interrupt` 请求。同一小说项目再次打开时，恢复原会话及最近的历史消息；项目切换后，旧会话迟到的消息不会进入新项目。

新建项目尚无章节时也能讨论创作方向。侧栏的正文生成快捷操作仍走原有独立 Writer 路径。R1 的 Codex 会话尚未提供小说检索工具，当前只依据作者在对话中给出的材料讨论。

启动位置：[启动程序.bat](../启动程序.bat)。工作区目录沿用 R0 的名称，Git 分支已转为 R1。

## 改动边界

| 文件 | 职责 |
|---|---|
| `infrastructure/codex/app_server.py` | JSON-RPC stdio 通信、子进程生命周期、连接隔离和安全失败 |
| `infrastructure/codex/session_index.py` | 校验并原子保存项目到会话编号的映射；不保存密钥或正文 |
| `application/codex_session_service.py` | 登录状态检查、会话创建/恢复、流式消息归属、停止与完成状态 |
| `ui_qml/bridge/codex_session_bridge.py` | 后台任务与 Qt 信号、消息列表更新、项目切换及错误展示 |
| `ui_qml/bridge/mock_novel_studio_facade.py` | 将普通助手对话和停止操作接到 Codex，并绑定当前项目 |
| `ui_qml/bootstrap.py` | 正常启动时组合 Codex 会话；退出时关闭其连接 |
| `CreativeAgentPanel.qml` / `AgentTextBlock.qml` | 展示 Codex 状态，模型文字按纯文本显示 |
| 三个新增测试文件 | 会话、真实 stdio 测试子进程、Qt 接线与恢复/停止的回归 |

没有修改项目数据库 schema、正式正文保存路径、独立 Writer 模型配置或全局 Codex 配置。

## 接入与存储

复用本机已登录的 ChatGPT 账号，由本地 `codex app-server` 管理认证；程序没有读取或复制登录凭据文件。当前已验证版本为 **codex-cli 0.160.0**。

项目对应的会话索引位于 `%LOCALAPPDATA%/AI Novel Studio/codex-sessions/<项目 UUID>.json`。每个项目各用一个文件，内容仅为版本和会话编号。损坏索引保留原文件并报告错误。

完整会话历史由 Codex 自身保存，界面恢复最近100条文字消息。每次发送不超过20000字；流式回复有长度上限，超限时停止并提示。小说资料仍由项目后端管理，不把会话历史作为小说事实库。

会话工作目录位于 `%LOCALAPPDATA%/AI Novel Studio/codex-workspaces/<项目 UUID>`，与开发仓库及小说正文目录分开。程序使用中文创作指令，关闭项目 AGENTS 文档读取；Codex 仍会报告全局用户指令的来源元数据。

## 本机权限验证

- `thread/start` / `thread/resume` 必须返回 `readOnly`，否则不保存会话编号、不开始推理。
- 关闭 shell、统一执行器、Code Mode 主机、应用/插件、浏览器、电脑操作、图像工具及 hooks。
- 发现本机空 MCP 表会合并既有配置，因此按有效配置逐项关闭继承的 MCP，并关闭内置执行器 MCP。操作仅通过当前子进程参数完成。
- 推理开始前检查 MCP 状态；任何可用工具、资源或未读分页都会使连接失败。关闭的服务器元数据可以存在，但没有可调用工具。
- 不接受额外命令/文件变更审批；未知服务端请求返回不支持。

以上权限已通过真实 App Server 探测确认：终端工具关闭，项目文档读取预算为0，没有额外 MCP 工具可用，会话处于只读模式。

接口依据：[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)、[官方配置文档](https://learn.chatgpt.com/docs/config-file/config-reference)，以及本机0.160.0生成的协议 schema。

## 验证结果

| 验证 | 结果 |
|---|---|
| 会话/Qt/旧 Harness/QML/消息列表的针对性测试 | 79项通过，20.12秒 |
| 最后新增的索引版本及子进程退出回归 | 相关12项补充复测通过；与上一轮合计覆盖81个不同测试 |
| Ruff | 修改范围通过 |
| MyPy | 7个相关源文件通过 |
| Git 空白检查 | 通过 |
| 真实对话 | 收到“R1 会话接入成功”，状态为 `completed` |
| 真实停止 | 首次文字到达后发出停止请求，服务端返回 `interrupted` |
| 独立服务重新连接 | 恢复同一会话的2条消息 |
| 生产 QML 原生窗口 | 实际显示 Codex 回复；关闭软件并重新启动后，历史消息仍可见 |

原生验收使用本轮创建的空白临时小说，未读取用户小说。进行了真实 Codex 验收请求，未调用独立 Writer。

本次也修正了进程退出时的等待问题：Windows 下关闭当前 App Server 的进程树，避免继承 stdout 的子进程阻塞关闭。对应测试验证关闭及时完成、读取线程退出。

复现针对性测试：

```powershell
Set-Location -LiteralPath '<repo>/'
. .\scripts\resolve_python.ps1
$r1Python = Resolve-ProjectPython
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
$r1Temp = Join-Path $env:LOCALAPPDATA ('Temp\r1-' + [guid]::NewGuid().ToString('N').Substring(0,8))
& $r1Python -B -m pytest -q -p no:cacheprovider --basetemp $r1Temp `
  tests/unit/application/test_codex_session_service.py `
  tests/unit/application/test_codex_app_server.py `
  tests/ui_qml/test_codex_session_bridge.py `
  tests/ui_qml/test_harness_agent_bridge.py `
  tests/ui_qml/test_qml_shell.py `
  tests/ui_qml/test_agent_timeline.py
```

采用短临时目录是为了避开 Windows 长路径与本机默认临时目录权限问题。原生验收应使用正常环境会话，不继承 `QT_QPA_PLATFORM=offscreen`。

## 下一票与限制

- 下一票为 R2：仅开放 Novel MCP 的当前工作区、章节目录、正文证据检索和写作约束等只读能力，并验证引用来源和项目隔离。
- R1 尚不能自动读取当前正文、通过 Codex 调用 Writer 或提交小说修改；这些按后续票接入。
- 接入协议仍有实验性标记，后续升级 CLI 时应复核握手、权限及恢复行为。本票没有执行全仓测试。
- R0 记录的 WebEngine 黑边与旧 Harness 崩溃恢复缺口仍属于独立问题。

原生验收脚本和协议证据保存在 [R1 恢复记录目录]。

## 用户启动故障修复

用户双击入口报退出码1后，在 Windows PowerShell 默认936代码页下复现了实际异常：`ModuleNotFoundError: No module named 'PySide6'`。Git 的 UTF-8 中文路径被按当前代码页错误解码，共享虚拟环境查找失败，随后误选了没有 PySide6 的系统 Python。

`resolve_python.ps1` 现在读取 Git 输出时临时使用 UTF-8，随后恢复原代码页；`launch.ps1` 用正常窗口模式启动交互界面。新增回归测试同时验证正确选中已有环境和恢复原代码页，4项启动测试通过；从原批处理入口在936代码页下实际启动并确认主界面可见、可激活。此前直接使用已选定 Python 的会话验收没有覆盖这一差异。

本次复现日志位于 `<local-workspace>`。
