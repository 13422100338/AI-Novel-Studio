# AI Novel Studio

AI Novel Studio 是一个从零实现的、本地优先的 AI 长篇小说创作工作台。

当前状态：V3 Phase 3 统一模型网关。项目尚未发布正式版本。

Phase 1 已具备：

- 以稳定 UUID 管理项目、卷、章和历史版本。
- Markdown/UTF-8 正文与 SQLite 结构化元数据。
- 原子正文保存、改稿历史、章节回收站和删卷迁移。
- 项目完整性检查、单写入实例锁和 ZIP 备份保留。
- 旧版 `meta.json + DOCX` 项目的只读预览、迁移和核验报告。

Phase 2 已具备：

- 可拖动的章节/人物、正文和剧情商讨三栏工作台。
- 左栏滚动、区块折叠、人物选择/编辑/删除的本地交互。
- 可编辑正文、字号与自定义输出 Token 上限。
- 独立、可编辑和可锁定的“当前章要求”。
- 可审查、冻结和克隆的章节 Brief 模拟流程。
- ChatGPT/Codex 风格聊天气泡与独立剧情商讨窗口。
- 记忆库、人物/读者知识、叙事线索、文风规则和审校页面。
- 统一黑白灰主题、可拖动滚动条、圆角按钮和辅助功能名称。

Phase 3 已具备：

- 多个 OpenAI-compatible API/第三方中转连接及自定义模型列表地址。
- Windows 凭据管理器保存 API Key；普通配置、日志和项目文件不保存明文密钥。
- 剧情商讨与正文创作双模型，以及 Brief 整理、文风审校的高级覆盖路由。
- 模型列表获取与显式能力探测，不根据模型名称猜测流式、JSON、推理或工具能力。
- 流式剧情聊天、正式当前章要求草稿、Brief 整理和独立模型审校。
- JSON 合同校验、最多一次格式纠错、部分流式结果保留和禁止静默切换付费模型。
- 实际/估算 Token、缓存、重试和费用统计；用户设置的 `200000` 输出上限原样传递。

三栏项目内容仍使用不可持久化的演示数据。记忆库数据库接线将在 Phase 4 完成；正式正文
生成、冻结 Brief 交接和流式检查点属于 Phase 5，当前不会被模型网关提前启用。

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\mypy src
```

## Project data

V3 项目把卷章结构、修订信息和状态保存在 `project.sqlite3`，把唯一正式正文保存在
`manuscript/volume_<UUID>/chapter_<UUID>.md`。数据库中的标题、章号和顺序可以修改，
但跨模块关联始终使用 UUID。

详细格式和恢复规则见 [Project data format](docs/architecture/0002-project-data-format.md)。
界面模块边界和模拟功能说明见 [Phase 2 UI boundaries](docs/architecture/0003-phase-2-ui-boundaries.md)。
模型连接、任务路由、凭据、合同和流式规则见
[Unified model gateway](docs/architecture/0004-unified-model-gateway.md)。

## Privacy

公开提交和发布产物不得包含真实姓名、本机用户名、用户目录、API Key 或用户稿件。

## Windows build

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The output is `dist/AI-Novel-Studio/AI-Novel-Studio.exe`.

## Release privacy gate

Create the ignored `.privacy-blocklist` locally, one private term per line, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

Do not publish an artifact unless this command succeeds.
