# Codex 目录连接失败修复

基线 `1931a08`。用户界面显示“Codex 目录刷新失败，请检查登录和连接后重试”。

## 原因与复现

同一份 Codex CLI 0.160.0，在普通启动时能够初始化；使用小说软件原有配置时立即以退出码1结束，错误为 `invalid transport in mcp_servers.node_repl`。

原接入代码固定写入 `mcp_servers.node_repl.enabled=false` 和 `mcp_servers.cua_repl.enabled=false`。当本机没有这些服务器定义时，覆盖项会新建缺少 command/url 的服务器表，Codex 在读取配置时失败，尚未进入账号读取流程。设置桥接层又把所有异常统一显示为登录/网络提示，掩盖了原因。

## 改动

- `infrastructure/codex/app_server.py`：移除固定的缺少传输定义的服务器覆盖项；继续读取有效配置，仅禁用实际存在的服务器，并保留工具目录校验。
- `ui_qml/bridge/codex_controls_bridge.py`：展示已有的安全连接错误；未知异常仍隐藏内部细节，不显示密钥或原始 API 负载。
- `test_codex_app_server.py`：覆盖无 MCP、普通 MCP 和具有完整连接定义的内置 MCP 三种环境。
- `test_codex_controls.py`：覆盖具体安全错误显示及未知错误信息过滤。
- `test_codex_session_service.py`：更新断言，确保空 MCP 配置中不生成没有连接定义的节点。

## 验证

39项相关测试通过，Ruff 和相关源文件类型检查通过。真实目录刷新显示 ChatGPT 已登录并返回7个模型；新建隔离测试小说的 MCP 接入成功。重启原生软件后，设置页和侧栏均成功显示模型及思考强度，模型下拉列出7个模型，原报错消失。

没有修改全局 Codex 设置、登录凭据、写作 API 密钥或作者小说。界面的“请打开项目”仍然表示尚未选择小说项目，与账号连接状态独立。

## 桌面启动环境的后续修复

用户再次反馈的错误已变为“没有找到 Codex，请检查安装及 PATH”。前次验证继承了 Codex 桌面程序注入的环境，未覆盖从 Explorer 直接启动的情况；普通桌面进程的 PATH 中没有 Codex CLI。

`app_server.py` 增加可执行文件查找：优先使用 PATH；Windows 下找不到时，仅检查 `%LOCALAPPDATA%/OpenAI/Codex/bin` 下一层的完整 Codex 运行时，选择有效的 `codex.exe`，忽略没有可执行文件的目录。所有启动仍使用绝对路径和无 shell 调用；不修改系统 PATH，不读取或改写凭据。

追加3项回归测试，覆盖 PATH 优先、没有 PATH 但存在桌面版，以及未安装场景。42项相关测试、Ruff 和类型检查通过。

真实验证将子进程 PATH 限制为 Windows System32，`shutil.which('codex.exe')` 明确返回 None；此时仍读到7个模型，完成小说 MCP 查询、文本输入、联网、3个会话的新建/分支/恢复和压缩。所有素材均为新建测试小说。

原生窗口使用系统及用户注册的普通 PATH 启动，确认没有 PATH 可用的 Codex 命令，设置页仍成功显示 ChatGPT 已登录和模型目录。作者正在编辑的旧窗口未关闭，小说未重新打开或修改；旧进程需要保存后重启才能载入此次代码修复。
