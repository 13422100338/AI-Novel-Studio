# 缺陷报告：save_content 回滚路径静默改写 CRLF 手稿行尾

> 日期：2026-08-21
> 发现者：OpenCode worker（ox-alpha），O2 revision invalidation 审计期间
> 发现分支：`opencode/backend-o2-invalidation` @ `6fab4b3`（基线 `origin/main@36d3c63`）
> 状态：已记录，未修复；等待主控开票授权
> 本报告未修改任何生产代码

## 1. 缺陷摘要

`ChapterRepository.save_content(...)` 在数据库事务失败回滚时，会把章节正文文件
**从 CRLF 静默改写为 LF**，而 `chapters.content_hash` 列仍保留原始 CRLF 内容的
SHA-256。结果：磁盘正文与权威 hash 永久不一致，后续所有依赖精确 hash 校验的
路径（Formal Manuscript 维护、Occurrence 绑定、Evidence 回源）都会 fail-closed，
且用户手稿内容在未经授权的情况下被改变（违反 AGENTS.md 规则 11 的精神）。

## 2. 精确代码证据

`src/ai_novel_studio/infrastructure/storage/chapter_repository.py`：

```python
# :392（save_content 内，事务开始前读取旧内容用于快照与回滚）
previous = canonical.read_text(encoding="utf-8")
```

`Path.read_text()` 未传 `newline` 参数，默认 universal newlines 模式：
内存中的 `previous` 已把 `\r\n` 翻译成 `\n`。

```python
# :455-458（save_content 异常回滚路径）
except BaseException:
    atomic_write_text(canonical, previous)
    snapshot.unlink(missing_ok=True)
    raise
```

```python
# src/ai_novel_studio/infrastructure/storage/atomic_file.py:12
with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
```

`atomic_write_text` 以 `newline=""` 写入，不做二次翻译——它如实写下了
已经被 `read_text` 翻译成 LF 的字符串。净效果：CRLF 文件 → LF 文件。

同一事务中 `UPDATE chapters SET content_hash = ?` 已随事务回滚
（`:415-429` 的 UPDATE 与 INSERT chapter_versions 同属一个 `with connection`
块），因此 `content_hash` 列保持原始 CRLF hash，与恢复后的 LF 文件不匹配。

## 3. 触发条件

同时满足：

1. 章节正文文件包含 CRLF 行尾（Windows 编辑器或导入产生的手稿是常态）；
2. `save_content` 在进入数据库事务阶段后抛出任意异常——包括但不限于：
   - `cursor.rowcount != 1` 的并发修改保护（`:434`）；
   - 项目数据库上存在触发器/约束拒绝写入；
   - `sqlite3.Error`、磁盘 I/O 错误；
3. 异常走 `except BaseException` 回滚分支。

正常保存成功路径不受影响（成功时会用新内容的正确 hash 覆盖）。

## 4. 影响与风险

| 影响 | 说明 |
| --- | --- |
| 用户手稿被未授权修改 | 行尾全部改变；对 diff/版本工具可见，违反"不修改用户正文"约束 |
| hash 与正文永久失配 | `_current_formal_source`（search_repository）与 Occurrence 绑定校验会报 "formal manuscript source file does not match current chapter" / "occurrence candidate source is unavailable"，该章节的派生数据从此无法维护 |
| 可恢复性差 | 无自愈路径；需要人工或专门工具重算 hash 或还原文件 |
| 静默性 | 回滚"成功"，调用方只看到原始异常，不知道文件已被改写 |

## 5. 复现证据

O2 RED 阶段测试 `test_failed_save_rolls_back_flags_and_content`
（`tests/integration/storage/test_occurrence_invalidation.py`）以 CRLF 内容
驱动 save_content 并用触发器注入失败，断言 `read_content_exact(...) == CONTENT`
失败，pytest diff 显示实际值为 LF 版本：

```text
assert '序章\n\n艾琳发现钥匙🔑。\n守卫随后封锁现场。' == '序章\r\n\r\n艾琳发现钥匙🔑。\r\n守卫随后封锁现场。'
```

同测试中 DB 侧断言（revision==0、content_hash==原 CRLF hash、失效标志未置位）
全部通过，证明数据库完整回滚而文件已被改写——正是本缺陷的特征。
该测试现已改用 LF 内容以绕开本缺陷、聚焦 O2 语义；CRLF 场景应作为修复票的
RED 测试重新引入。

## 6. 不受影响的路径（已核实）

以下路径读取旧内容时使用 `open(..., newline="")`（`_read_content_path_exact`，
`chapter_repository.py:251-259`），字节级保真，无此缺陷：

- `rename_chapter`（经 `read_content_exact`，`:268`）；
- `delete_volume` 迁移（经 `_read_content_path_exact`，`:637`）；
- `delete_chapter`（移动文件，不改写内容）；
- `restore_chapter`（移动文件）。

仅 `save_content` 使用了带 universal newlines 的 `canonical.read_text()`。
另：`read_content()`（`:237`）同样使用默认翻译模式，但它只服务于展示层读取，
不参与回滚写回，不属于本缺陷（如主控认为展示层也应字节级保真可另行评估）。

## 7. 建议修复方向（供主控冻结票范围）

最小修复（推荐）：`save_content` 中 `:392` 改为复用现有的
`self._read_content_path_exact(chapter.content_path)`（`newline=""` 保真读取），
替换 `canonical.read_text(encoding="utf-8")`。一行改动，语义与
rename/delete_volume 对齐。

配套验收：

1. RED 测试：CRLF 手稿 + 注入事务失败 → 断言 `read_content_exact` 字节级等于
   原文、`content_hash` 列不变、再次 `maintain_current_revision` 成功；
2. 全量回归：`tests/unit/application/test_project_workspace_service.py`、
   `tests/integration/storage/`；
3. Ruff + MyPy + `git diff --check`。

需主控单独决策（不在最小修复内）：

- 是否扫描既有项目检测"文件 LF 但 hash 为 CRLF"的受损章节并提供修复
  （涉及用户数据，必须显式授权）；
- `read_content()` 展示路径是否统一为保真读取。

## 8. 边界声明

- 本缺陷预先存在于 `origin/main@36d3c63` 及更早历史，非 O2/P2b/OC-BE1 引入；
- O2 分支（`6fab4b3`）未修改 `save_content`、`atomic_file.py` 或任何相关代码；
- 本报告仅为记录与交接，修复需主控授权后另开独立票、独立 worktree 实施。
