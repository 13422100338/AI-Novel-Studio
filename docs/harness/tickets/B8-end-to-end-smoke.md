# HARNESS-V1-B8:旧项目端到端冒烟(编译→生成→审校→审批→提交→重启恢复)

- 日期:2026-08-15
- 设计来源:v0.3 §73 端到端门禁、附录 D A14、§52-§57;handoff 2026-08-14 §4(B8)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:B1-B7 全部已实现;后端 LegacyProjectImporter / AuditClaimService /
  ChangeSetService 已合入 main

## 目标

1. ChapterGenerationLoop(harnes 编排链,唯一长事务编排入口):
   start → compile(B1 适配器)→ 阶段 CONTEXT_COMPILED → GenerationPackage
   (EditorSnapshot 冻结 + formal_revision + context_manifest_id)+
   GENERATION_PACKAGE_READY 事件 → PACKAGE_READY → build_draft_messages
   (PromptCompiler 组装:HARNESS_SYSTEM/GLOBAL + TASK_BLOCK/RUN +
   CONTEXT_PROJECTION/TURN + CURRENT_INPUT 最末)→ MODEL_RUNNING →
   stream_draft(B2)→ DRAFT_SAVED → 确定性审校(AuditClaimService 草稿路径,
   AUDIT_STARTED/COMPLETED 事件)→ AUDIT_COMPLETED → 构建 ChangeSet +
   CHANGESET_READY 事件 → 创建 CHANGESET 审批(WAITING_APPROVAL);
   finish():COMPLETED;批准后由 B3 解决器提交(零后端直写);
2. B6 胶囊补接 GENERATION_PACKAGE_READY 载荷(editor_snapshot_revision/
   formal_revision 从此有生产者);
3. 冒烟测试:旧格式项目经 LegacyProjectImporter 导入 → 循环生成候选稿
   (假流式网关)→ 审校 → 审批 → 批准提交(revision+1、正文更新)→ 重启
   (重开 ProjectRepository)后事件/审批/胶囊/恢复投影/正文全部可恢复;
   另覆盖取消路径(残稿入 DRAFT_CHECKPOINT/PARTIAL_DRAFT、无迟到事件)。

## 允许文件

- 新增 src/ai_novel_studio/harness/agent_loop.py
- 修改 src/ai_novel_studio/harness/projections.py(capsule 两字段接载荷)
- 新增 tests/integration/harness/test_end_to_end_smoke.py
- 新增 docs/harness/tickets/B8-end-to-end-smoke.md

## 禁止事项

- 无 schema 变更;不改后端 Facade/导入器/审校/ChangeSet;
- 不实现 Main Agent 模型循环(解释性审校留后续)、不实现自动重试;
- 不合并 main

## 已知限制

- 确定性链以 BASIC/MINIMAL 映射旧审校模式(QUICK→BASIC);
  Main Agent 模型解释 Finding 与返工流留后续票
- 审批与提交非跨系统原子(继承 B3 已知限制)

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_end_to_end_smoke.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
