# HARNESS-V1-A9b:失败分类与重试决策(设计 §56)

- 日期:2026-08-14
- 设计来源:v0.3 §56、附录 B 决策 23
- 分支:agent/ai-agent-v1;基线:A10a 提交 6662649
- 无 schema 变更

## 目标

- classify_failure:把失败确定性映射为编排决策 RETRY / RECOMPILE_ONCE /
  SAVE_PARTIAL_AND_ASK / STOP:
  - 瞬时供应商失败(408/429/5xx,retryable)-> RETRY(次数与 Retry-After
    由既有网关 RetryPolicy 执行,默认最多两次)
  - 上下文超预算(ContextTooLongError)-> RECOMPILE_ONCE
  - 长流中断(PartialStreamError)-> SAVE_PARTIAL_AND_ASK
  - 契约校验失败 -> STOP(内置已自动纠正一轮,不再循环)
  - 取消/终态/数据库/缺失模型凭据/未知 -> STOP
- 无"自动换模型"决策值(设计:不自动换备用模型)

## 允许文件

- 新增 src/ai_novel_studio/harness/failure_policy.py
- 新增 tests/unit/harness/test_failure_policy.py
- 新增 docs/harness/tickets/A9b-failure-classification.md

## 禁止事项

- 不新增 schema / 迁移 / 表;不修改网关重试逻辑
- 不实现重试执行循环(属 RunEngine,待 context.compile 冻结后)
- 不修改 main

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
