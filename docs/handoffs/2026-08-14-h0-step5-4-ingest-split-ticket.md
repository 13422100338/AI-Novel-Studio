# H0 步骤 5.4:状态提取拆接口不改行为

- 日期:2026-08-14
- 依据:H0 步骤 5 DCP D-7/D-8(用户批准推荐项 A);设计 §4"模型只提案"
- 分支:ds/r3b-q1

## 目标

把"模型调用"与"确定性落库"拆开:新增 MemoryCandidateIngestService 拥有
校验(来源章节/修订/哈希必须匹配当前正式正文)+ 摘要/人物状态/正典/伏笔/
知识候选的确定性写入;ManuscriptMemoryBuildService.build_all 的模型成功
分支改为委托 ingest,行为不变(既有 22 个测试全绿锁定)。Harness 未来可经
模型角色取得 MemoryCandidateBundle 后直接调 ingest,不再经过 build_all
的模型路径。

## 允许文件

- 新增 src/ai_novel_studio/application/memory_candidate_ingest.py
- 修改 manuscript_memory_build_service.py(委托 ingest,删除已搬移的私有
  辅助,行为不变)
- 新增 tests/integration/application/test_memory_candidate_ingest.py
- 新增 docs/handoffs/2026-08-14-h0-step5-4-ingest-split-ticket.md

## 禁止事项

- 无 schema 修改;不改 MemoryAnalyzer/模型调用路径(本票不接线,只拆接口)
- 不改 harness 分支/main/看板

## 验收

- 既有 build 测试 + 新 ingest 测试全绿;ruff;mypy;diff --check

## 回滚

- revert 本提交即可
