# R3b-Q2:EvidenceSet -> ContextBlock 运行时注入

- 日期:2026-08-14
- 依据:H0 序列第 2 步"运行时注入";补充文档 §4.1 链路与 Ticket R4 前置;
  R3b-Q1(同分支 cb0b8cc/ab1f73e)
- 分支:ds/r3b-q1 续用;工作树:.codex/worktrees/ds-r3b

## 目标

把 R3b EvidenceSet 确定性地转换为 ContextBlock 序列,使精确证据能进入
既有 ContextBuilder 编译链路并在 Manifest 中留下来源修订/哈希。

## 允许文件

- 新增 src/ai_novel_studio/core/context/evidence_context.py
- 新增 tests/integration/context/test_evidence_context.py
- 新增 docs/handoffs/2026-08-14-r3b-q2-evidence-injection-ticket.md(本票)

## 禁止事项

- 无 schema 修改;不修改 ContextBuilder/ContextManifest/R3a/R3b-Q1
- 不把 routes/诊断分数写进 Manifest 结构(属 R4;本票仅放 rationale 人类可读
  摘要)
- 不改 harness 分支 / main / 看板

## 行为契约

- 每个 EvidenceHit -> 一个 ContextBlock:category=EXACT_EVIDENCE,
  source_type=FORMAL_MANUSCRIPT,来源章节/修订/哈希取自 hit
- block.id 由 hit.document_id 派生,确定性且唯一
- 空 EvidenceSet -> 空块序列;INSUFFICIENT 的部分命中照常转换,由调用方
  按 outcome 决策(与 R3a 语义一致)
- priority/required 可注入(默认 50 / False)

## 验收

- 新测试全绿(含"块进入 ContextBuilder 且 Manifest 记录来源"的注入证明)
- 既有 context/R3a/R3b 测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
