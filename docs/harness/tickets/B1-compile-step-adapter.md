# HARNESS-V1-B1:CompileContextService → HarnessRunEngine compile_step 适配器

- 日期:2026-08-15
- 设计来源:v0.3 §21-§24;契约 §2、§6、§10;handoff 2026-08-14 §4(B1)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:后端 CompileContextService(已合入 main,R4 DCP 已批准)

## 目标

CompileStepAdapter:实现 A12 预留的 ContextCompileStep 端口,把后端
CompileContextService 接进 HarnessRunEngine.compile_step——

1. HarnessRun → CompileContextRequest 映射:chapter_id =
   run.active_chapter_id(缺失抛 CompileChapterMissingError,非法 UUID
   在发事件前即失败),run_id = run.id;budget、requirement、recent_chapter_
   texts、participant_ids、pov_character_id、evidence_requests 取自适配器
   构造时冻结值(budget 由调用方显式传入,不猜模型上下文窗口);
2. 经 HarnessEventStore 追加 CONTEXT_COMPILATION_STARTED / CONTEXT_COMPILED
   (COMPILED payload 含 chapter_id、manifest_id、estimated_input_tokens、
   evidence_hit_count、included_categories);build 失败则不追加 COMPILED;
3. 返回后端 CompiledContext;适配器不自行装配块、不保存第二套投影、
   不绕过 Context Compiler 拼生成上下文(契约 §6)。

## 允许文件

- 新增 src/ai_novel_studio/harness/compile_step.py
- 新增 tests/integration/harness/test_compile_step.py
- 新增 docs/harness/tickets/B1-compile-step-adapter.md

## 禁止事项

- 无 schema 变更;不改 run_engine.py 端口(适配器直接满足现有 Protocol);
- 不改后端 CompileContextService / ContextBuilder / 检索语义;
- 不引入第二套上下文装配或投影存储;不合并 main

## 已知限制

- 阶段迁移到 CONTEXT_COMPILED 与 manifest 挂接 GenerationPackage 由
  后续 B2 Agent 循环负责;本票只发射事件并返回 CompiledContext
- 适配器只支持一次编译(无 ContextExtensionRequest 重编译),留后续票

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_compile_step.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
