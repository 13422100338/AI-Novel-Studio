# HARNESS-V1-B5:Agent 侧 Subject 合并工具四件套

- 日期:2026-08-15
- 设计来源:v0.3 §27.1.1、§29-§31;契约 §8.2;handoff 2026-08-14 §4(B5)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:A3 工具注册表/权限网关、A8a 审批、B3 审批解决器(均已实现);
  后端 SubjectInspectionService / SubjectMergeService 已合入 main

## 目标

subject.inspect / subject.compare / subject.preview_merge / subject.propose_merge——

1. 四个 ToolDefinition 注册进 Harness ToolRegistry(§29 元数据:inspect/
   compare/preview_merge 为 READ_ONLY/NONE;propose_merge 为
   PROPOSAL_ONLY,网关强制 idempotency_key);
2. SubjectToolService.execute(tool_id, arguments, run_id):
   - inspect:SubjectInspectionService 查询主体卡(类型/正名/活跃/别名);
   - compare:双卡 Inspection + 合并预览(状态事件数/共享章节冲突);
   - preview_merge:SubjectMergeService.preview 确定性预览(零写入);
   - propose_merge:参数校验 → 确定性预览(未知卡即报错)→ 经
     ApprovalService 创建 SUBJECT_MERGE 审批请求(payload 用 B3 编解码器),
     run 转 WAITING_APPROVAL;真正提交只由 B3 ApprovalResolver 执行,
     本工具不做任何领域写入;
3. 工具只接受 subject_id(名称发现归 B9 subject.query);未知工具/参数
   抛确定性错误;propose 按 (run_id, idempotency_key) 幂等(A8a 语义)。

## 允许文件

- 新增 src/ai_novel_studio/harness/subject_tools.py
- 新增 tests/integration/harness/test_subject_tools.py
- 新增 docs/harness/tickets/B5-subject-tools.md

## 禁止事项

- 无 schema 变更;不改后端 Subject 服务;不改网关/注册表实现;
- 不暴露 commit/merge 为模型工具(§27.1.1);不做名称别名解析(B9 范围);
- 不合并 main

## 已知限制

- 工具执行与网关判定由调用方串联(Agent 循环接线留 B8);
- 审批创建与预览分两次后端读,中间并发变更由审批侧 expected 校验兜底

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_subject_tools.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
