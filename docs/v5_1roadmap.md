# Hermes 任务：V5.1 Fullstack Remediation Pack — 修复 V5 验收阻断项

## 一、任务目标

基于 V5 全量验收审计结果，执行 V5.1 修复包。

本任务目标不是继续开发新功能，而是修复 V5 当前阻断项，使系统从：

CONDITIONAL FAIL
提升到至少：

CONDITIONAL PASS

优先级顺序必须是：

P0 数据与 API 主链路
→ P1 前端可用性与真实数据
→ P2 可观测性与测试体系
→ 最后重新执行 V5 全量验收审计

禁止在 P0/P1 未通过前继续开发 V6、新页面、新策略或新 Agent 能力。

---

## 二、必须读取的上下文

请先读取以下文件或最近一次审计目录：

1. V5 架构图：

```bash
/home/ly/.hermes/research-assistant/commands/frontend/v5-architecture.html
```

2. 最近一次 V5 审计报告目录：

```bash
/mnt/d/HermesReports/v5_fullstack_audit/20260709_105752/
```

如果该目录不存在，请自动查找：

```bash
/mnt/d/HermesReports/v5_fullstack_audit/
```

读取其中：

```bash
executive_summary.md
gate_result.md
fix_roadmap.md
raw/v5_api_audit.json
raw/v5_data_audit.json
raw/v5_static_audit.json
raw/feature_completeness.json
raw/test_coverage.json
```

3. 当前代码目录：

```bash
/home/ly/.hermes/research-assistant/commands
```

---

## 三、修复边界

本次只允许修复以下问题：

### P0 阻断项

1. 因子 API 与真实因子库脱节。
2. `/api/universe` 同步阻塞事件循环约 120 秒。

### P1 核心可信度问题

3. K 线数据 97 天未更新。
4. U1 用户可交易池未正确过滤。
5. 股票池市值字段全部为 null。
6. `/qmt`、`/events`、`/tasks` 3 个页面 JS 错误。
7. 6 个后端失败或超时端点。

### P2 验收体系问题

8. 半数 API 缺少 `as_of_date` / `freshness` / `lineage`。
9. Ops 路由泄露 traceback。
10. 缺少 Playwright E2E。
11. 部分后端路由未统一 `api_response()`。
12. K 线重复文件和 schema 不一致。

不要大改架构，不要重写前端，不要引入大型新框架。

---

## 四、P0-1：修复因子 API 与真实因子库脱节

### 当前问题

审计发现：

* `/api/factors` 只返回 6 个硬编码 `_SAMPLE_FACTORS`。
* 实际因子库中有约 124 个真实注册因子，但 API 不暴露。
* `/api/factors/{factor_id}` 也只查 sample。
* `/api/factors/{factor_id}/risk-attribution` 使用随机数或假计算。

### 修复要求

请定位真实因子注册表，优先搜索：

```bash
factor_base.py
REGISTRY
@register
factor_engine.py
routes_factor.py
```

必须完成：

1. 移除或隔离 `_SAMPLE_FACTORS`，禁止作为生产 API 默认返回。
2. 新增或修复因子注册表服务，例如：

```bash
commands/factor_lab/backend/services/factor_registry_service.py
```

3. `/api/factors` 必须从真实 `REGISTRY` 动态读取因子。
4. `/api/factors/{factor_id}` 必须返回真实因子详情。
5. `/api/factors/{factor_id}/risk-attribution` 禁止返回随机数。
   如果暂时无法计算，必须返回结构化状态：

```json
{
  "ok": true,
  "data": {
    "factor_id": "...",
    "computation_status": "not_available",
    "reason": "risk attribution requires computed factor values"
  }
}
```

不能返回 fake/random/mock 值。

### `/api/factors` 最低返回字段

每个 factor 至少包含：

```json
{
  "id": "ret5",
  "name": "5日动量",
  "category": "momentum",
  "expression": "...",
  "description": "...",
  "lookback": 5,
  "inputs": ["close"],
  "source": "factor_base.REGISTRY",
  "status": "active",
  "as_of_date": "YYYY-MM-DD",
  "freshness": {
    "status": "ok|stale|unknown",
    "latest_data_date": "YYYY-MM-DD"
  },
  "lineage": {
    "registry": "factor_base.py",
    "engine": "factor_engine.py"
  }
}
```

### 验收标准

必须新增测试：

```bash
tests/backend/test_factor_api_registry.py
```

测试要求：

1. `/api/factors` 返回因子数 >= 100。
2. 返回结果不包含 `_SAMPLE_FACTORS` 作为默认生产数据源。
3. 每个因子有 id、name/category 或等价 metadata。
4. 随机数风险归因被禁止。
5. 任取 3 个真实因子，`/api/factors/{factor_id}` 能返回详情。
6. 前端 FactorLab 页面能展示真实因子数量。

验收命令：

```bash
curl -s http://127.0.0.1:8766/api/factors | python3 -m json.tool
```

必须证明：

* factor_count >= 100
* source 包含真实 registry
* 无 mock/demo/sample/fallback/hardcode

---

## 五、P0-2：修复 `/api/universe` 阻塞事件循环

### 当前问题

审计发现：

* `/api/universe` 响应约 119972ms。
* async 端点中同步执行 `build_all()`。
* 服务器并发请求被全部排队。

### 修复要求

请定位：

```bash
routes_universe.py
universes.py
build_all()
```

必须完成：

1. `/api/universe` 不能在请求路径中同步重建全量股票池。
2. 增加缓存层：

```bash
commands/factor_lab/backend/services/universe_cache.py
```

3. 缓存 TTL 默认 1 小时。
4. warm cache 响应必须 < 1500ms。
5. cold rebuild 必须放到后台或线程池，不能阻塞事件循环。
6. 如果缓存存在但过期，可以先返回旧缓存，并标记：

```json
{
  "refreshing": true,
  "freshness": {
    "status": "stale",
    "latest_data_date": "YYYY-MM-DD"
  }
}
```

7. 如果完全无缓存，允许返回 202/accepted 或结构化空状态，但不能卡住 120 秒。

### 可选实现方式

优先使用：

```python
starlette.concurrency.run_in_threadpool
```

或：

```python
asyncio.to_thread
```

但必须保证 async endpoint 不直接执行 CPU/IO 重任务。

### 验收标准

新增测试：

```bash
tests/backend/test_universe_cache.py
```

测试要求：

1. warm cache `/api/universe` < 1500ms。
2. 并发 5 个请求不会串行等待 120 秒。
3. 返回结构含 `as_of_date`、`freshness`、`lineage`。
4. 返回结果能区分 U0 / U1 / U2 / U3 / U4 / ETF。
5. U1 不允许等于 U0 的简单复制。

验收命令：

```bash
time curl -s http://127.0.0.1:8766/api/universe > /tmp/universe.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/universe.json'))
print(d.keys())
print(d.get('meta') or d.get('freshness'))
PY
```

---

## 六、P1-1：恢复 K 线数据更新与 schema 统一

### 当前问题

审计发现：

* K 线最新日期停留在 2026-04-03。
* 距 2026-07-09 已 97 天未更新。
* 股票和 ETF K 线 schema 不一致。
* 存在 `_hist.csv` 与 `_daily_kline.csv` 重复文件。

### 修复要求

请不要直接删除旧数据。必须先备份：

```bash
/mnt/d/HermesReports/v5_1_remediation/backups/kline_YYYYMMDD_HHMMSS/
```

然后执行：

1. 自动识别当前标准 K 线目录。
2. 拉取 2026-04-03 之后至最近 A 股交易日的日线。
3. 优先使用当前系统已有数据源，不要新造数据源：

   * Tushare
   * Baostock
   * Eastmoney
   * Tencent
   * Sina
4. 统一股票和 ETF schema：

```text
code,timeString,open,high,low,close,volume,amount
```

5. ETF 也必须补充 `code` 列。
6. 对零成交量但价格不变的记录，标记为停牌或异常，不要静默当作正常交易日。
7. 清理重复 `_hist.csv`，但必须保留备份和 manifest。
8. 生成数据刷新报告：

```bash
/mnt/d/HermesReports/v5_1_remediation/data_refresh_report.md
/mnt/d/HermesReports/v5_1_remediation/raw/data_refresh_manifest.json
```

### 验收标准

新增测试：

```bash
tests/data/test_kline_freshness_schema.py
```

测试要求：

1. 最新 K 线日期距最近 A 股交易日 <= 3 个交易日。
2. 所有 K 线文件 schema 一致。
3. 无 `_hist.csv` 与 `_daily_kline.csv` 完全重复。
4. 无未来日期。
5. OHLC 合法：`high >= max(open, close)`，`low <= min(open, close)`。
6. 异常停牌数据有 status 标记或被过滤。

---

## 七、P1-2：修复股票池 U1 和市值字段

### 当前问题

审计发现：

* U1 用户可交易池与 U0 全 A 几乎等同。
* U1 未正确过滤退市/ST/不可交易标的。
* 所有股票池 `total_mv` / `float_mv` 为 null。
* industry 大量为 `nan`。
* concepts 全部为空。

### 修复要求

请定位：

```bash
universes.py
routes_universe.py
datahub.py
tushare_client.py
```

必须完成：

1. U0 定义为研究全量池，可以包含历史退市信息，但必须清楚标记。
2. U1 定义为用户可交易池，必须过滤：

   * 退市
   * ST / *ST
   * 停牌
   * 北交所，如果当前账户不交易
   * 科创板/创业板，如果用户账户权限不支持
   * 成交额过低标的，如果已有风控配置
3. U1 必须是 U0 的严格子集。
4. U1 不允许包含 name 含 “退” 的标的。
5. 使用 Tushare `daily_basic` 或等价数据补充：

   * total_mv
   * float_mv
   * turnover_rate
   * amount
6. industry 不能直接写字符串 `"nan"`。

   * 有数据则填行业。
   * 无数据则为 null，并给出 missing_reason。
7. concepts 暂时无法获取时，不要伪造；返回空数组可以，但必须在 lineage 中说明数据源限制。

### 验收标准

新增测试：

```bash
tests/data/test_universe_integrity.py
```

测试要求：

1. U1 股票数 < U0 股票数。
2. U1 中退市数 = 0。
3. U1 中 ST 数 = 0。
4. U1 中 name 含 “退” 的数量 = 0。
5. U1 中 `total_mv` 非空比例 >= 80%。
6. U1 中 `float_mv` 非空比例 >= 80%。
7. `/api/universe` 返回的 U1 与本地 universe 文件一致。

---

## 八、P1-3：修复 6 个后端失败或超时端点

### 当前失败端点

必须修复：

```text
GET  /api/roadmap
GET  /api/versions/report/detail
GET  /api/data/health
GET  /api/reports/summary
GET  /api/reports
POST /api/auto-run
```

同时优化：

```text
GET  /api/reports/backtest
POST /api/ops/backup
```

### 修复要求

1. 500 端点必须改为结构化错误或正常返回。
2. timeout 端点必须分页、缓存或后台化。
3. `/api/reports` 不允许同步扫描超大目录导致超时。
4. `/api/reports/summary` 应只读 manifest/index，不应全文扫描所有报告。
5. `/api/auto-run` 不允许在 HTTP 请求中同步执行长任务。应改为：

   * 创建任务
   * 返回 task_id
   * 后台执行
   * 前端轮询 `/api/tasks/{task_id}` 或已有任务接口
6. `/api/ops/backup` 如果超过 3 秒，也必须后台化。

### 验收标准

新增测试：

```bash
tests/backend/test_failed_endpoints_remediated.py
```

测试要求：

1. 上述 6 个端点均不返回 500。
2. GET 端点响应 < 3000ms。
3. 长任务 POST 响应 < 2000ms，并返回 task_id。
4. 所有错误响应无 traceback。
5. 所有响应统一 envelope：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "run_id": "...",
    "as_of_date": "...",
    "freshness": {},
    "lineage": {}
  }
}
```

---

## 九、P1-4：修复前端 3 个 JS 错误

### 当前问题

审计发现：

```text
/qmt     React hooks 条件调用
/events  undefined.localeCompare
/tasks   non-array .some()
```

### 修复要求

1. `/qmt`

   * 所有 React hooks 必须在组件顶层无条件调用。
   * 禁止在 if、循环、早返回之后调用 hook。

2. `/events`

   * 所有排序字段必须空值保护。
   * `localeCompare` 前必须保证是 string。

3. `/tasks`

   * API 返回值进入 `.some()` / `.map()` / `.filter()` 前必须 normalize 为数组。
   * 如果后端返回对象，要在 service 层转换，不要在页面里散落兼容逻辑。

4. 增加前端防御工具：

```bash
frontend/src/utils/normalize.ts
```

至少提供：

```ts
toArray<T>(value: unknown): T[]
safeString(value: unknown): string
```

### 验收标准

新增或修复测试：

```bash
frontend/src/**/*.test.tsx
```

并执行：

```bash
cd commands/frontend
npm run build
npx tsc --noEmit
npx vitest run
```

必须全通过。

---

## 十、P2-1：统一 API 响应、freshness、lineage、错误脱敏

### 当前问题

审计发现：

* 半数 API 缺少 `as_of_date`。
* 所有 API `lineage` 基本缺失。
* Ops 路由泄露 traceback。
* `backup.py`、`status.py`、`paper.py` 未统一 `api_response()`。

### 修复要求

1. 后端所有核心 API 统一使用：

```python
api_success()
api_error()
api_response()
```

2. 最低 meta 字段：

```json
{
  "run_id": "...",
  "as_of_date": "YYYY-MM-DD",
  "freshness": {
    "status": "ok|stale|unknown",
    "latest_data_date": "YYYY-MM-DD",
    "max_stale_days": 3
  },
  "lineage": {
    "source": "...",
    "files": [],
    "functions": [],
    "generated_at": "..."
  }
}
```

3. 生产错误响应禁止包含：

   * Python traceback
   * 本机绝对路径
   * token
   * API key
   * 环境变量值

4. traceback 只能写入本地日志：

```bash
/mnt/d/HermesReports/logs/backend_errors/
```

### 验收标准

新增测试：

```bash
tests/backend/test_api_envelope_lineage.py
tests/backend/test_no_traceback_leak.py
```

要求：

1. 核心 API 的 `meta.as_of_date` 覆盖率 >= 90%。
2. 核心 API 的 `meta.lineage` 覆盖率 >= 80%。
3. 任意错误响应不包含 `Traceback`、`.py`, `/home/`, `/mnt/`, token 字样。
4. `backup.py`、`status.py`、`paper.py` 已接入统一 envelope。

---

## 十一、P2-2：补齐 Playwright E2E

### 当前问题

审计发现：

* build、tsc、vitest 通过。
* 但没有 Playwright E2E。
* 无法防止“pytest 全绿但页面卡死”。

### 修复要求

在前端增加：

```bash
commands/frontend/playwright.config.ts
commands/frontend/tests/e2e/v5-smoke.spec.ts
```

E2E 必须覆盖 15 个页面：

```text
/
 /data
 /console
 /roadmap 或当前实际 route
 /reports
 /risk 或 livegate
 /paper
 /feedback 或 events
 /ops 或 qmt
 /history 或 tasks
 /backtest
 /factors
 /stocks
 /portfolio
 /settings
```

以实际路由为准。

每页必须检查：

1. 页面无白屏。
2. 无 console error。
3. 无 network 404/500。
4. 至少一个核心标题或 data-testid 存在。
5. 核心 API 返回后页面有非空内容。
6. 截图保存到报告目录。

### 验收命令

```bash
cd commands/frontend
npx playwright install chromium
npx playwright test
```

如果当前环境无法安装浏览器，不要跳过。必须记录为 BLOCKED，并提供本机可执行命令。

---

## 十二、P2-3：增加 V5.1 修复报告和追溯映射

修复完成后，必须生成：

```bash
/mnt/d/HermesReports/v5_1_remediation/YYYYMMDD_HHMMSS/
```

目录内容：

```text
README.md
fix_summary.md
p0_factor_api.md
p0_universe_async_cache.md
p1_data_refresh.md
p1_universe_integrity.md
p1_frontend_js.md
p1_api_failures.md
p2_observability.md
p2_e2e.md
raw/
  changed_files.json
  test_results.json
  api_smoke_after.json
  data_freshness_after.json
  factor_api_after.json
  universe_after.json
screenshots/
logs/
```

同时更新或新增 traceability：

```bash
agent_tasks/traceability/v5_1_remediation_mapping.json
agent_tasks/traceability/latest_mapping.json
```

每个修复项必须映射：

```json
{
  "requirement": "P0-1 factor API uses real registry",
  "files_changed": [],
  "tests_added": [],
  "commands_run": [],
  "evidence": [],
  "status": "PASS|FAIL|PARTIAL"
}
```

---

## 十三、最终复测命令

完成修复后，必须执行：

### 后端测试

```bash
cd /home/ly/.hermes/research-assistant/commands
python3 -m pytest tests/ -q --tb=short
```

### 前端测试

```bash
cd /home/ly/.hermes/research-assistant/commands/frontend
npm run build
npx tsc --noEmit
npx vitest run
npx playwright test
```

### API smoke

启动后端后执行：

```bash
python3 scripts/v5_api_smoke.py --base http://127.0.0.1:8766 --output /mnt/d/HermesReports/v5_1_remediation/api_smoke_after.json
```

如果脚本不存在，请创建该脚本。

必须覆盖：

```text
/api/health
/api/status
/api/factors
/api/factors/{known_factor_id}
/api/universe
/api/data/health
/api/reports
/api/reports/summary
/api/roadmap
/api/versions/report/detail
```

### 数据复测

必须创建或运行：

```bash
python3 scripts/v5_data_integrity_check.py --output /mnt/d/HermesReports/v5_1_remediation/data_integrity_after.json
```

检查：

1. K 线 freshness。
2. K 线 schema。
3. U1 过滤。
4. 市值字段非空率。
5. 因子 API 与 registry 一致性。
6. 重复文件。
7. 停牌/零成交量异常。

---

## 十四、最终 Gate 要求

修复完成后重新给出 Gate 表。

最低目标：

| Gate     | 目标                                           |
| -------- | -------------------------------------------- |
| A 架构一致性  | PASS                                         |
| B 前端可用性  | PASS                                         |
| C 后端 API | PASS                                         |
| D 真实数据   | CONDITIONAL PASS 或 PASS                      |
| E 数据正确性  | CONDITIONAL PASS，不能 FAIL                     |
| F 测试体系   | CONDITIONAL PASS，Playwright 至少可运行或明确 BLOCKED |
| G 生产可观测性 | CONDITIONAL PASS                             |

如果 E 数据正确性仍然 FAIL，则本轮修复视为失败。

---

## 十五、禁止行为

以下行为一律视为修复失败：

1. 用 mock/demo/sample/fallback 让测试通过。
2. 用硬编码 124 个因子列表代替真实 registry。
3. 用随机数填充风险归因、因子值、收益率。
4. 直接吞掉异常但不记录日志。
5. 只改前端展示，不修后端数据。
6. 只改测试断言，不修真实问题。
7. 删除审计失败项而不是修复。
8. 把长任务继续放在 HTTP 请求同步执行。
9. 将 U1 继续做成 U0 的复制。
10. 继续使用 2026-04-03 的陈旧 K 线作为可交易数据。

---

## 十六、最终回复给用户

完成后只汇报：

1. V5.1 修复总评：PASS / CONDITIONAL PASS / FAIL
2. P0/P1/P2 修复状态表
3. Gate 复测表
4. 关键证据：

   * `/api/factors` 因子数量
   * `/api/universe` 响应时间
   * K 线最新日期
   * U1 股票数、退市/ST 数、市值非空率
   * 失败 API 数量
   * 前端 JS 错误数
   * Playwright 结果
5. 报告目录
6. 仍未解决的问题和下一步建议

不要只说“修复完成”，必须给证据。
