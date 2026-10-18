# AI Novel Studio

**简体中文** · [English](README_EN.md)

本地优先的小说创作桌面工作台。在软件内与 **Codex** 讨论剧情、检索小说资料，并调用**独立正文模型**生成写作候选。

目前为开发预览版，主要面向 Windows。

## 当前功能

- **小说工作区**：项目与卷章管理、Markdown／文本稿件导入、正文编辑、自动保存与修订记录。
- **Codex 助手**：使用 ChatGPT 登录，支持模型与思考强度选择、会话历史、分支、压缩、图片／文本附件和可选联网查询。
- **小说资料检索**：通过小说 MCP 读取章节、章要求、人物和原文证据，支持批量阅读与汇总状态。
- **独立正文写作**：Codex 整理任务，另行配置的写作模型生成候选；聊天侧栏显示进度与结果，正式稿由作者审阅处理。
- **选文与记忆**：引用正文选区，使用 `/润色`、`/重写` 等写作指令，查看人物、世界设定与剧情记忆；聊天支持 Markdown 显示。

## 安装与启动

需要 **Python 3.11+、Node.js／npm**，以及已使用 ChatGPT 登录的 Codex CLI 或 Codex 桌面版。

1. 克隆仓库或下载 ZIP 并解压，双击 `setup.bat` 安装 Python 依赖。
2. 在项目目录打开 PowerShell，首次使用时构建正文编辑器：

   ```powershell
   Push-Location src/ai_novel_studio/ui_qml/editor_web
   npm ci
   npm run build
   Pop-Location
   ```

3. 双击 `启动程序.bat`（或 `launch.bat`），新建或打开小说项目。
4. 在设置中配置独立正文模型的 API 连接与模型；Codex 助手使用其自身的 ChatGPT 登录。

## 下一步

正在设计事件大纲驱动的雪花式创作流：导入大纲、关联事件与章节，再定向组织写作资料。
这些能力尚未实现，详见[设计方案](docs/SNOWFLAKE_EVENT_WORKFLOW_2026-10-18.md)。

欢迎通过 Issues 反馈问题。许可证：[MIT](LICENSE)。
