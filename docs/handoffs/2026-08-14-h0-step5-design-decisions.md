# H0 步骤 5:五项设计冲突的决策提案(DCP)

- 日期:2026-08-14
- 依据:H0 审计接受结论——ProjectConstitution、Subject 合并演进、
  ChangeSet/approval、状态提取模型所有权、Plan 语义需单独设计决策后再实施
- 状态:待用户/主控逐项拍板;批准项另开实施票

## 1. ProjectConstitution 与 ProjectGuidance 的关系

现状(已核实):domain/project_guidance.py + project_guidance_repository +
project_guidance_service + ADR 0008;当前语义=剧情商讨注入的只读提示与
最近三章全文。设计 v0.3 §37.1 要求"小说最高提示词"是一等、版本化领域对象
(分层规则/提案/审批/历史版本/导出),进入 Project Stable Prefix。

冲突:两者都是"项目级、作者可编辑、注入模型的文本",字段与生命周期重叠。

选项:
  A(推荐):扩展 ProjectGuidance 为版本化宪法领域——保留现有只读提示职责,
    新增 revision/分层规则(shared/agent_only/writer_only/overridable)/
    提案与审批流/历史版本,一套对象两种用途。
  B:并存分工——Guidance 只管剧情商讨,Constitution 新建只管生成宪法;
    需要迁移现有 guidance 数据,且长期两套重叠配置。
  C:完全替换(删除 ProjectGuidance)。不推荐,破坏现有剧情商讨功能。

决策点:D-1 选 A/B/C;D-2 若 A,分层字段是否一步到位(推荐一步到位,
schema 由主控分配版本)。

## 2. Subject 合并演进

现状(已核实):character_identity_service + character_identity_merges 表
(v12 backfill)已有合并、引用迁移与撤销事务;H0 审计确认"已有、可撤销的
Character/Subject 合并事务"。设计 §27.1.1 要求 subject 层合并 +
MergePreview/MergeManifest/alias/tombstone + 并发控制 + 撤销。

冲突:设计语义与现有实现基本一致,缺的是面向 Harness 的预览/提案门面与
MergeManifest 输出合同;无需重造事务。

选项:
  A(推荐):在现有合并事务之上加 build_subject_merge/preview 门面,
    MergeManifest 复用现有 merge 记录 + 撤销接口;Harness 只提案不执行。
  B:新建独立 subject 合并域并迁移 character 合并。不推荐(重复事务)。

决策点:D-3 选 A/B;D-4 MergeManifest 的导出字段清单(建议:id/主卡/被并卡/
别名保留/引用迁移计数/冲突字段/可撤销)。

## 3. ChangeSet 与审批对接

现状(已核实):Harness 侧审批生命周期已完成(A8a,harness 分支 schema v22,
PENDING->APPROVED/REJECTED + 事件 + 幂等);后端无统一 ChangeSet 概念,
提交分散在 submit_revision/repair 等既有边界。

冲突:Harness 需要后端 build_changeset(干跑+影响分析)与 commit_changeset
(审批凭证 + expected_revision + 幂等键)两个 Facade;后端要避免为每种操作
各写一套提交。

选项:
  A(推荐,最小):ChangeSet = 一组 typed operations(chapter_content_replace/
    repair_apply/title_change),build 只做干跑与影响投影(复用 submit_revision
    的 expected_revision 校验与 FormalMaintenance),commit 映射到既有边界;
    ApprovalRequest 载荷先只支持 CHANGESET 一种 kind。
  B:完整通用变更模型 + 统一事务引擎。工作量大,留 V1.2。

决策点:D-5 选 A/B;D-6 ChangeSet operation 类型清单(推荐先三种)。

## 4. 状态提取的模型所有权

现状(已核实):manuscript_memory_build_service 等提取服务自行调用模型
(记忆整理一次一模型,契约明确模型调用由 Harness 唯一编排)。

冲突:Harness 拥有唯一模型编排权后,提取服务不能再自行发请求。

选项:
  A(推荐):把提取服务拆成"确定性子流程 + 接收已验证模型结果的纯函数";
    Harness 经 compile/model 角色调用模型后把结构化结果回填,提取服务只做
    校验、拆分、落库与依赖失效。
  B:提取服务保留模型调用,但注册为 Harness 经 Permission Gateway 调用的
    受管工具。仍违反"服务内自行发请求",不推荐。

决策点:D-7 选 A/B;D-8 迁移顺序(推荐:先拆接口不改行为,再逐条接线)。

## 5. Plan 语义与查询领域

现状(已核实):无正式 Plan 查询领域;计划类信息散在 chapter requirement、
project guidance 与记忆候选。设计要求 PLAN != CANON、PlanCandidate 生命周期
(EXPLORING/SHORTLISTED/APPROVED/...)。

冲突:为 V1 新建完整 Plan 领域成本高,且与现有大纲/要求重叠。

选项:
  A(推荐,V1 最小):只读 plan.query Facade 聚合现有来源(chapter requirement
    + guidance 中的确定大纲 + PlanCandidate 语义先落 chapter requirement 的
    分层字段),PLAN 与 CANON 分离由 Context 硬过滤保证;完整 Plan 领域留
    V1.1 单独设计。
  B:新建 Plan 领域(schema + 仓储 + 生命周期)。留待 V1.1 评审。

决策点:D-9 选 A/B。

## 汇总

五项各含选项与推荐;批准后每项开独立实施票,按 1->4->3->2->5 建议顺序
(依赖关系:1 无依赖;4 是 3 的模型侧前提;2 依赖审批凭证;5 可与 1 并行)。
