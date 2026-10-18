# 后端冻结请求与审计结论(H0 契约审计已接受,2026-08-14)

- 日期:2026-08-14
- 收件:Codex 后端 master / 用户指派的后端实施模型
- 发件:Harness 实施(agent/ai-agent-v1 分支)
- 依据:《Agent-Harness 总体设计 v0.3》§22、§73、附录 A、附录 D;
  《Agent实施与后端防冲突契约 v0.1》§9-§13;后端只读审计回复(2026-08-14)
- 状态:H0 契约审计已完成并被看板接受(main @ 773c627);本分支已 rebase 到
  该基线。被接受的冻结结论:不做单一共享 DTO 大文件、不做一次性 15 Facade
  大票;每个能力只拥有自己的有界公共 DTO;复用/适配 Context Manifest、
  Formal Evidence、RevisionImpact、Audit、ProjectGuidance、Subject、
  Character Identity、Style、Context Pin 既有权威;ProjectConstitution /
  Subject 合并演进 / ChangeSet+审批 / 状态提取模型所有权 / Plan 语义 /
  公共 Context 编译需单独设计决策后再实施。首选实施候选 R3b-Q1(基于
  HistoryRetriever/Subject 解析 + R3a 精确水合的 Formal-current 证据查询
  门面),但 R3b-Q1 及之后每个 Facade 仍需用户单独授权。

## 1. Harness 侧已完成(不变)

分支 agent/ai-agent-v1(未合并 main)已交付契约 §12"可立即独立实现"清单全部项,
8 个提交(A1-A6,含 schema v21 纯追加 harness_runs/harness_run_events)。
读取方式:

    git show agent/ai-agent-v1:docs/harness/README.md
    git show agent/ai-agent-v1:docs/harness/agent-harness-design-v0.3.md
    git show agent/ai-agent-v1:docs/harness/agent-implementation-backend-contract-v0.1.md

## 2. 阻塞原因与当前共识

附录 D 剩余项需要后端 Public Facade 与共享 DTO 支持,且冻结必须增量进行
(一次性冻结会重复现有后端能力,甚至形成第二套领域系统——后端审计结论)。
因此改为按下述顺序逐票推进,不做"大合同文件"。

## 3. 后端只读审计结论(2026-08-14,以审计为准,修正本请求初版)

### 3.1 可以复用或适配(不必新做)

    submit_revision + RevisionImpact(R2b-C 已集成)
    R3a 的 EvidenceSet / EvidenceHit(精确回源已集成)
    ContextManifest v2(M1 已集成)
    StyleRetriever / CompiledStyle(ST1 已集成)
    SubjectRepository(CHARACTER + 别名)
    AuditFinding(deterministic_audit + 仓储)
    ProjectGuidance(现有项目指引领域)
    已有、可撤销的 Character/Subject 合并事务(初版此处判断有误,予以更正)

### 3.2 真正缺失

    query_subject_evidence 的完整查询门面(现只有"拿候选 ID 精确回源")
    正式 Plan 查询领域
    通用 ChangeSet
    EditorSnapshot / GenerationPackage 的共享契约
    ProjectConstitution 的提案、审批与历史版本

### 3.3 必须先解决的设计冲突(更新设计文档后再实施)

    ProjectConstitution 与现有 ProjectGuidance 重叠 —— 需界定边界
    compile_context 不能直接等于现有 ContextBuilder(后者只处理调用方预制的
    ContextBlock)
    ApprovalRequest 生命周期归 Harness 所有;后端只验证审批凭证并执行确定性
    提交(该结论与契约 §2 一致,Harness 侧据此可在后端 DTO 冻结前先建审批
    生命周期骨架)
    现有状态提取服务自行调用模型,与 Harness 唯一模型编排权冲突 —— 需设计
    更新(改造成接受外部模型结果或经 Facade 编排)

## 4. 建议实施顺序(后端侧)

    1. R3b-Q1 query_subject_evidence:复用现有检索 + R3a 精确回源;
       只允许当前、有效的 Formal Manuscript 证据;无 schema 修改。
    2. 运行时注入(evidence 进入 compile 链路)。
    3. R4 compile_context 公共门面(在 ContextBuilder 之上定义新门面契约)。
    4. 逐项适配 StyleProjection、SubjectInspection、AuditFinding、submit_revision。
    5. ProjectConstitution、Subject Merge、ChangeSet、Plan 查询、状态提取:
       先更新设计文档,再实施。

## 5. Schema 版本协调(需作者决策)

    main 当前 v20;Harness 分支占用未合并的 v21(纯追加)。
    后端不得同时创建 v21;后端未来迁移将由主控分配 v22。
    需要作者先决定 Harness v21 的合并/变基顺序(选项见 README 决策点)。

## 6. 后端完成后的交接

每完成一个 Facade:窄测试 + ruff + mypy 全绿;向用户提交 READY FOR MASTER
REVIEW,注明 Facade 清单、DTO 定义文件路径、schema 版本号(如有)、与设计
文档的任何偏差。Harness 侧按冻结进度逐项接线(A5 起),集成由作者协调,
不自行合并 main。
