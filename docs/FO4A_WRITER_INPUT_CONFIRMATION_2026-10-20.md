# FO-4a：正文完整输入与作者确认

日期：2026-10-20。状态：实现与验证完成，未提交、合并或推送。
分支：`codex/full-outline-architecture`；沿用 FO-1 至 FO-3 的独立工作树，基线 `3d196bd`。
依据：[完整大纲方案](FULL_OUTLINE_WORKFLOW_2026-10-18.md)、[FO-3 Codex 输入](FO3_CODEX_COMPLETE_OUTLINE_2026-10-19.md)。

FO-4 拆为两个可验收小票。本票完成“完整输入准备 → 作者审阅确认 → 独立模型候选”，FO-4b 接通侧栏采用、放弃与恢复，保留现有正式正文保护。

## 使用流程

1. 登记完整 Markdown 大纲，在聊天中说明目标事件、写作要求、相关章及作者选定的范章。
2. Codex 按需读取正式正文，将相关章／片段通过 `related_refs`、范章通过 `style_refs` 明确交给正文工具；读取过不会自动等于传给正文模型。
3. 有大纲时，`generate_novel_draft` 先返回 `AWAITING_CONFIRMATION` 输入提案，不调用正文模型。侧栏显示“待确认正文输入”。
4. 点击“查看并确认输入”，逐条查看实际将发送的消息。默认显示完整大纲，可以切换至作者要求、相关正文、范章、近期章节等原文。
5. 点击“确认输入并生成”后才启动独立正文模型；需要修改时返回聊天重新整理，也可取消提案。确认权限没有暴露成 MCP 工具，Codex 无法替作者确认。
6. 生成中显示进度，完成后可查看、复制候选和本次冻结输入；正式正文不会自动改变。取消仍保留已经收到的检查点。

近期正文默认取目标之前三章，可以在任务中指定 `recent_chapters=0..10`。首版通过聊天明确指定范章及片段，没有再新增常驻的文风管理系统。
没有登记大纲的项目继续使用原来的聊天写作入口；新资料参数不在旧路径中被静默忽略。

## 实际输入与验证

系统写作边界及人工最高指导在最前，最高指导仍保持 `system` 角色和原文。其余资料按以下顺序组装：

1. 作者登记的全部大纲文档原文，保留文档顺序、BOM、CRLF、空白及 Markdown。
2. 本次写作要求、目标、已有章要求及锁定状态；有选文时包含完整选文并明确“仅处理选文”。
3. 当前章节素材及显式相关正式正文／片段；编辑缓冲区与正式稿分开标记。有选文时不自动把整章当作修改范围。
4. 作者指定的范章／片段。
5. 目标之前实际存在的 N 章正式原文，不用摘要替换。

同一章同一区间承担多个用途时只发送一次，清单保留全部用途。每项材料有身份、修订、哈希、长度和必要范围；不会按相关性筛选大纲，也不自动调用人物状态、正典、伏笔或摘要记忆提供器。

正文引用只接受 `chapter_id`、`revision`、`source_hash` 和可选的 `start/end` 半开字符区间，不接受任意文件路径。哈希对应完整源章，范围只决定发送哪段原文；错误 ID、修订、哈希、区间、额外字段及非严格整数均拒绝。相关正文与范章合计最多 64 项，超限明确失败。

准备和确认时都校验当前大纲包、目标正式稿、编辑内容／选文、章要求、人工指导、引用原文、近期章序和模型配置。更换同名模型的连接地址、容量或采样参数也使旧提案失效；输入快照和配置指纹不包含密钥正文，认证继续由既有网关与系统凭据库处理。

模型上下文窗口必须已登记为有效整数，不沿用 BASIC 模式的未知容量回退。全文按 UTF-8 字节数作保守输入估算，另计输出和安全余量；未知或不足时明确失败，不能缩纲、降级摘要或静默删正文。

## 冻结输入与运行状态

- 提案尚未确认时只在当前会话内存中保留，不创建生成运行或确认凭据。重启后需要重新整理、审阅，不会自动开始生成。
- 确认后复用现有 generation run、Context Manifest、网关、流式生成与检查点，实际消息保存到 `.ai_pipeline/writer_inputs/<run_id>.json`。
- 快照只独占创建，包含完整消息、作者确认、出处、项目／运行／清单身份和整体校验和；读取失败不会重新读取当前资料来替代旧输入。
- 快照单文件上限 64MB；超过上限完整拒绝，不截断。目标路径校验防止通过链接转向其他文件。
- 输入读取在模型流开始前失败时，运行从 READY 转为 FAILED，释放活动写作状态，不会卡在“生成中”或谎称已经保留草稿。
- 一次确认只消费一次提案；取消与确认共用锁，不能由确认清掉并发取消。准备中取消也不会再发布待确认提案。
- 候选、部分结果和原始输入均不覆盖正式稿。旧记忆模块和旧项目接口保留；本票没有数据库迁移。

## 改动文件

新增源码，路径相对于 `src/ai_novel_studio/`：

- `application/outline_writer_input.py`：严格引用、只读资料组装、输入计划与失效校验。
- `application/outline_writer_service.py`：待确认提案、一次性作者确认、取消、冻结输入和候选执行。
- `infrastructure/storage/writer_input_repository.py`：不可变消息快照及完整性／身份检查。
- `ui_qml/qml/components/WriterInputReview.qml`：米色输入审阅与确认窗。

修改源码：

- `application/novel_read_service.py`：供内部输入组装读取未截断的编辑快照；MCP 展示限制不变。
- `application/novel_writer_service.py`：有大纲的新路径和原无大纲路径分离。
- `application/codex_session_service.py`、`infrastructure/mcp/novel_server.py`：显式正文引用参数及待确认语义。
- `ui_qml/bridge/codex_session_bridge.py`、`mock_novel_studio_facade.py`：审阅、确认、取消及异步生成状态。
- `ui_qml/qml/components/WriterTaskCard.qml`：范围／固定大纲版本、输入入口和候选状态。

新增测试：`tests/integration/application/test_outline_writer_input.py`、`tests/ui_qml/test_writer_input_review.py`。简短中英文 README 与路线文档同步进度。

## 验证结果

- 本票新增 31 项测试通过：后端 29 项、实际 QML 2 项。
- 原有及新增相关回归累计去重 **658 项通过**，无跳过；覆盖存储、草稿恢复、工作区、Codex 接入、小说 MCP、批量阅读及旧写作路径。
- 截获真实 `LLMGateway` 发给假适配器的最终 `LLMRequest`，逐条验证其角色、完整原文与审阅内容一致，并用禁止调用的旧记忆提供器验证新主链确实绕过旧编译。
- 取消锁交错、快照损坏、跨项目复制、正文／大纲／约束／连接／章序变化、长选文、范围与去重均有针对性断言。
- 真实 Codex + 本地假写作适配器串联通过：27,027 字虚构大纲，第五章相关正文、第一章范章及近期两章；确认前 0 次正文调用，确认后 1 次，最终请求与审阅完全一致，正式稿未变。没有调用付费正文供应商或读取作者小说。
- 待确认卡、完整输入窗、候选完成态完成离屏截图检查；相关 QML 无警告。辅助截图脚本首次因等待线程方式不当退出，改用 Qt 事件循环后完成验证，没有为此修改业务代码。
- Ruff、9 份相关 Python 源码的 MyPy、独立只读复核通过。MCP 依赖仍有既存的 Pydantic `lifespan` 前向引用警告，测试断言均通过。

在当前工作树设置 `PYTHONPATH=src`、`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`，用新临时目录复跑：

```powershell
python -m pytest tests/integration/application/test_outline_writer_input.py tests/ui_qml/test_writer_input_review.py tests/integration/application/test_novel_writer_service.py tests/ui_qml/test_codex_session_bridge.py -q -p no:cacheprovider --basetemp (Join-Path $env:TEMP ('ans-fo4a-' + [guid]::NewGuid().ToString('N')))
```

下一票：FO-4b，侧栏候选采用、放弃和恢复。必须进一步核对原选区位置与修订，不能把选文候选作为整章替换；恢复时读取原确认快照，不能重新按当前资料组装冒充旧任务。
