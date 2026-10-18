# HARNESS-V1-B2:正文候选流 + 流式检查点

- 日期:2026-08-15
- 设计来源:v0.3 §42、§47、§52-§54、§63、§65、§73;契约 §4;handoff 2026-08-14 §4(B2)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:A1 事件日志 / A2 模型角色适配器 / A5 ArtifactStore / A12 RunEngine(均已实现)

## 目标

ChapterDraftStreamService:Chapter Draft Model 经 RunEngine 生成候选稿——

1. RunEngine 新增 `ChapterDraftStream` 协议端口 + `stream_draft(run_id,
   messages, output_token_limit)` 方法(设计 §73:流式输出由 RunEngine
   唯一编排;引擎解析 run 与取消令牌,孤儿 run 抛 RunCancelledError);
2. 服务经冻结的 HarnessModelAdapter 以 CHAPTER_DRAFT 角色流式调用,
   发射 CHAPTER_STREAM_STARTED / DELTA / CHECKPOINT_SAVED / COMPLETED
   事件走 A1 事件日志;
3. 确定性字符数检查点(默认 2000 字,构造可配):每次跨越阈值即把当前
   累积正文存为 PARTIAL_DRAFT 工件(内容寻址自动去重);
4. 完成时存 DRAFT_CANDIDATE 工件、发射 COMPLETED(含 artifact_id/
   character_count/用量)并把 run 迁到 DRAFT_SAVED;
5. 取消/失败:保存非空残稿为 PARTIAL_DRAFT 后原样上抛(CancellationError
   或 DraftStreamFailureError);取消后 run 已关闭,迟到事件被 A1 拒绝(§54);
6. REASONING 增量永不落事件日志(设计 §65 不展示隐藏思维链)。

## 允许文件

- 新增 src/ai_novel_studio/harness/draft_stream.py
- 修改 src/ai_novel_studio/harness/run_engine.py(仅加端口与方法)
- 新增 tests/integration/harness/test_draft_stream.py
- 新增 docs/harness/tickets/B2-draft-stream-checkpoints.md

## 禁止事项

- 无 schema 变更;不改 ArtifactStore 首次写入去重语义;
- 不建正文模型消息装配(TASK_BLOCK 渲染留 B8 接线票);不实现自动重试(A9b
  已有失败分类,重试策略留 Agent 循环票);
- 不改 cancel_run(RUN_CANCELLED 事件缺失是 A12 遗留,记入已知限制);
- 不合并 main

## 已知限制

- cancel_run 只迁移阶段不追加 RUN_CANCELLED 事件(A12 遗留),留后续
  RunEngine 硬化票;本票测试只断言"取消后无迟到流事件"
- 检查点按字符阈值而非段落边界;与最终正文字节相同的历史检查点会因
  内容寻址与 DRAFT_CANDIDATE 共享同一 artifact_id(首写元数据生效,已测试)
- 流式用量以网关最后一次 USAGE/COMPLETED 携带值为准

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_draft_stream.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
