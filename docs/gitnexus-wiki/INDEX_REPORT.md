======================================================================
  投研系统知识图谱索引报告
  GitNexus Knowledge Graph Index Report
======================================================================

生成时间:     2026-07-07T04:54:02.006Z
仓库路径:     /home/ly/.hermes/research-assistant
远程仓库:     https://github.com/dafienoly/research-assistant
最后提交:     f534196dcf1e

──────────────────────────────────────────────────────────────────────
一、代码规模总览
──────────────────────────────────────────────────────────────────────

  总文件数:    458
  符号节点:    10,182  (函数、类、变量、接口)
  关系边:      20,316  (调用链、继承、引用)
  社区聚类:    497  (功能模块)
  执行流程:    300  (跨模块调用链路)
  向量嵌入:    0  (语义搜索)

  索引引擎:    LadybugDB (图谱) + FTS (全文搜索)
  向量搜索:    不可用

  文件类型分布:
    .py         368 个文件
    .md          32 个文件
    .json        13 个文件
    .sh           9 个文件
    .cmd          8 个文件
    .jsx          8 个文件
    .ps1          6 个文件
    .yaml         5 个文件
    .js           2 个文件
    .html         2 个文件
    .css          2 个文件
    .example      1 个文件
    .jsonl        1 个文件
    (无扩展名)        1 个文件

──────────────────────────────────────────────────────────────────────
二、模块文档索引（GitNexus Wiki 自动生成）
──────────────────────────────────────────────────────────────────────

  Wiki 页面数: 15

  模块                                           大小     行数
  -------------------------------------- -------- ------
  strategy-portfolio-factor-lab             21768    591
  alpha-factory                             20575    531
  risk-safety                               17926    488
  api-agent-console                         16519    441
  broker-qmt-connectivity                   16461    394
  data-acquisition-commands                 15754    302
  research-system                           14509    404
  factor-engine                             12919    309
  strategy-portfolio-strategy-lab           12388    351
  core-framework                            11291    308
  strategy-portfolio-commands               10265    273
  frontend                                   9768    245
  data-acquisition-factor-lab                8691    257
  data-acquisition-scripts                   8226    191
  execution-pipeline                          298      5

──────────────────────────────────────────────────────────────────────
三、模块概览
──────────────────────────────────────────────────────────────────────

  strategy-portfolio-factor-lab           Strategy & Portfolio factor_lab — ETF 选择、Sector Rotation
  alpha-factory                           Alpha Factory — 因子全生命周期管理，从候选生成到退役治理的端到端管道
  risk-safety                             风控安全 — 规则定义→实时监控→断路器→事件审计→人工审批→事后复盘
  api-agent-console                       API & Agent Console — 三层 API 接口，SSE 流式推送，Claude Code 集成
  broker-qmt-connectivity                 Broker & QMT — 两层适配器架构，审批门控，运行时风控
  data-acquisition-commands               数据采集 CLI — 多源自动降级架构，含行情、公告、政策事件
  research-system                         Research System — LLM 驱动的因子自动发现与迭代优化系统
  factor-engine                           Factor Engine — 因子计算引擎，声明式注册表管理因子定义与计算
  strategy-portfolio-strategy-lab         Strategy Lab — 策略挖掘回测框架，含股票池构建、参数搜索
  core-framework                          Core 框架 — 统一基础设施层，含审计日志、门禁检查、产物追踪、配置管理
  strategy-portfolio-commands             策略回测 CLI — 均线交叉经典回测框架
  frontend                                前端监控面板 — React 18 + Vite + Ant Design 5，可视化路线图
  data-acquisition-factor-lab             数据采集 factor_lab — 分钟线存储、两融、北向资金流
  data-acquisition-scripts                数据采集脚本 — mx_fetch_step 步进式采集
  execution-pipeline                      Execution Pipeline — 执行管线（文档待完善）

──────────────────────────────────────────────────────────────────────
四、知识图谱结构分析
──────────────────────────────────────────────────────────────────────

  社区/聚类数: 497 — 表示代码中功能内聚的模块群
  流程/流数:   300 — 表示跨模块的执行链路（从入口到终点）
  节点密度:    22.2 节点/文件
  边密度:      2.00 边/节点

  主要模块关系链 (根据知识图谱推断):

    data-acquisition  ──→  factor-engine  ──→  strategy-lab
                          ↓                     ↓
                      alpha-factory        portfolio-backtest
                          ↓                     ↓
                    research-system  ──→  execution-pipeline
                                                     ↓
                                              broker-qmt (安全边界)

    全部由 API / Agent Console / Frontend 提供可视化和交互入口

──────────────────────────────────────────────────────────────────────
五、迭代开发参考建议
──────────────────────────────────────────────────────────────────────

  1. 当前版本 V6.8 (A-share Sector Rotation) 执行中, 自动推进至 V8.9
  2. Wiki 文档 `execution-pipeline` 仅 298 字节 (不完整)，建议优先完善
  3. 向量嵌入(embeddings=0) 未启用，开启后可实现语义搜索
  4. 大规模代码库 (10,182 节点) 建议定期用 gitnexus analyze 增量更新
  5. 跨模块调用链梳理可借助 GitNexus web UI 可视化浏览
  6. 知识图谱已关联至 gitnexus MCP，Claude Code 可直接查询

──────────────────────────────────────────────────────────────────────
六、访问方式
──────────────────────────────────────────────────────────────────────

  Web UI:      http://localhost:4747
  Wiki 文档:   .gitnexus/wiki/*.md (15 个模块文档)
  MCP Server:  http://localhost:4747/api/mcp
  CLI:         gitnexus list | status | wiki
