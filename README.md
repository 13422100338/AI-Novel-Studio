# AI Novel Studio

AI Novel Studio 是一个从零实现的、本地优先的 AI 长篇小说创作工作台。

当前状态：V3 Phase 1 数据内核。项目尚未发布正式版本。

Phase 1 已具备：

- 以稳定 UUID 管理项目、卷、章和历史版本。
- Markdown/UTF-8 正文与 SQLite 结构化元数据。
- 原子正文保存、改稿历史、章节回收站和删卷迁移。
- 项目完整性检查、单写入实例锁和 ZIP 备份保留。
- 旧版 `meta.json + DOCX` 项目的只读预览、迁移和核验报告。

当前窗口仍是工程外壳；三栏创作界面属于 Phase 2。

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
