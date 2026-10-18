# HARNESS-V1-B3:审批解决器(批准后调后端 commit 门面)

- 日期:2026-08-15
- 设计来源:v0.3 §54、§57、§63-§64、§944(审批解决器);契约 §8;handoff 2026-08-14 §4(B3)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:A8a 审批生命周期 / B4 宪法流(均已实现);后端 ChangeSetService、
  SubjectMergeService 已合入 main

## 目标

ApprovalResolver:resolve_and_commit(request_id, approved, note)——

1. 经 ApprovalService 决议(PENDING→APPROVED/REJECTED,事件已由 A8a 发射);
2. 拒绝:零后端写入,result=None;
3. 批准后按 kind 派发后端提交门面:
   - CHANGESET:payload 重建 ChangeSet(构造时全量校验,模型输出不可信)
     → ChangeSetService.commit(change_set, idempotency_key=审批幂等键);
   - SUBJECT_MERGE:payload 重建 merge 参数 → SubjectMergeService.merge(...,
     confirmed_by_user=True);
   - PROJECT_CONSTITUTION 由 B4 ConstitutionFlowService 负责(不重复实现);
     PROMPT_CHANGE / SKILL_CHANGE 无 V1 提交门面 → UnsupportedCommitError;
4. payload 编解码器公开导出(changeset_to_payload / changeset_from_payload /
   subject_merge_to_payload / subject_merge_from_payload)供 B5/B8 提案侧复用;
5. 提交前不触发后端写入;提交失败(如 Stale)审批记录保持 APPROVED,
   由 Harness 以新提案重试(B4 已知限制同源)。

## 允许文件

- 新增 src/ai_novel_studio/harness/approval_resolver.py
- 新增 tests/integration/harness/test_approval_resolver.py
- 新增 docs/harness/tickets/B3-approval-resolver.md

## 禁止事项

- 无 schema 变更;不改 run_engine.py / ApprovalService / B4 宪法流;
- 不改后端 ChangeSetService / SubjectMergeService 及其领域;
- 不重复实现 PROJECT_CONSTITUTION 提交;不合并 main

## 已知限制

- 决议与提交非跨系统原子:并发 Stale 时审批已 APPROVED(同 B4,留
  RunEngine 硬化票)
- 恶意/损坏 payload 在决议后才报 ValueError(审批已 APPROVED,零写入),
  与 B4 顺序一致

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_approval_resolver.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
