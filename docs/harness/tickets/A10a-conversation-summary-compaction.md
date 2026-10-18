# HARNESS-V1-A10a:会话滚动摘要 + 程序骨架提取 + 压缩门禁

- 日期:2026-08-14
- 设计来源:v0.3 §17-§20、§74(V1.1 结构化上下文压缩的数据面)
- 分支:agent/ai-agent-v1;基线:A9a 提交 6d06e0e + 审计文档提交
- 无 schema 变更;复用 ArtifactStore(新增 ArtifactKind.SUMMARY_REVISION)

## 目标

- ConversationSummary:设计 §17 八字段滚动摘要,列表去重归一;
  摘要永远不是小说领域真相源(§18)
- SummaryRevision:正数修订号 + UTC 时间戳的不可变版本
- build_program_skeleton:设计 §18 程序确定性提取半边——已批准审批摘要
  -> confirmed_decisions,已拒绝 -> rejected_options,作者批注 ->
  important_rationale;无确定性来源的字段留空由主 Agent 后补
- CompactionGate:设计 §19 禁区——MODEL_RUNNING(流式中)、有待审批、
  终态 run 一律禁止压缩;触发条件(预算压力/阶段结束/话题切换等)由调用方
- persist_summary_revision:修订版本以内容寻址工件持久化

## 允许文件

- 新增 src/ai_novel_studio/harness/conversation_summary.py / compaction.py
- 修改 src/ai_novel_studio/harness/artifacts.py(加 SUMMARY_REVISION kind)
- 新增 tests/unit/harness/test_conversation_summary.py
- 新增 tests/integration/harness/test_compaction.py
- 新增 docs/harness/tickets/A10a-conversation-summary-compaction.md

## 禁止事项

- 不新增 schema / 迁移 / 表
- 不实现主 Agent 自然语言压缩调用(A4 PromptCompiler 的 COMPACTION 角色
  已在模型层就绪,运行时接线等 RunEngine)
- 不修改 main

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
