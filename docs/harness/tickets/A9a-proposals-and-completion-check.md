# HARNESS-V1-A9a:模型提案记录 + 程序侧完成校验

- 日期:2026-08-14
- 设计来源:v0.3 §33、§38、§57、§60
- 分支:agent/ai-agent-v1;基线:A8a 提交 67d3f1b
- 归属:PromptChangeProposal / SkillChangeProposal / TodoCandidate 不在契约
  §11 冻结 DTO 清单内,由 Harness 定义并校验;CompletionChecker 是设计 §57
  的"程序检查"半边

## 目标

- PromptChangeProposal:模型只提 Diff(ADD/REMOVE/REPLACE delta,带锚点),
  作者批准后由所属系统创建新版本;程序权限不因提示词提案改变
- SkillChangeProposal:只能改方法/检查项/输出结构/推荐工具/上下文配方,
  必须至少变更一项,skill id 沿用 snake_case 规则
- TodoCandidate:标题必填、明细归一
- CompletionChecker:
  check() 事后审计——COMPLETED 却带待审批 / WAITING_APPROVAL 却无待审批 /
  COMPLETED 却带 TOOL_CALL_FAILED -> 失败项
  can_complete() 完成门禁——有待审批或已 CANCELLED/FAILED -> 不允许

## 允许文件

- 新增 src/ai_novel_studio/harness/proposals.py / completion_check.py
- 新增 tests/unit/harness/test_proposals.py
- 新增 tests/integration/harness/test_completion_check.py
- 新增 docs/harness/tickets/A9a-proposals-and-completion-check.md

## 禁止事项

- 不新增 schema / 迁移 / 表
- 不持久化提案(批准后的落库属后端领域或后续票据)
- 不修改 main

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
