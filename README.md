# AI Novel Studio

> 当前开发版本：`0.7.0`（V3 Phase 7）。本地优先的长篇记忆、动态上下文、冻结 Brief 交接、流式正文草稿、检查点恢复、审校落库、有界修复、严格模式采用边界，以及只读工具检索与证据追踪已经落地。

AI Novel Studio 是一个从零实现的、本地优先的 AI 长篇小说创作工作台。项目目标是支持百万字体量的“人工主导 + AI 辅助”创作，而不是把全文一次性塞给模型。

## Phase 5 已具备

- 受保护的“当前章要求”：用户可直接编辑和锁定，剧情商讨模型只能生成候选要求，不能覆盖锁定内容。
- 可审查 Chapter Brief：草稿、冻结、过期和归档状态；标准模式只接受当前冻结 Brief。
- 动态正文上下文：按当前章要求、冻结 Brief、近章全文、历史摘要、记忆和检索证据组装，并记录 Context Manifest。
- 自定义输出 Token 上限：保留用户设置，不再静默压到 3000 以下；超过模型能力时明确报错。
- 流式正文草稿：模型输出先进入检查点和草稿区，正式正文只有用户明确采用后才写入。
- 中断恢复：重启后可扫描 `PREPARING / READY / STREAMING / PARTIAL` 运行和检查点，不自动发起第二次付费模型调用。
- 安全采用/放弃：采用前校验章节 revision 和检查点哈希；放弃不会删除检查点历史。
- Phase 5 UI 接口：正文面板区分正式正文和 AI 草稿，提供生成、取消、采用、放弃和恢复入口。

架构说明见 [ADR 0006: Prose generation pipeline](docs/architecture/0006-prose-generation-pipeline.md)。
只读工具检索说明见 [ADR 0007: Read-only tool retrieval and evidence trace](docs/architecture/0007-agent-tool-loop.md)。

## 已完成阶段概览

### Phase 1：本地项目数据内核

- 以稳定 UUID 管理项目、卷、章和历史版本。
- Markdown/UTF-8 正文 + SQLite 结构化元数据。
- 原子正文保存、改稿历史、章节回收站和删卷迁移。
- 项目完整性检查、单写入实例锁和 ZIP 备份。
- 旧版 `meta.json + DOCX` 项目的只读预览、迁移和校验报告。

### Phase 2：三栏桌面工作台

- 可拖动的章节/人物、正文和剧情商讨三栏工作台。
- 左栏滚动、区块折叠、人物选择/编辑/删除。
- 可编辑正文、字号和自定义输出 Token 上限。
- 独立、可编辑和可锁定的“当前章要求”。
- 章节 Brief、记忆库、风格规则、审校页面和聊天气泡界面。

### Phase 3：统一模型网关

- 多个 OpenAI-compatible API / 第三方中转连接。
- Windows 凭据管理器保存 API Key，配置文件不保存明文密钥。
- 剧情商讨、正文创作、Brief 整理和审校可走不同模型路由。
- 模型列表获取、显式能力探测、流式聊天、结构化输出校验和用量统计。

### Phase 4：长篇记忆与动态上下文

- L0-L4 分层摘要、人物状态时间线、人物/读者知识边界。
- 正典、伏笔、叙事线索和分层风格规则。
- SQLite FTS5 历史检索、相关人物和人工固定权重。
- 动态输入预算、整块摘要回退和可审查 Context Manifest。
- 模型记忆提取候选的嵌套结构校验和人工晋升边界。

### Phase 5：正式正文生成流水线

- Chapter Brief 生命周期和冻结交接。
- 写前上下文准备、Manifest 记录和稳定提示顺序。
- 流式正文生成、reasoning 分离、Token 用量记录和检查点。
- 草稿采用、放弃与重启恢复。
- UI 服务接入和百章压力测试。
### Phase 7：只读工具检索与证据追踪

- 剧情商讨可选“工具检索”，由模型用 JSON 明确请求只读工具。
- 工具可检索章节摘录、记忆文档、人物状态/知识、活跃伏笔、正典事实、风格规则和审校发现。
- 每次运行、消息和工具调用写入 schema v5 trace 表，便于审查模型到底看了什么。
- 迭代次数、工具调用次数、工具结果字符数和模型输出 Token 都有预算上限。
- 工具检索只输出建议或可审查计划，不直接修改正文、记忆库、设置或导出。
- 这不是未来完整 Agents 大版本；多 Agent 协作、原生 function calling、自动规划和长任务队列仍属于后续大版本范围。

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\mypy src
```

## Project data

V3 项目把卷章结构、修订信息和状态保存在 `project.sqlite3`，把唯一正式正文保存在 `manuscript/volume_<UUID>/chapter_<UUID>.md`。数据库中的标题、章号和顺序可以修改，但跨模块关联始终使用 UUID。

详细格式和恢复规则见：

- [Project data format](docs/architecture/0002-project-data-format.md)
- [Phase 2 UI boundaries](docs/architecture/0003-phase-2-ui-boundaries.md)
- [Unified model gateway](docs/architecture/0004-unified-model-gateway.md)
- [Memory and context kernel](docs/architecture/0005-memory-and-context-kernel.md)
- [Prose generation pipeline](docs/architecture/0006-prose-generation-pipeline.md)
- [Read-only tool retrieval and evidence trace](docs/architecture/0007-agent-tool-loop.md)

## Privacy

公开提交和发布产物不得包含真实姓名、本机用户名、用户目录、API Key 或用户稿件。

## Windows build

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

输出文件为 `dist/AI-Novel-Studio/AI-Novel-Studio.exe`。

## Release privacy gate

创建本地忽略的 `.privacy-blocklist`，每行一个私密词，然后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

隐私扫描通过前不要发布构建产物。
