# FO-3：Codex 每轮完整大纲

日期：2026-10-19。状态：实现、临时项目回归及真实 Codex 验证完成，未提交或推送。
分支：`codex/full-outline-architecture`；沿用 FO-1／FO-2 的独立工作树，基线 `3d196bd`。
依据：[完整大纲方案](FULL_OUTLINE_WORKFLOW_2026-10-18.md)、[章节关联](FO2B_OUTLINE_CHAPTER_LINKS_2026-10-19.md)。

## 当前行为

- 打开项目，在“大纲”中保存全书总览及分卷文档，再正常使用右侧 Codex 对话。
- 每次发送前保存当前大纲编辑；保存冲突时保留缓冲区并停止发送，不暗中使用旧版本。
- 每轮按文档顺序前置全部登记大纲的完整原文，保留 BOM、CRLF、空白、编号与 Markdown。无需作为普通消息或附件粘贴，普通聊天的 20,000 字符限制不变。
- 每份文档附身份、修订、长度与哈希；本轮整体版本固定。运行中追加要求使用同一份完整快照，期间改纲在下一轮生效。
- 新对话、恢复、切换、分支以及手动压缩后的下一轮，均重新读取并注入当前原文。
- 当前版本已确认的章节关联附为轻量清单，提供 `chapter_id` 供现有 `read_novel_chapters` 批量读取。原文链接保留，未确认关系不伪装成已确认关系。
- 不自动将章节全文加入 Codex 输入；关联收集只读章节元数据。关联索引损坏时发送完整大纲，但明确显示索引不可用，已确认清单置空。
- 侧栏每轮只增加一张“本轮完整大纲”摘要卡，显示文档数、字符数、版本、关联与容量估算。恢复聊天时收拢软件注入的大纲块，保留作者原问题；Codex 的历史输入并未因此删除。
- 没有登记大纲的旧项目继续使用既有对话流程，不新增容量门槛。

## 容量、传输与压缩

发送前读取 Codex 的 `model_context_window` 配置，结合已有运行时窗口和正数自动压缩阈值取较小容量。缺失或无效的容量配置会明确阻止有大纲的任务；不假定所有模型容量相同。

预检计入完整输入、会话历史、系统／工具与输出预留和安全余量。文本以 UTF-8／JSON 字节数作保守估算，不采用中文“字节数除以四”；图片每张额外预留 32,768 Token。估算不等于精确分词或供应商计费，服务端更严格的上下文限制仍会明确报错，不能借此声称模型实际理解无误。

- 预算不足时完整拒绝，展示输入、历史与预留占用；建议新建会话或减少可选资料，不能缩纲或降级成摘要。
- JSON-RPC 单帧收发均限制 8MB。大纲资产仍可保存至 FO-1 的 20MB 上限，但超出单次协议承载能力会明确拒绝，不发送一部分，也不因超限删除原文。
- 普通手动压缩沿用现有功能；下一轮重新注入整纲。
- 活动创作中收到 `contextCompaction` 生命周期或旧压缩事件时，立即关闭当前 Codex 连接并撤销写作／读取工具，停止显示后续回复。提示作者重新发送，新的端口会再次读取完整大纲。

协议依据为[官方 Codex App Server 文档](https://learn.chatgpt.com/docs/app-server)，并核对本机 `codex-cli 0.163.0-alpha.10.2` 生成的协议 schema：`turn/start.input`、`turn/steer`、`thread/compact/start`、`contextCompaction`、Token 用量与窗口事件。没有假定存在每轮 `baseInstructions` 字段。

## 改动文件

以下源码路径相对于 `src/ai_novel_studio/`：

- `application/codex_outline_context.py`：只读完整大纲快照、已确认章节映射、容量检查与聊天历史展示。
- `application/codex_session_service.py`：每轮／追加输入、容量与压缩保护、明确错误、侧栏摘要事件及创作助手指令。
- `domain/outline.py`：共用大纲包指纹，保持与 FO-2b 确认语义一致。
- `infrastructure/storage/outline_repository.py`：同一只读事务读取全部登记文档并验证原文。
- `infrastructure/storage/outline_link_repository.py`：只读列举已登记关联，不扫描写入或自动确认。
- `infrastructure/codex/app_server.py`：单帧编码上限与明确的超限响应错误。
- `ui_qml/bridge/codex_session_bridge.py`：项目大纲绑定、每轮汇总卡及追加失败提示。
- `ui_qml/bridge/mock_novel_studio_facade.py`：发送前的大纲保存保护。

测试：新增 `tests/integration/application/test_codex_outline_context.py`，扩展 `tests/ui_qml/test_codex_session_bridge.py` 与 `tests/unit/application/test_codex_app_server.py`。中英文 README 和路线文档同步进度，继续保持简短。

不新增数据库迁移，不改独立正文模型的输入主链，不移除旧记忆模块。数据读取使用项目只读数据库包装，不迁移或修改作者数据库。

## 验证

- 本票新增 24 项测试；存储／应用／草稿恢复 396 项、界面与工作区 169 项、Codex 协议与控件 32 项、小说 MCP／正文写作／批量阅读／写作指令 30 项，共 **627 项通过**，无跳过。
- Ruff、8 份相关源码的 MyPy、差异及文档检查通过；独立只读复核通过。
- 既有 MCP 依赖在两组测试中出现同一条 Pydantic `lifespan` 前向引用警告；断言与测试均通过，本票没有修改第三方依赖。
- 米色主题摘要卡完成离屏视觉检查，相关 QML 无警告；没有启动可见桌面窗口。
- 真实 Codex：以 27,296 字的临时虚构大纲，在开头、中段、末尾设置随机值。新对话、改纲后、手动压缩后、分支、进程重启恢复共五次均完整取出三处随机值；改纲后版本指纹同步变化。
- 真实自动压缩保护：只在另一份临时测试会话把阈值设为 1,000 Token。第一轮未触发压缩，带有历史的第二轮触发后成功关闭连接，压缩后的输出为零；没有修改全局 Codex 设置。
- 所有数据库与正文验证均使用临时项目。真实模型只收到测试生成的虚构材料，未打开作者小说。

按新的临时目录复跑，设置 `PYTHONPATH=src`、`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`：

```powershell
python -m pytest tests/integration/application/test_codex_outline_context.py tests/unit/application/test_codex_session_service.py tests/unit/application/test_codex_app_server.py tests/ui_qml/test_codex_session_bridge.py -q -p no:cacheprovider --basetemp (Join-Path $env:TEMP ('ans-fo3-' + [guid]::NewGuid().ToString('N')))
```

尚未实施：FO-4 的独立正文模型完整大纲／正文引用组装与作者输入确认；专用 AI 关联提案入口。Codex 读过的正文目前仍不会自动成为独立正文模型的输入，不能把本票当成双模型闭环已经完成。
