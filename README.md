# AI Novel Studio

**简体中文** · [English](README_EN.md)

以完整大纲驱动的本地小说创作工作台。在软件内与 **Codex** 讨论剧情、查阅正文，并调用**独立正文模型**生成写作候选。

目前为开发预览版，主要面向 Windows。

## 当前功能

- **小说工作区**：项目与卷章管理、Markdown／文本稿件导入、正文编辑、自动保存与修订记录。
- **大纲工作区**：Markdown 编辑、导入导出、目录与版本回退；可关联正式章节，改纲后保留链接并重新确认。
- **Codex 助手**：每轮接收当前完整大纲；支持 ChatGPT 登录、模型与思考强度、会话分支与压缩、附件和可选联网查询。
- **小说资料检索**：通过小说 MCP 读取章节、作者约束与原文证据，支持批量阅读与汇总状态。
- **独立正文写作**：完整大纲、相关正文、范章与近期章节经作者确认后生成候选；支持选文／整章采用、放弃与原输入恢复。
- **选文与旧资料**：支持 `/润色`、`/重写` 等选文指令与 Markdown 聊天；旧人物、记忆及审查记录集中只读查看。

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

## 创作方式

正文创作默认使用完整大纲并由作者确认输入；旧项目可先编辑与讨论，生成前在大纲页导入或新建大纲。
新写作流程进度详见[设计方案](docs/FULL_OUTLINE_WORKFLOW_2026-10-18.md)。

欢迎通过 Issues 反馈问题。许可证：[MIT](LICENSE)。
