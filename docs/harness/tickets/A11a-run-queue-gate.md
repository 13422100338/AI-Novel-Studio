# HARNESS-V1-A11a:V1 并发队列门禁(设计 §58)

- 日期:2026-08-14
- 设计来源:v0.3 §58、附录 B 决策 18
- 分支:agent/ai-agent-v1;基线:rebase 后 main @ 773c627(分支 d7b431b)
- 无 schema 变更

## 目标

- RunQueueGate:V1 并发规则"一个正式模型/工具 Run 执行"的确定性实现——
  任何 run 处于执行阶段(TASK_ANALYZED 至 WAITING_APPROVAL 八段)即返回
  QUEUE,否则 START;CREATED/终态/INTERRUPTED/STALE 不占用队列
- evaluate() 即"启动前重新校验"(设计 §58);普通聊天与后台维护不在本门禁
  范围(设计:可继续)

## 允许文件

- 新增 src/ai_novel_studio/harness/run_queue.py
- 新增 tests/integration/harness/test_run_queue.py
- 新增 docs/harness/tickets/A11a-run-queue-gate.md

## 禁止事项

- 不新增 schema / 迁移 / 表;不实现排队调度器/自动启动(属 RunEngine)
- 不修改 main

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
