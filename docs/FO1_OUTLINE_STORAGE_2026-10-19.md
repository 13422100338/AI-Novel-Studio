# FO-1：大纲文档与版本存储

日期：2026-10-19。状态：后端实现及临时项目验证完成，尚未接入 UI 或模型输入。
分支：`codex/full-outline-architecture`；基线：`3d196bd`；本票未提交或推送。
需求依据：[完整大纲驱动方案](FULL_OUTLINE_WORKFLOW_2026-10-18.md)。

## 本票行为

- 创建、列出和读取大纲文档；文档按导入顺序排列。
- 导入／重新导入 UTF-8 的 `.md`、`.markdown`、`.txt`，源文件不变。
- 原样保留 BOM、CRLF、空白、标题、注释与链接；不解析重排、不摘要、不截断。
- 每次内容变更产生新版本；无改动保存不增修订、不触碰工作文件。
- 旧修订不能覆盖新修订；磁盘内容与登记版本不一致时，普通读取与保存明确失败。
- 历史回退作为新修订保存，保留原来的新旧版本。
- 数据库写入失败时保留磁盘内容和恢复资产，不自动回滚覆盖作者编辑。
- 大纲保存不调用章节、记忆、检索或模型服务。

## 文件与数据库

v26 仅新增 `outline_documents`、`outline_versions` 两表及排序索引。
迁移不清空、修改或删除旧表。本轮仅在临时库执行了迁移，未打开作者项目。
只支持 v25 的旧程序不能打开已经升级至 v26 的项目，不能通过修改版本号强行降级。

```text
outlines/<document_id>.md
.ai_pipeline/outline_versions/<document_id>/<version_id>.md
.ai_pipeline/outline_versions/<document_id>/disk_<uuid>.md
```

第一项为可编辑的工作副本；第二项是已登记版本的独立快照。
第三项是替换时保留的实际磁盘副本，不等于已登记版本，不直接用于模型输入。
未提交的新快照、创建失败的文件和磁盘恢复副本均保留，本票不自动回收或枚举孤立资产。

保存会把实际磁盘文件移至恢复位置，校验内容后独占发布新文件；目标被外部重建时不会替换它。
失败时也只尝试独占恢复，不覆盖另一个编辑器的新文件。
发布通过独立 staging 文件及硬链接完成，历史快照与工作文件不会长期共享 inode。
项目文件系统必须支持同卷硬链接；不支持时明确失败并保留资产，不退回可能覆盖文件的写法。
外部程序若持有旧文件句柄，仍可能继续改变 `disk_*` 恢复资产，因此不能把它当成不可变版本。

## 接口

`OutlineRepository`：

- `create(title, content)`、`list_documents()`、`get(document_id)`。
- `read(document_id)`：校验当前登记版本、快照及工作副本，返回完整原文。
- `save(document_id, content, expected_revision=...)`。
- `list_versions(document_id)`、`read_version(document_id, revision)`。
- `inspect_working_copy(document_id)`：仅供作者检查未登记磁盘内容。
- `recover_from_disk(..., expected_revision=..., expected_disk_hash=...)`：显式接纳作者检查过的磁盘原文，修订或磁盘 hash 变化时拒绝。
- `restore_missing_working_copy(..., expected_revision=...)`：仅在工作文件缺失时，从当前已校验快照独占恢复，不增修订。

`OutlineService`：`import_file`、`reimport_file`、`restore_version`。
最后一项在正常版本校验后新增修订，不覆盖历史。
`recover_from_disk` 要求当前已登记快照仍完好；损坏时失败关闭，不凭空修复历史。
存储单文件上限为 20 MB UTF-8，超限明确报错；该上限不是模型上下文容量。

## 修改范围

源码：

- `src/ai_novel_studio/domain/outline.py`
- `src/ai_novel_studio/application/outline_service.py`
- `src/ai_novel_studio/infrastructure/storage/outline_repository.py`
- `src/ai_novel_studio/infrastructure/storage/schema_migrations_v26.py`
- `src/ai_novel_studio/infrastructure/storage/schema_migrations.py`

新增测试：`tests/integration/storage/test_outline_schema.py`、`test_outline_repository.py`，
以及 `tests/integration/application/test_outline_service.py`。
另同步 11 份旧存储测试的最新／未来版本断言，保留其原有数据和行为检查：
`test_project_repository.py`、`test_character_identity_schema.py`、`test_subject_registry.py`、
`test_memory_schema.py`、`test_occurrence_schema.py`、`test_generation_schema.py`、
`test_embedding_schema.py`、`test_audit_schema.py`、`test_agent_schema.py`、
`test_harness_schema.py`、`test_project_constitution_schema.py`。

## 验证

- 新增测试 25 项通过，包含超过 20,000 字符的大纲、原文保真、无改动保存、旧修订冲突、文件重定向、磁盘／数据库故障、显式恢复与创建失败。
- 两类外部编辑竞态先复现失败，修复后通过：替换边界修改、发布期间重建目标。
- 存储层全部测试、FO-1 服务测试及现有草稿采用／恢复测试合计 **360 项通过**，无跳过。
- Ruff 通过；本票 5 份源码 MyPy 通过；独立只读风险复核通过。
- 未调用真实模型、启动图形界面或修改作者小说、数据库、备份与密钥。

复核命令（在本工作树、已安装测试依赖的 Python 环境中执行）：

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest tests/integration/storage tests/integration/application/test_outline_service.py tests/integration/generation/test_generation_acceptance_and_recovery.py -q -p no:cacheprovider --basetemp (Join-Path $env:TEMP ('ans-fo1-' + [guid]::NewGuid().ToString('N')))
```

下一票：FO-2，接入可编辑 Markdown 大纲工作区及轻量章节链接确认；完整大纲注入仍属 FO-3／FO-4。
