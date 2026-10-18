# 正文选文与紧凑聊天侧栏

本票修复正文焦点黄框、选文在聊天中丢失、快捷按钮占用空间和模型设置不易收起，并接入小说编辑原生技能。没有修改作者小说、章要求、数据库结构或模型凭据。

## 使用方式

- 在正文里选中文字，聊天输入区上方显示章节、字数和两行引用预览。点击引用上的 × 清除引用。
- 选文随本轮消息固定，聊天记录保留引用预览。本轮进行中继续编辑正文，不会改变这一轮读取的上下文；新上下文在下一轮生效。
- 附件旁的“/ 写作”打开重写、润色、精简、扩写、生成草稿和续写菜单。输入 `/` 或 `/skills` 也可打开菜单；上下键选择，Enter 补全，再输入要求并发送。
- 支持 `/润色` 等中文指令及 `/polish`、`/rewrite`、`/shorten`、`/expand`、`/draft`、`/continue`。例如 `/润色 让对话更自然，保留人物语气`。
- `/model` 展开或收起模型与会话，`/new` 新建会话，`/compact` 压缩会话。右上角展开后按钮明确显示“收起设置”。
- 没有选文且只发送 `/润色`、`/重写`、`/精简`、`/扩写` 时，先提示选择正文。整章操作可明确补充“整章”，不会把缺少选文默认为整章。

生成继续交由独立正文写作模型完成，结果显示为候选任务卡，不自动替换正式稿。

## 实现边界与文件

- `ui_qml/editor_web/src/style.css`：仅清除正文内部 ProseMirror 可编辑区域的焦点轮廓，保留其他控件的键盘焦点样式。
- `ui_qml/editor_web/src/editor.ts`：新增只读选文上下文，保留导入源文本；编辑时同步实时缓冲区，保存修订后重新发送选文。原有精确替换捕获继续严格校验，聊天引用不授予替换权限。
- `ui_qml/bridge/models/chat_selection.py`、`editor_bridge.py`、`mock_novel_studio_facade.py`、`bootstrap.py`：验证只读引用的字段、章节、修订、体积及字符编码，更新缓冲区而不保存；修改正文时清除旧引用，保存后更新仍有效的引用修订。
- `ui_qml/bridge/codex_session_bridge.py`：本轮小说 MCP 快照固定，消息展示与发送内容分离，聊天中不展示内部技能提示词。
- `ui_qml/qml/components/AgentComposer.qml`、`CreativeAgentPanel.qml`、`ContextReferenceChip.qml`：菜单、键盘补全、设置收起和选文预览。引用按纯文本显示，避免将小说中的 HTML 字样解释为富文本。
- `application/novel_writing_commands.py`：写作指令与任务转换。
- `application/codex_session_service.py`、`infrastructure/codex/app_server.py`、`infrastructure/codex/writing_skill.py`、`infrastructure/codex/skills/novel-edit/SKILL.md`、`pyproject.toml`：打包并以原生 `skill` 输入调用小说编辑技能，其他编码技能仍在小说会话中禁用。
- 对应测试：`tests/ui_qml/test_chat_selection.py`、`test_writer_chat_ui.py`、`test_qml_shell.py`、`tests/unit/application/test_novel_writing_commands.py`、`test_codex_session_service.py`、`editor_web/tests/editor-core.test.ts`。
- 验收工具：`scripts/validate_editor_selection.py`、`scripts/validate_chat_writer.py --headless --live --selected-polish`。只使用新建的临时测试小说。

上面源码路径相对于 `src/ai_novel_studio/`，测试、脚本和打包配置路径相对于仓库根目录。

## Codex 兼容性

[官方 App Server 文档](https://developers.openai.com/codex/app-server#skills) 支持通过用户文本中的 `$novel-edit` 和结构化 `{type: "skill", name, path}` 显式调用技能。斜杠菜单由小说软件提供，不是把 CLI 的整套界面嵌入聊天框。

本机 CLI `0.163.0-alpha.10.2` 的本地协议只有 `skills/list.cwds` 和 `forceReload`，尚不支持最新文档的额外技能根目录参数。实际验证发现，仅传外部技能文件路径不会加载其正文。因此程序把包内技能放入软件自己的隔离 Codex 工作目录 `.agents/skills/studio-novel-edit-v1/SKILL.md`，让 Codex 正常发现，再通过原生输入选用。不会写入小说目录或修改全局技能设置。

技能副本使用独占创建，已存在且内容不同则停止并提示，不覆盖。后续修改这个包内技能时应递增副本目录版本。当前 `/skills` 展示本软件的小说编辑技能入口，不是本机全部技能的管理器。

只读引用最多 20,000 字；现有小说 MCP 单次选文上限仍为 8,000 字并带截断标记。技能遇到截断应先请作者缩小范围，不能以截断片段冒充完整选文。

## 验收证据

- 离屏真实 Chromium + WebChannel：正文聚焦时 `outline=none`，跨失焦仍有选文引用，缓冲区不变；保留了截图并核查。
- 1100、1440 宽度下验证：设置按钮可通过鼠标展开和收起，折叠状态聊天区超过侧栏高度的 60%；菜单不常驻挤占聊天空间。
- 临时小说真实调用：技能目录包含 `novel-edit`，发送了结构化原生技能输入，会话记录确认完整技能正文已被注入；生成请求包含完整选文及范围限制，独立写作模型返回 66 字候选，正式稿与锁定章要求均未改变。
- 对应临时结果目录：`%LOCALAPPDATA%/Temp/novel-native-skill-3dfb8c57`；`result.json` 记录生成与范围检查，`native-skill-proof.json` 记录正文注入检查。
- 编辑器完整单元测试 144 项通过，TypeScript 检查与构建成功；后台启动冒烟检查通过。Python 153 项回归覆盖选文、侧栏、项目保存、会话、原生技能与传输边界，包含真实鼠标点击与键盘输入验证。

该技能的通用校验脚本依赖未安装的 PyYAML；本票使用实际 Codex 技能目录解析、完整正文注入和真实写作调用验证，未为此安装依赖。
