# FO-4b：侧栏候选采用、放弃与恢复

状态：已实现；日期：2026-10-20。承接 [FO-4a 完整输入与确认](FO4A_WRITER_INPUT_CONFIRMATION_2026-10-20.md)，仅接通完整大纲流程的候选操作，不设为全局默认、不删除旧记忆代码或数据库表。

## 使用方式

- 作者确认输入、生成候选后，可查看本次输入、展开／复制草稿、采用或放弃。
- 整章候选显示“采用到本章”；选文候选显示“替换原选文”；中断后的部分候选显示“采用部分候选”，必须由作者明确点击。
- 侧栏“恢复候选”恢复最近 20 个尚未采用／放弃的新流程任务，并显示恢复数／总数。同一候选重复恢复只更新一张卡片；会话切换或项目重开后仍可恢复。
- 恢复只加载原检查点、作者已确认的输入与来源，不重新读取当前大纲组装旧任务，不自动续写或调用模型。已采用／放弃任务的输入和检查点继续保留。
- 待确认但尚未生成的提案仍只在内存中存在；重启后需要重新整理并确认，不能伪造作者确认。

## 原文保护

新输入快照增加 `adoption_source`：生成时的编辑原文、章节身份、修订及精确选区捕获。旧快照缺少该字段时仍可查看、复制，不能自动推测替换位置。

选区捕获沿用 `selection-patch-v1`，包含全文哈希、字符范围、选文及两侧锚点。采用按原字符范围拼接，不按字符串搜索，不把选文候选当整章覆盖。重复句的第二处选区、跨段落、CRLF 和 Unicode 均保留未选部分原文。

Web 编辑器继续使用现有精确捕获；仅有聊天引用且无法还原 Markdown 区间时，卡片说明只能复制。TextArea 回退编辑器把 UTF-16 范围严格转换为 Python 字符范围，拒绝半个代理对及无效区间。聊天引用不会覆盖已有有效的精确捕获。

采用前核对当前编辑章节、修订及全文，检查正式正文的原修订／哈希，以及作者看到的检查点 ID／哈希。生成后有任何正文编辑、外部修订或候选变化，都拒绝过期采用。不会先自动保存再覆盖。

大纲或其他参考资料在生成后更新，不修改候选或其原输入；作者仍可检查旧输入，决定是否采用旧候选或重新发起任务。

## 提交与恢复边界

- 生成、采用、放弃及恢复共用项目操作锁；Codex 断线重连、关闭后重开同一项目时保留该锁，旧生成线程退出前不能恢复或采用其候选。
- 采用在 `BEGIN IMMEDIATE` 中重新核对正式原文与最新检查点，通过现有 `ChapterRevisionService.commit_revision()`、同一 SQLite 连接及 `ChapterFileTransaction` 一起提交正文修订和 `ACCEPTED` 状态。同进程异常回滚数据库和正文文件。
- 正式正文已提交后，全文检索维护失败或返回待修复状态时仍报告采用成功，并提示索引待修复，不能把已提交结果说成未采用。
- `ChapterFileTransaction` 仍沿用既有的同进程异常回滚边界，本票未建立 SQLite 与多个文件在断电／进程强杀时的跨存储事务。
- 放弃仅变更运行状态，不删除输入或检查点。采用／放弃入口仅由 UI 暴露，不增加 Codex MCP 自动采用工具。
- 遗留 `STREAMING` 有完整校验的检查点时恢复为 `PARTIAL`；其他未结束且无可用结果的任务转为 `FAILED`，不自动重新生成。
- 快照或检查点缺失／损坏时保留卡片和原文件、禁止采用；其他可读候选仍能恢复。直接采用最多显示完整的 200,000 字候选；选文替换沿用 20,000 字限制，超限明确禁止，不能截断后采用。
- 检查点按原 UTF-8 字节解码校验，避免 Windows 通用换行转换导致正常 CRLF 被误判损坏。

## 改动文件

路径相对于 `src/ai_novel_studio/`：

- 新增 `application/writer_candidate_service.py`：候选验证、采用事务、放弃与原快照恢复。
- `application/outline_writer_input.py`、`outline_writer_service.py`、`novel_read_service.py`、`novel_writer_service.py`：冻结采用来源、共享操作锁与服务接线。
- `application/selection_patch.py`：从明确字符区间创建现有格式的精确捕获。
- `infrastructure/storage/generation_repository.py`、`checkpoint_repository.py`：调用方事务接线及字节精确的检查点校验。
- `ui_qml/bridge/codex_session_bridge.py`、`mock_novel_studio_facade.py`：候选操作、恢复进度、原输入预览、编辑器修订同步及选区传递。
- `ui_qml/qml/components/WriterTaskCard.qml`、`CreativeAgentPanel.qml`、`pages/WritingPage.qml`：采用／放弃按钮、恢复入口与回退选区。

新增 `tests/integration/application/test_writer_candidates.py`、`tests/ui_qml/test_writer_candidate_actions.py`，并扩展 `test_chat_selection.py`。简短中英文 README 与总路线同步状态。本票无数据库迁移。

## 验证

- 新增 26 项测试覆盖整章／第二处重复选文采用、编辑／正式稿／检查点过期拒绝、事务失败回滚、放弃保留文件、旧快照兼容、坏资产、CRLF、UTF-16、部分结果明确采用、共享锁与索引待维护。
- 实际 QML 按钮验证采用、放弃、会话历史清空后恢复、恢复去重、原输入查看及编辑器修订同步。新按钮缺失的 5 项测试先失败，再全部通过；索引返回待维护的用例同样先失败后修复。
- 存储、应用、旧生成、QML、MCP／Codex 接口及大纲解析相关回归累计去重 **724 项通过**，无跳过；Ruff 与 10 份相关 Python 源码的 MyPy 通过。
- 临时虚构项目完成“选文 → 确认 → 假模型生成 → 恢复 → 采用”串联；恢复不增加模型调用，原始输入逐条不变，正式稿仅原选区改变。完成／恢复／采用三态离屏截图通过检查，相关 QML 警告为 0。
- 离屏截图进程初次未找到系统字体，显式加载已存在的微软雅黑／宋体／Segoe UI 后重拍；未修改软件主题或系统字体。MCP 依赖仍有既存的 Pydantic `lifespan` 前向引用警告。
- 独立只读后端风险复核通过。所有验证只用临时项目，未打开或修改作者小说、数据库、备份、导出或密钥。

可在本工作树设置 `PYTHONPATH=src`、`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`，复跑：

```powershell
python -m pytest tests/integration/application/test_writer_candidates.py tests/ui_qml/test_writer_candidate_actions.py tests/ui_qml/test_chat_selection.py -q -p no:cacheprovider --basetemp (Join-Path $env:TEMP ('ans-fo4b-' + [guid]::NewGuid().ToString('N')))
```

下一票：FO-5，把验证过的完整大纲流程设为默认，收拢旧记忆自动调度入口；保留旧资料只读、正文索引和修订／搜索，不删除旧数据库表。
