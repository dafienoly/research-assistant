# Hermes VNext 未解决项

更新时间：2026-07-12。以下项目不会被示例、mock、静默 fallback 或“已开发”措辞掩盖。

## 阻止模型/策略晋级的真实缺口

- 数据审计仍为 `PARTIAL`：按 U0 代码集合核对，资金流匹配 5,401/5,530、缺 129，财务匹配 5,528/5,530、缺 2；精确补拉对这些代码得到上游空结果。概念 409/380、行业 511/80 已为 OK；三份产业链/主题标签已从受版本控制语义和 canonical `stock_basic` 原子生成，不再缺失。当前唯一 data-gap 报告为已验证空的 preopen policy event，影响级别 minor。
- Canonical DataHub 核心新鲜度已为 OK：活跃股票 5,530/5,530，5,526 只最新至 2026-07-10，另 4 只由官方 `suspend_d` 解释；正式 ML 和 Shadow 数据门禁为 OK。生产 BUY OrderDraft 仍因资金流/财务/标签辅助缺口保持 BLOCKED，保护性 SELL 数据门禁为 OK。
- 市场 Event Truth 已真实拉取 13 个指数/ETF 代理，覆盖 `stk_limit`、`suspend_d`、现金分红和复权因子；公司事件已完成 166 个有效 U3 A 股标的，holdertrade 892、repurchase 493、share_float 1,412、dividend 5,363。forecast 网关持续返回非 JSON，累计三次后熔断，因此公司事件保持 `PARTIAL`，不得宣称完整。
- Events API 已删除固定虚假行情/卖单/资金流事件，逐分区验证公司事件 manifest SHA 后返回真实列表和详情；事件因子 1/5/20 日表现尚无权威产物，继续返回空数组而非估算值。
- Legacy Backtest Lab 的随机指标/NAV/交易生成器已退役，提交现在 fail-visible 并指向 VNext 已验证回测产物；若恢复交互式提交，必须接入 canonical universe、用户日期、真实成本、Event Truth 和 OOS runner，不能复用旧硬编码 CLI。
- Live Readiness API 已接真实 13 门禁并补 QMT/确认持仓/当日授权/三阶段认证四项硬阻断；Portfolio latest 已接 VNext cost-aware artifact，Theme history 已接 DataHub SHA 等权投影。Portfolio run 与 Theme status/subsector 的完整交互能力在 governed runner/canonical projection 接入前继续 fail-visible。
- Strategy Lab 固定个股信号及 Portfolio Builder 随机/内置兜底信号已物理删除；Paper/Shadow 也禁止缺省信号。正式 strategy signal runner 尚未接入 DataHub snapshot/manifest/universe/version，因此对应 latest 命令保持明确阻断。历史 `data/portfolio` 产物保留但视为未验证，不进入执行链。
- 组合回测的 synthetic benchmark 已从默认路径移除，仅允许测试显式开启；真实基准不可用时结果保持无基准并携带 warning。`benchmark.py` 内部合成生成器仍为测试兼容代码，后续可迁移到 tests fixture 后彻底删除。
- `factor:mine`/注册、策略报告、行业轮动与行业排名的无输入随机演示路径已在真实 CLI 分发顺序上阻断；策略报告支持显式真实收益 CSV。`factor_commands` 与 `hermes_cli` 仍存在重复 command registry 和不可达旧代码，需物理合并后才能消除维护漂移。
- 自动 Research Skill 的 strategy-report/factor-mining/sector-rotation 也已 fail-closed，demo 参数不能再生成“completed”结果。真实 handler 尚需接入 DataHub snapshot、manifest SHA、universe version、forward return 与行业映射；旧随机实现目前不可达但仍应在重建时物理删除。
- 已退役的 research:loop/AutoResearchLoop 公共启动函数现统一 BLOCKED，不再评估、入队或注册自动候选。`research_loop.py` 与同名 package 的双实现仍需物理合并；历史类不可作为恢复自动 Agent 开发系统的依据。
- Live Readiness 的 Paper 状态缺失函数和 Benchmark 错误导入已修复：真实 Paper 权益为 21 日，六个 canonical benchmark 均可用。Telegram/企业微信凭据已从 Windows 用户环境桥接到权限 600 的非仓库 runtime env，实际 cron worker 显式加载；基础 13 门禁现为 13 pass/0 blocker/0 warning。API 额外 QMT、确认持仓、授权、认证门禁仍禁止实盘。
- 决策认证回放使用 WSL `/tmp` 后通过半导体设备 ETF 高开横盘后收跌 7% 案例，2 点 L2、3 点减半、结构破位 10 分钟退出和事件去重均为 true；Stage 1 Paper 通过。Stage 2 仍缺连续真实 Shadow、配对成交和权益曲线，保持未通过。Stage 3 因无 MiniQMT 权限按用户要求跳过实测，同时永久保持实盘关闭。
- 行级完整性审计当前为 OK（活跃 5,530 文件、0 问题行）；曾污染的 3 个文件已从最早干净 D 盘快照恢复，污染原件保留在 `quarantine_polluted_market_20260712_0134`。该事件说明备份恢复已生效，但恢复后的连续每日门禁仍需观察。
- 监管公告 ingestion 与覆盖感知门禁已实现并安装 08:57 cron。真实 smoke 曾发现 CNINFO 缺 orgId 时返回全市场公告，原“30 条”证据已撤销；现按上游 `secCode` 验证并二阶段使用 `688012,orgId` 拉取，得到 1 条证券专属公告、覆盖 `OK`。该证据仅证明 688012，不代表全市场覆盖。
- Antifragile Review 缺 realized Regime/Semi/Style 标签、滚动模型衰减历史及连续 Paper/Shadow 权益曲线，因此相关六项指标为 null。
- vectorbt 第二个 OOS fold 收益为 -6.03%，不得用第一段或样本内结果替代。

## 外部运行条件

- Telegram 与企业微信已完成一次真实双通道 HTTP 200 发送；共享确认和单通道失败隔离已通过测试。后续仍需持续运行回执监控，实盘执行不由通知成功自动解锁。
- 用户已明确说明没有 MiniQMT 权限，并豁免本次真实账户/持仓/小额白名单实测。QMT Bridge 行情侧和接口自动化测试保留，`XtQuantTrader connect failed: -1` 属预期无权限状态；订单通道继续 DISABLED，不以 mock 解锁，也不再把该外部实测列为本次交付阻断。
- 应用内浏览器运行时可加载，但本轮 `agent.browsers.list()` 返回空列表；HTTP、DOM、lint、Vitest 和生产构建已通过，真实浏览器 console/点击证据仍 BLOCKED。
- `scripts/mx_fetch_step.py` 曾包含硬编码高熵凭据，现已改为 `MX_APIKEY` 环境变量；旧凭据必须在提供方撤销/轮换，代码删除不能清除 Git 历史。
- `dive_prediction/datahub_supplement.py` 曾明文保存 JoinQuant 账号密码，现已物理删除并退役直连入口；该 JoinQuant 密码同样必须在提供方轮换，Git 历史按泄露凭据处理。

## 供应链与产品化剩余风险

- Core 与实际启用的隔离 vectorbt Python 环境均使用完整 hashed lock 和 `--require-hashes`，审批清单固定 plain/hashed 文件 SHA，SBOM记录两类摘要。vn.py/OpenBB/FinRL 仍为 comment-only 未安装状态；若未来启用，必须先解析并生成各自 hashed lock，SBOM/许可证报告不能替代来源完整性证明。
- 前端已完成路由懒加载和 Rolldown vendor 分组，最大生产块约 175 KB且无 chunk-size warning；应用内浏览器不可用导致真实 console/点击/截图仍待验收。
- vectorbt 受 Apache-2.0 + Commons Clause 约束，仅批准隔离内部研究；商业托管或分发前需重新审查。
- vn.py、OpenBB、FinRL/FinRL-X、Qbot 均未装入 Core；comment-only lock 表示“未安装”，不能宣称对应运行时已适配完成。
- 无真实订单发送实现；任何未来 Live 通道必须另行授权、安全评审、Paper/Shadow 稳定性证明和小额白名单验收。
- `intraday_monitor.py`、`etf_dive_warning.py`、`monitor_588710.py`、dive live predictor、dive 历史训练 collector 和 semiconductor event 生产加载路径均已收敛为 DataHub 只读消费者；旧 provider 方法已物理删除。159516 ETF canonical 日线已通过统一 fund_daily ingestion 接入 715 行，训练 smoke 使用最近 250 行且日期正确。KOSPI canonical 数据尚未接入，588710 看板会明确显示缺失。
- 全市场成交额不再调用业务层 `mx.py` 或合成 20 日均；canonical `derived/market_turnover` 已生成 60 日、5,738 源分区、CNY 单位和 SHA manifest。该投影需要随每日 DataHub DAG 连续观察，缺失/过期时盘中成交额结论保持 MISSING。
- Decision Loop JSONL 已使用不可抢占 `flock`、坏行 quarantine 和关联通知归档；仍需在真实积压、进程强杀和跨日恢复下持续观察。Alpha Registry 旧 D 盘 JSON 多写者尚未完全迁移到同一 CAS/单写入服务。
- Alpha Registry、人工确认、pending、Shadow 与 Promotion Queue/History 的主要状态已统一到 `flock + atomic replace/O_APPEND + fsync`；60 路队列并发和历史幂等追加专项已通过。仍需在真实进程强杀与磁盘故障下注入验证。测试隔离复核新增的两个 disabled Alpha 已登记保留，未自动删除。
- VNext 健康页面已改为只读取 canonical coverage/freshness/integrity 与 data audit，不再扫描目录或按 provider 名称猜健康；实时快照强制 manifest/hash 校验。真实连续运行仍需观察审计生成任务与页面状态更新时间是否一致。
- PassList 与监管真值已进入带交易日门禁的 `premarket` DAG，分钟实时快照也在联网前检查 canonical 日历；仍需观察下一真实交易日的 checkpoint、重试和运维告警。
- 双通道 outbox worker 已覆盖每天 08:00–20:59，避免盘后/周日 DAG 告警滞留；仍需在下一次真实故障中核对两通道回执与统一确认。
