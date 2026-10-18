# AI Novel Studio — Agent 总设计交付报告

> 日期:2026-08-15 · 分支:`agent/ai-agent-v1`(工作树 `<repo>/`)
> 交付对象:Harness 编排层(V1 纵向切片)+ 与后端 H0 门面的接线
> 状态:设计权威内 55 项决策未改;B1–B10 与审查修复 F1–F7 全部落地;未合并 main(集成由作者指示)

## 1. 交付总览

- **一句话**:从"骨架齐备"推进到"端到端闭环"——真实旧项目可经 Harness 完成
  编译→生成→审校→审批→提交→重启恢复的完整链路,且具备权限闸门、状态机
  校验、事件溯源、共享恢复树与可审计请求清单。
- **代码**:新增 16 个 harness 模块、1 个 schema v24 迁移;修改 4 个既有模块。
- **测试**:harness+storage 447 通过;仓库全量 1497 通过(+1 个与本次无关的
  GBK 环境失败,main 同样存在);ruff 0;mypy strict 0。
- **提交**:B1–B10 九个提交、F1–F7 十个提交、2 个文档提交,全部在
  `agent/ai-agent-v1`,每票一提交、可逐票回滚。

## 2. 设计权威与三条红线

实现全程以两份权威文档为准,未做任何设计变更:

- `docs/harness/agent-harness-design-v0.3.md`(55 项锁定决策)
- `docs/harness/agent-implementation-backend-contract-v0.1.md`(接线契约)

三条红线均有测试与审计锁定:

```text
1. Harness 不存第二套领域存储 —— 仅 runs/events/approvals/manifests 四张编排表
2. backend(domain/core/application/infrastructure)对 harness 的 import 为 0
   (test_harness_boundaries.py 四层扫描,零违规)
3. 无旧 Pipeline 双编排 —— 唯一长事务编排器是 HarnessRunEngine
```

## 3. 交付范围

### 3.1 主线 B1–B10(handoff 2026-08-14 第 4 节全部清单)

| 票 | 内容 | 关键文件 |
|---|---|---|
| B1 | 后端 CompileContextService 接入 RunEngine compile_step 端口 | `compile_step.py` |
| B2 | 正文候选流 + 流式检查点(经 RunEngine,事件走 A1,残稿入 ArtifactStore) | `draft_stream.py` |
| B3 | 审批解决器:批准后调后端 commit_changeset / commit_subject_merge | `approval_resolver.py` |
| B5 | subject.inspect / compare / propose_merge / preview_merge 四工具 | `subject_tools.py` |
| B6 | AgentContextStatusProjection + 胶囊/上下文状态栏命令 | `projections.py` |
| B7 | 正文检查点与共享检查点基础设施对接(`.ai_pipeline/artifacts`) | `artifacts.py` |
| B8 | 端到端编排链 + 旧项目冒烟(编译→生成→审校→审批→提交→重启恢复) | `agent_loop.py` |
| B9 | 核心工具 9 个(薄门面 + 手写确定性校验,零新依赖) | `core_tools.py` |
| B10 | ModelRequestManifest 落库(v24)、Artifact 保留清理、Skill 运行时装载、恢复中心续接取消令牌 | `schema_migrations_v24.py` 等 |

### 3.2 审查修复 F1–F7(审查票 `docs/handoffs/2026-08-15-harness-audit-fix-tickets.md`)

| 票 | 内容 |
|---|---|
| F1 | 每次工具调用强制过 PermissionGateway,补 TOOL_CALL_* 事件,删除死字段 |
| F2 | 正文请求补 writer 专用宪法投影(§37.1 两层规则)+ §41 硬约束进任务块 |
| F3 | 生成前门禁:未决剧情阻止正文模型,原因进失败字段(§41) |
| F4 | GenerationProfile 按 §41.1 配对校验(QUICK↔MINIMAL、NORMAL↔STANDARD) |
| F5a | Subject 合并提交前 revision 只读复核,失配拒绝、审批保持 PENDING、run 标 STALE |
| F6 | 宪法工具改走 get_project_constitution 门面;三项门面缺口记录附录 A |
| F7 | 状态机合法迁移表;压缩禁区补两条;边界扫描扩四层;DELTA 事件全文出事件表 |

## 4. 关键机制(设计依据)

- **编排链(§73)**:`ChapterGenerationLoop` 是唯一长事务路径——compile(B1)
  → package 冻结 + GENERATION_PACKAGE_READY → draft stream(B2)→ 确定性审校
  (AuditClaimService 草稿路径)→ ChangeSet + 审批(B3)→ 批准后后端事务提交。
- **事件日志与状态机(§52-§63)**:13 态状态机 + 合法迁移表(F7-1);关闭态拒绝
  迟到事件;event_id 幂等;取消单向不复活;重启后事件/审批/胶囊/恢复投影完整。
- **上下文编译唯一入口(§21-§24)**:直接查询工具只用于回答/诊断;进入正式生成
  必经 context.compile;Manifest 为审计记录,projection 不落第二真相。
- **审批生命周期(A8a/B3/B4)**:模型只提案,程序执行;五类审批 kind;
  expected_revisions 并发控制;批准后由解决器派发后端提交,模型无提交工具。
- **候选流与检查点(§42/§53.1)**:DRAFT_CHECKPOINT/PARTIAL_DRAFT/DRAFT_CANDIDATE
  类型分离;内容寻址去重;项目级共享恢复树;全文只进工件,事件表只留长度。
- **请求可审计(§15)**:PromptCompiler 稳定性分层(胶囊/工具结果/作者输入永不进
  稳定前缀);ModelRequestManifest 落库(v24)可复现"模型当时看到了什么"。
- **恢复与保留(§55/§67)**:recover_open_runs 重建取消令牌;WAITING_APPROVAL
  审批卡可恢复;TOOL_RESULT/SUMMARY 30 天清理,创作工件永久。

## 5. 合规与安全

- 模型输出不可信:全部进后端 DTO 前经构造校验(ChangeSet、EvidenceNeed、
  Subject 合并参数、宪法提案、工具参数)。
- 权限不可绕过:唯一执行入口 `ToolExecutor`,Prompt/Skill 无旁路。
- 无 schema 滥用:v24 为 handoff 预授权的唯一新迁移,注册表版本连续。
- 不猜模型:预算/模式/输出上限由调用方显式注入,适配器不臆造。
- 不编造领域事实:F2 中后端未暴露的字段一律不填充,记录附录 A。

## 6. 验证命令

```text
.venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness tests/integration/storage -q --basetemp .test-temp\pytest
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy src/ai_novel_studio
```

## 7. 已知限制与后续事项(审查票附录 A)

1. F5b:后端 SubjectMergeService.commit 需在事务内做 expected_revisions 校验;
2. F2:后端投影需暴露 pov / story_time / 知识边界 / StyleProjection 等 §41 字段;
3. F6:manuscript.read / get_selection / memory.query / subject.query 缺应用门面;
4. Provider 级主动取消(现为协作式 token 轮询);
5. 胶囊 last_model_request_manifest_id 未接 Manifest 库(小接线)。

以上均为后端/作者立项事项,Harness 侧接口与记录格式已就绪。

## 8. 文档资产

- `docs/harness/tickets/B1–B10` — 十张实施票(范围/禁止项/验收/回滚)
- `docs/handoffs/2026-08-14-opencode-handoff.md` — 接手说明(基线)
- `docs/handoffs/2026-08-15-harness-audit-fix-tickets.md` — 合规审查票(含附录 A)
- `docs/handoffs/2026-08-15-harness-verification-guide.md` — 整体检查指导
- `docs/handoffs/2026-08-15-harness-audit-fix-verification.md` — 修复检查指导

**结论**:Harness V1 编排层已具备端到端闭环能力并通过合规审查修复;集成 main
与前端接线、附录 A 后端事项待作者指示。
