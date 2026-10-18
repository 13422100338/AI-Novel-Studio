# Codex 小说工作台能力对齐

用户确认范围：以小说创作为中心，覆盖模型、思考强度、会话、附件、联网和小说 MCP；保留独立 Writer。基线 `2203e31`，实施分支 `codex/novel-codex-workbench`。

当前缺口：旧 API 设置页的剧情模型不控制 Codex；侧栏没有模型和思考强度选择，也缺少常用会话操作、附件及小说工具。本次实施让控件对应真实 API 行为。

## 实施切片

1. Codex 设置与侧栏控制：实时模型目录、支持的思考强度、登录/用量状态、联网开关；独立 Writer API 设置保留，退役旧剧情路由的 UI。
2. 会话与输入：新会话、分支、压缩、运行中追加要求、图片/文本附件、上下文用量与工具/计划进度。
3. 只读 Novel MCP：使用已打开项目，提供当前编辑快照、章节、正文证据及写作约束；绑定项目身份并限制结果长度，禁止写入。
4. 对每个切片运行窄测试，最后做真实模型设置、联网、附件、会话操作及 MCP 验收和原生视觉检查。

## 核实的 API

- `model/list` 返回模型名称、支持的 effort 和输入类型；目录不是账户权限保证。
- `turn/start.model` 与 `effort` 控制当前及后续 turn；首次/重新连接通过 `thread/start` 或 `thread/resume` 的 model/config 设置。
- 联网通过 `config.web_search` 在无活动 turn 时重连/恢复生效，不更改本地命令网络权限。
- `thread/fork` 创建分支；新会话不删除原历史；压缩用 `thread/compact/start`，等待压缩完成事件后显示完成。
- `turn/steer` 在运行中追加输入；图片使用已核实的 `localImage` 输入。
- `thread/tokenUsage/updated`、`turn/plan/updated`、工具 item 事件用于侧栏进度。
- `account/read` / `account/rateLimits/read` 用于账号与用量；不读取或复制密钥。

依据：本机 CLI 0.160.0 生成 schema、[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)、[官方配置文档](https://learn.chatgpt.com/docs/config-file/config-reference)。

## 最小涉及文件

- 新增 `infrastructure/codex/preferences.py`、`application/codex_controls_service.py`、`ui_qml/bridge/codex_controls_bridge.py`。
- 扩展已有 `app_server.py`、`codex_session_service.py`、`codex_session_bridge.py` 与 Facade/bootstrap 接线。
- 新增 `application/novel_read_service.py`、`infrastructure/storage/read_only_database.py` 与 `infrastructure/mcp/novel_server.py`；在 `pyproject.toml` 固定 MCP SDK 版本。
- 新增 `CodexControls.qml`；更新 `App.qml`、`SettingsPage.qml`、`CreativeAgentPanel.qml`、`AgentComposer.qml`、`AgentTextBlock.qml`，以及 `model_settings_bridge.py` 的独立模型展示文案。
- 添加设置传参、会话操作、附件校验、工具只读/隔离及 QML 测试。
- 新增 `scripts/verify_codex_workbench.py` 与 `scripts/preview_codex_workbench.py`，用于隔离测试小说的实际接入及窗口验收。

## 验收要求

选择模型/思考强度后检查实际 turn 参数；重启保留选项；联网切换真实生效。会话分支/新会话不删除历史；压缩与停止不以请求回包冒充完成。附件按模型能力和大小验证。MCP 不能调用含隐式写入的 `ProjectRepository.open`、`workspace.load_chapter` 或 `requirements.get_or_create`；只复用已经打开的项目和只读服务。工具带来源版本/哈希，项目切换拒绝旧访问。API Key、数据库、正文与全局 Codex 配置不进入此次写入范围。

## 已交付

- 设置页将 Codex 与独立写作模型分开。侧栏使用真实模型目录和该模型支持的思考强度，保存到本软件的偏好文件；同时提供联网开关、账号状态、最近请求 token 用量和工具/计划进度。
- 会话支持新建、分支、历史切换、压缩、停止和运行中追加要求。原会话保留；空会话首次发送后才记录可恢复编号。
- 附件支持 PNG/JPG/WebP/GIF，以及 UTF-8 TXT/Markdown。每次最多4个；图片20MB以内，文本100KB且不超过20000字。文本随本轮输入传入，图片使用 `localImage`；图片发送前核实模型能力。
- Novel MCP 提供6个只读工具：当前作品/编辑快照/选区、章节列表、正式正文片段、正式正文证据、作者计划/约束、人物名称/别名查询。使用只读 SQLite 连接，不生成章节要求或执行迁移。项目切换立即撤销旧工具访问。
- 修改建议快捷按钮交给 Codex；“写作模型草稿”使用已有独立 Writer 和审稿流程。候选正文的生成和接受不交给这票的只读 MCP。

## 实际接入中的修正

CLI `-c` 使用点分键，会话 RPC 使用嵌套配置；两者不可直接复用。同样的 MCP 禁用配置在会话中必须重新验证，启动后通过 `mcpServerStatus/list(threadId)` 确认实际工具目录。

当前模型通过 `code_mode_host` 调度 MCP/联网。保留这个调度层，并关闭终端、通用执行、应用/插件、电脑/浏览器操作、文件写入许可及其他 MCP。本机编码技能只在小说会话中禁用，防止旧识图桥或开发工作流影响附件处理；全局 Codex 设置不改动。

MCP SDK 固定为 `mcp==1.26.0`。服务绑定随机本机端口，临时鉴权令牌只通过 Codex 子进程环境传入，命令行、会话索引和配置文件不含令牌。校验 Host、Origin、请求大小和工具参数，关闭项目时关闭服务。

## 验证记录

95项相关测试分组通过：Codex/MCP 36项、QML 外壳39项、独立写作模型设置13项、Codex 控件接线1项、消息布局6项。Ruff 通过，15个相关源文件的严格类型检查通过；Windows PowerShell 5.1 启动冒烟检查退出码为0。

真实登录账号使用 `gpt-6.1-sol / low` 验收通过：调用小说上下文、章节和正文工具，区分未保存结尾，读取文本暗号和图片 Base URL，进行联网查询，创建并保留3个会话，恢复原会话并完成压缩。验收脚本只创建新的测试小说，未修改作者小说或 API 密钥。

可复现命令（在本工作树运行，使用 `scripts/resolve_python.ps1` 得到 Python，并设置 `PYTHONPATH=src`）：

```powershell
python -B -m pytest -q -p no:cacheprovider tests/unit/application/test_codex_controls_service.py tests/unit/application/test_codex_session_service.py tests/unit/application/test_codex_app_server.py tests/ui_qml/test_codex_session_bridge.py tests/integration/application/test_novel_mcp.py
python -B scripts/verify_codex_workbench.py --image <本机测试图片路径>
```

真实脚本使用当前登录账号，会消耗用量；所有测试项目、偏好和索引在新建的本机临时目录。GUI 测试使用 `QT_QPA_PLATFORM=offscreen`，pytest 的 `--basetemp` 应使用短路径，避免 Windows 路径长度限制。

## 限制与后续

PDF/Word 附件、小说 MCP 写操作、通过 Codex 调用独立 Writer、正式 Plan 模式及通用终端/Git 不在本票。历史界面仅加载最近100条消息，完整会话仍由 Codex 保存。目录代表可选配置，不保证每个模型的账户权限；上下文预算展示的是配置值，未冒充实际容量。

原生窗口已显示新侧栏及真实模型。后续桌面点击检查收到用户 Esc 中止信号，已停止输入，未声明完整点击验收通过。首次混合 Qt 测试曾发生 Windows 原生访问冲突，各相关组在独立进程重跑通过，混合批次的崩溃原因尚未定位。SDK 与当前 pydantic-settings 组合有一条 lifespan 前向引用警告，HTTP 鉴权、调用和关闭测试均通过。

当前启动入口为本工作树的 `启动程序.bat` / `launch.bat`。已有窗口不会热更新，需要关闭后重新启动。下一票建议接通“Codex 调用独立 Writer → 候选稿 → 作者审阅接受”的小说 MCP 流程。
