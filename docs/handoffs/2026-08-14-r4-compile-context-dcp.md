# DCP:R4 compile_context 公共门面设计决策提案

- 日期:2026-08-14
- 依据:H0 审计接受结论("public Context compilation require separate design
  decisions before implementation");设计 v0.3 §21-§24;补充文档 Ticket R4;
  本分支 R3b-Q1/Q2
- 状态:待用户/主控拍板,批准后另开实施票

## 1. 现状审计(全部核实)

- 编译链路分两段:application/generation_context_service.py 调
  GenerationMemoryContextProvider.blocks(...) 组装全部记忆/文风/历史块
  (含 HistoryRetriever 检索、手动固定、正典/伏笔/人物/摘要),再把块交给
  core/context/context_builder.py 的 ContextBuilder.build(ContextBuildRequest)
  做排序/过滤/去重/预算/Manifest。
- ContextBuilder 只处理"调用方预先准备的 ContextBlock"(H0 已确认)。
- 仓库中不存在 ContextProjection 概念;输出是 BuiltContext(text + manifest)。
- 设计 §21 要求 Context Compiler 是所有正式生成上下文的唯一编译入口,
  含硬过滤、四路召回、重排、权威裁决、去重、预算竞争、投影与 Manifest;
  Agent 只能通过 context.compile 进入正式生成。

## 2. 冲突

现状没有公共门面;块装配逻辑住在应用层 provider 里,检索由 provider 直接
发起,Harness 若自行装配块或自行检索即构成第二编译器。

## 3. 方案选项

A(推荐,渐进复用):新增 application 门面 compile_context(request) ->
  CompiledContext,内部顺序:
  1) 基础块:复用 GenerationMemoryContextProvider(降级为门面内部块工厂,
     不重写其检索逻辑);
  2) 证据通道:R3b-Q1 查询 + R3b-Q2 注入,evidence_requests 逐项编译为
     EXACT_EVIDENCE 块;
  3) 组装:现有 ContextBuilder 不变(排序/过滤/预算/去重/Manifest);
  4) 输出:新建有界 ContextProjection DTO(类别构成/证据摘要/预算占比)
     + 复用 ContextManifest。
  不重写 12 步管线,不引入第二检索路径。

B:按设计 §21 全量重写 Context Compiler 管线。风险大、违背 H0 最小复用,
  不推荐(除非用户明确要求)。

C:不加门面,仅把 R3b-Q2 块并入现有 provider。被 H0 否决(Harness 需要
  公共 Facade,不能直接构造块)。

## 4. 冻结契约草案(待拍板)

请求(本能力自有 DTO,不共享给其他模块):

    CompileContextRequest
      chapter_id                必填
      run_id                    可选(常驻边界:证据块仅本次编译,天然无持久化)
      requirement                可选(当前章要求文本,基础检索用)
      recent_chapter_texts       可选
      participant_ids / pov_character_id  可选
      budget                    TokenBudget(复用现有)
      evidence_requests          可选 tuple[EvidenceNeed, ...]
        EvidenceNeed: kind(EXACT_QUOTE|HISTORICAL_DETAIL|EXISTENCE_CHECK),
        query, subject_ids, limit, required_hits

输出:

    CompiledContext(projection: ContextProjection, manifest: ContextManifest)
    ContextProjection(新建,有界):text, included_categories 统计,
    evidence_hit_count, estimated_input_tokens, manifest_id

## 5. 决策点清单(请一次拍板,括号内为我的推荐)

D1 门面是否吸收 provider 全部块装配成为唯一入口?(是)
D2 ContextProjection 新建 DTO 而非复用 BuiltContext?(是,字段见上)
D3 evidence need 触发语义:Agent 显式声明(确定性,推荐)还是关键词自动触发
   (留后续)?(显式)
D4 Manifest 是否本票就加结构化 evidence 字段(routes/诊断分数)?设计 R4
   要求记录;若加,走兼容 envelope(新 schema_version,旧版可读)。(推荐本票
   只加可选 evidence_items 字段 + schema 版本升 3,旧 v1/v2 继续可读;
   若你希望最小化,可推迟到下一票)
D5 门面放置:application/compile_context_service.py?(是)
D6 旧调用方(generation_context_service)本票是否改走门面?(推荐:不改,
   门面先行,旧路径迁移单独一张票,降低回归面)

## 6. 明确不做(本票)

- 不改 ContextBuilder/Filter/Ranker/预算算法;不重写检索;
- 不做自动 evidence need 触发;不做 embedding 能力切换;
- 无 schema 修改(D4 若批准则仅 Manifest 数据类,无表)。
