> **2026-07-12 operational override:** GitNexus indexing, anti-cheat auto-audit, and commit/push audit hooks are retired. Do not run them during ordinary development. Use `commands/scripts/major_code_audit.sh <version> [base]` only for an explicitly approved major release; it is source-only and excludes data/temp/generated trees.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **research-assistant** (19322 symbols, 36352 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Historical GitNexus guidance (disabled by the operational override above)

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/research-assistant/context` | Codebase overview, check index freshness |
| `gitnexus://repo/research-assistant/clusters` | All functional areas |
| `gitnexus://repo/research-assistant/processes` | All execution flows |
| `gitnexus://repo/research-assistant/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Historical Auto-Audit guidance (disabled)

The former Hermes plugin (`anti-cheat-auto-audit`) is retired and must not run
after `write_file` / `patch` on `.py` files in this project.

### 自动触发
- **Historical trigger (disabled):** any `.py` file write in this project (3-second debounce
  batches multi-file changes into one audit)
- **Historical command (disabled):** `leader:anti-cheat-audit --skip gate4 --enable-gate5` as background
  subprocess (Gates 1-3 + Gate 5 LLM review)
- **Historical behavior (disabled):** When the audit found problems, the plugin injected
  a ⚠️  notice into the next LLM user message via the `pre_llm_call` hook.
  The agent sees the findings and can proactively fix them — no manual
  check needed.
- **pre-push hook** is intentionally a no-op.

### Historical Gate 5 — LLM 审查 + 映射验证 (retired)

Gate 5 能检测"没有按需求执行"的问题，但依赖 agent 产出映射表：

历史流程曾要求多步需求写入 traceability mapping；当前 release-only source audit 不执行 Gate 5，mapping 仅作为项目文档保留：
```
agent_tasks/traceability/latest_mapping.json
```

格式：
```json
{
  "requirements": [
    {
      "id": "R1",
      "title": "从腾讯 API 获取实时价格",
      "code_locations": [
        {"file": "commands/factor_lab/market/tencent.py",
         "function": "fetch_realtime_price",
         "line": 42}
      ],
      "expected_keywords": ["qt.gtimg.cn", "requests.get"],
      "behavior": "HTTP GET → Tencent stock API → parse JSON"
    }
  ]
}
```

Gate 5 会：
1. **C — 映射验证**: 检查每个 `code_location` 的文件/函数是否存在、关键词是否出现
2. **A — LLM 审查**: 把需求描述 + git diff 发给 LLM，判断代码是否真实实现需求

不写 mapping 文件的话，Gate 5 仍然会跑 LLM 自由审查（只看 diff + plan），
但效果不如有 mapping 时好。

## Frontend Self-Verify Gate（前端强制自验证）

**触发条件：** 任何前端代码修改（新建/修改页面、组件、路由、API 数据消费层）

**必须做：**

1. **加载 skill** — 工作前先 `skill_view(name='frontend-self-verify')` 获取完整的 6 步验证流程
2. **启动 dev server** — `npm run dev -- --host 0.0.0.0`，确认 `curl http://localhost:5173` 返回 200
3. **逐个路由验证** — 对每个受影响页面（新增/修改/相邻页面）：
   - 导航到页面 → 检查 `#root.children` > 0（非白屏）
   - 检查 `browser_console()` — 过滤 antd 弃用警告后无致命 JS 错误
   - 检查数据渲染 — 表格行数 > 0，无"加载中"/"暂无数据"死态
   - 检查交互元素 — 点击/切换后无新错误
   - 对照需求关键词 — 用 `browser_console(expression=...)` 检查关键文本是否存在
4. **生成结构化验证报告** — 每检查一个路由一行，明确标注 ✅ PASS / ⚠️ WARN / ❌ FAIL
5. **FAIL 阻塞** — 任何 ❌ 不得宣称完成，必须先修复

**禁止宣称完成而不提供浏览器证据。** "应该没问题""代码看起来正常"等措辞在 AGENTS.md 层级被禁止。必须给出类似这样的报告：

```
## Frontend Self-Verify 报告
| 路由 | 白屏 | JS错误 | 数据渲染 | 交互 | 需求对照 | 结论 |
|------|------|--------|----------|------|----------|------|
| /data | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| /new-report | ✅ | ✅ | ⚠️ 行数0 | N/A | ❌ 缺关键词 | FAIL |
```

相关参考文件：`quality/frontend-self-verify/SKILL.md`, `references/agent-workflow-examples.md`
