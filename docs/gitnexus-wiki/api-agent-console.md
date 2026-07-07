# API & Agent Console

# API 与 Agent Console 模块

## 概述

本模块为 Hermes 投研系统提供三层 API 接口：

- **Agent Console** — 面向用户的 Agent 交互控制台，支持多种后端 Agent（Hermes 演示/研究模式、Claude Code），通过 SSE 流式推送回答
- **API Server** — 基于 FastAPI 的统一 REST 入口，聚合系统状态、路线图、备份、数据源健康等子模块
- **MCP Server** — 为 LLM Agent 提供 13 个标准化工具（因子验证、回测、知识库等），支持 HTTP 与 stdio 两种协议

三者共享文件级会话存储，形成一个"前端 SPA → API 路由 → 文件存储/子进程调度"的分层架构。

---

## 架构总览

```mermaid
graph TB
    subgraph 用户层
        SPA["SPA 控制台 (agent_console/server.py)"]
        AGENT["外部 Agent (Claude Code / Codex)"]
    end

    subgraph API层
        FASTAPI["FastAPI (api_server/main.py)"]
        CONSOLE["routes_console.py"]
        STATUS["routes_status.py"]
        ROADMAP["routes_roadmap.py"]
        BACKUP["routes_backup.py"]
        DATA["routes_data.py"]
        MCP["MCP HTTP (mcp_server.py)"]
    end

    subgraph 引擎层
        ADAPTERS["Adapters (agent_console/adapters.py)"]
        SESSIONS["Session 管理 (sessions.py)"]
        MCP_STDIO["MCP stdio (mcp_server.py)"]
    end

    subgraph 存储层
        DIR["~/.hermes/...agent_console_sessions["/agent_console_sessions/"]"]
        BACKUP_DIR["/mnt/d/HermesReports/session_backups/"]
    end

    SPA --> FASTAPI
    AGENT --> MCP
    FASTAPI --> CONSOLE & STATUS & ROADMAP & BACKUP & DATA
    CONSOLE --> ADAPTERS
    CONSOLE --> SESSIONS
    ADAPTERS --> SESSIONS
    SESSIONS --> DIR
    SESSIONS --> BACKUP_DIR
    MCP --> MCP_STDIO
```

**关键设计决策：**

- **文件即数据库** — 每个 session 是一个目录，事件以 JSONL append-only 写入，回答以 Markdown 累积。零依赖、可 grep、可手动修复
- **流式 vs 缓冲** — 前端使用 SSE 接收事件；后端Adapter按各自能力决定是否逐 token 推送。当前三种 Adapter 均为缓冲模式
- **守护进程生命周期** — 每个 session 创建时写入 `lifecycle.json`（含 PID），进程退出时 `atexit` 将所有 running session 标记为 orphaned，防止幽灵任务

---

## 核心模块详解

### 1. Agent Console Sessions (`sessions.py`)

会话是 Console 的基本工作单元。创建流程：

```
create_session(agent, prompt) → sid
  ├── 生成唯一 ID: ac_YYYYMMDD_HHMMSS_xxxxxx
  ├── 创建目录: SESSIONS_DIR / sid/
  ├── 写入 request.json（agent, prompt, version, created_at）
  └── 返回 sid
```

每个 session 目录内容：

| 文件 | 用途 |
|------|------|
| `request.json` | 创建时写入的请求快照 |
| `events.jsonl` | 所有事件 append-only 日志（JSONL 格式） |
| `answer.md` | answer_delta 事件的累积正文 |
| `summary.json` | 最终状态、更新时间和元信息 |
| `lifecycle.json` | 守护线程 PID 与状态（用于 orphan 检测） |

**关键函数：**

```python
def append_event(sid, event: AgentEvent) -> None
```
向 `events.jsonl` 追加一行，同时若事件类型为 `answer_delta` 则追加到 `answer.md`

```python
def get_session(sid) -> dict
```
聚合 request、summary、events（倒序最近 200 条）、answer、diagnostics（最近 50 条）、duration 计算、git commit 快照

```python
def cleanup_sessions(days=30) -> int
```
删除超过 N 天未更新的 session 目录

**Orphan 检测机制：**

```python
@atexit.register
def _mark_orphaned_sessions()
```
进程退出前扫描所有带 `lifecycle.json` 且 `status == "running"` 的 session，将其标记为 `orphaned`。前端通过 `status-orphaned` 样式展示，运维人员可手动清理。

---

### 2. Agent Adapters (`adapters.py`)

Adapter 模式隔离了不同 Agent 后端的实现差异。每个 Adapter 声明自己的元信息：

```python
ADAPTER_INFO = {
    "hermes_demo": {
        "label": "Hermes Agent (演示模式)",
        "streaming": "buffered",    # 当前仅支持缓冲模式
        "description": "运行 leader:dispatch --dry-run，用于验证链路",
    },
    "hermes_research": {
        "label": "Hermes Agent (研究模式)",
        "streaming": "buffered",
        "description": "运行 leader:automation-status + roadmap-status",
    },
    "claude_code": {
        "label": "Claude Code (--print)",
        "streaming": "buffered",
        "description": "Claude Code --print 模式，回答缓冲后一次性输出",
    },
}
```

调度入口：

```python
def start_session(sid, agent, prompt):
    # 根据 agent 类型分发到具体实现
    {"hermes_demo": _run_hermes_demo,
     "hermes_research": _run_hermes_research,
     "claude_code": _run_claude}[agent](sid, prompt)
```

**Hermes 研究模式**的运行逻辑：

```
_run_hermes_research
  ├── 发送 answer_delta（任务描述）
  ├── 并行执行多条 Hermes CLI 命令（automation-status + roadmap-status）
  │   ├── stdout → answer_delta（chunkify 分片发送）
  │   └── stderr → diagnostic
  ├── 聚合所有输出
  └── 标记完成/失败
```

**Claude Code Adapter 的特殊处理：**

首先尝试 PTY 模式（实验性）以实现准实时流：

```
PTY 模式流程:
  pty.openpty() → subprocess.Popen(claude --print, stdout=slave_fd)
  → select.select 轮询 → os.read 读取 → _strip_ansi 清洗 → answer_delta
  → 超时 300s 自动 kill
```

PTY 失败时回退到 buffered `subprocess.run` 模式，等待命令完全结束后一次性输出。

辅助函数 `_strip_ansi()` 使用正则移除 ANSI 转义序列（`\x1B[...m` 等），确保终端控制字符不会污染回答正文。

---

### 3. 数据模型 (`schemas.py`)

两个核心 dataclass：

```python
@dataclass
class AgentEvent:
    type: str        # answer_delta | diagnostic | error | status | done
    session_id: str
    data: str        # 正文或诊断文本
    status: str      # running | completed | cancelled | failed
    timestamp: str   # 自动填充 CST 时区

    def to_sse(self) -> str   → SSE 格式序列化（data 截断 2000 字符）
    def to_dict(self) -> dict → JSON 序列化

@dataclass
class SessionState:
    session_id: str
    status: str      # pending → running → completed/cancelled/failed
    answer_md: str
    diagnostics: list
```

`AgentEvent.to_sse()` 的输出格式：

```
event: answer_delta
data: {"type":"answer_delta","session_id":"ac_20260707_120714_abc123","data":"## 分析结果...","status":"running"}

```

---

### 4. Console HTML 页面 (`server.py`)

`CONSOLE_HTML` 是一个自包含的暗色主题 SPA，通过原生 JavaScript 与 API 交互。结构：

```
侧边栏 (260px)            主区域
┌──────────────────┐  ┌──────────────────────────────┐
│  会话历史列表       │  │  Agent 选择器 + 开始/取消按钮  │
│  ──────────────   │  │  ├─ agentSelect (select)     │
│  ◉ Hermes 研究    │  │  ├─ startBtn / cancelBtn    │
│  ○ Claude Code   │  │  └─ sessionStatus (badge)    │
│  ○ Hermes 演示    │  │                              │
│                   │  │  提示词输入框 (textarea)       │
│  过滤: Agent       │  │                              │
│       状态         │  │  回答区 (answerArea)          │
│       版本         │  │  (白色衬底, 等宽字体)          │
│                   │  │                              │
│                   │  │  诊断面板 (toggle 展开)         │
└──────────────────┘  └──────────────────────────────┘
```

**关键交互逻辑：**

```javascript
function startSession()
  → POST /api/agent-console/sessions  (agent + prompt)
  → 返回 session_id → connectSSE(sid)
  → EventSource 监听 message 事件:
      answer_delta → 追加到 answerArea
      diagnostic  → 追加到 diagnosticArea
      error       → 红色标记
      done        → 更新状态, 关闭 SSE, 刷新会话列表

function cancelSession()
  → POST /api/agent-console/sessions/{sid}/cancel
  → 标记 cancelled, 释放按钮

loadSessions()  // 每 15 秒自动轮询
  → GET /api/agent-console/sessions-list?agent=&status=&version=
  → 渲染侧边栏列表
  → 支持过滤和版本筛选
```

---

### 5. API 路由层

快速参考所有路由端点：

| 前缀 | 端点 | 方法 | 用途 |
|------|------|------|------|
| `/api` | `/agent-console/adapters` | GET | 列出可用 Adapter |
| | `/agent-console/sessions` | POST | 创建新 session 并启动 |
| | `/agent-console/sessions` | GET | 列出所有 session（带过滤） |
| | `/agent-console/sessions/{sid}` | GET | 获取单个 session 详情 |
| | `/agent-console/sessions/{sid}/stream` | GET | SSE 事件流 |
| | `/agent-console/sessions/{sid}/cancel` | POST | 取消运行中的 session |
| | `/agent-console/sessions/{sid}/backup` | POST | 备份到 HermesReports |
| | `/agent-console/backups` | GET | 列出备份 |
| | `/agent-console/backups/{id}/restore` | POST | 从备份恢复 |
| | `/agent-console/cleanup` | POST | 清理过期 session |
| | `/versions/report` | GET | 版本报告 |
| | `/versions/report/detail` | GET | 详细版本报告含 Agent 输出 |
| `/api` | `/status` | GET | 聚合状态（健康、光标、路线图、后端策略、版本报告） |
| | `/agent-output` | GET | 最近 Agent 输出快照 |
| `/api` | `/roadmap` | GET | 路线图详情 |
| | `/roadmap/versions` | GET | 版本列表与光标 |
| | `/roadmap/versions/mark` | POST | 标记版本状态 |
| `/api` | `/backups` | GET/POST | 备份列表/创建 |
| | `/backups/{id}/recover` | POST | 恢复备份 |
| | `/auto-run` | POST | 触发自动执行 |
| `/api` | `/data/overview` | GET | 数据状态概览（卡片摘要） |
| | `/data/providers` | GET | 数据源健康详情 |
| | `/data/freshness` | GET | 数据文件新鲜度 |
| | `/data/gaps` | GET | 数据缺口报告 |
| | `/data/fetch-log` | GET | 拉取日志 |

**SSE 流的实现**（`routes_console.py`）：

```python
@router.get("/agent-console/sessions/{sid}/stream")
async def stream_session(sid: str):
    async def event_gen():
        last_count = 0
        while True:
            el = SESSIONS_DIR / sid / "events.jsonl"
            if el.exists():
                lines = el.read_text().splitlines()
                for line in lines[last_count:]:
                    yield f"data: {line}\n\n"
                    last_count += 1
                if lines and '"done"' in lines[-1]:
                    break
            await asyncio.sleep(0.3)
    return StreamingResponse(event_gen(), media_type="text/event-stream")
```

轮询式 SSE：每 300ms 检查 `events.jsonl` 的新行。检测到 `done` 事件后终止连接。这种设计简化了跨进程通信（Adapter 在子线程写入文件，主线程 Serve 轮询读取），避免了复杂的管道管理。

---

### 6. MCP Server (`mcp_server.py`)

提供两种运行模式：

**HTTP 模式（默认，端口 8767）：**
```bash
python3 commands/factor_lab/mcp_server.py
# 或指定端口
python3 commands/factor_lab/mcp_server.py --port 8767
```

暴露 `POST /tools/{tool_name}` 端点，请求体自动解析 Pydantic 模型。同时提供 `GET /tools` 列出所有工具、`GET /health` 健康检查。

**MCP stdio 模式：**
```bash
python3 commands/factor_lab/mcp_server.py --stdio
```
需要安装 `mcp` 包。使用 FastMCP 注册工具，通过标准输入输出与 MCP 客户端通信。

工具清单及其内部依赖：

| 工具名 | 内部依赖 | 用途 |
|--------|----------|------|
| `list_operators` | `expression_parser.FUNC_REGISTRY` | 列出所有可用表达式算子 |
| `list_universes` | `strategy_lab.universe.list_universes` | 列出股票池 |
| `validate_expression` | `ExpressionParser.validate` | 表达式语法校验 |
| `run_backtest` | 回测管线 | 全流程回测 |
| `score_factor` | `validate_factor.run_validation` | 复合评分（含反过拟合和 Walk-Forward） |
| `diagnose_factor` | `research_loop.mutation.MutationEngine` | 诊断因子失败原因并生成突变策略 |
| `run_anti_overfit` | `validation.anti_overfit.run_anti_overfit` | 反过拟合检验（IC稳定性 + 安慰剂 + 压力测试） |
| `run_walk_forward` | Walk-Forward 模块 | Walk-Forward 验证 |
| `run_adversarial` | 对抗性验证 | 对抗性验证 |
| `batch_evaluate` | 批处理引擎 | 并发批处理回测 |
| `knowledge_search` | `KnowledgeBase.search` | 知识库搜索 |
| `knowledge_add` | `KnowledgeBase.add_entry` | 知识库写入（含重复假设检测） |
| `research_loop` | 研究循环 | 启动研究循环 |

**跨社区执行流示例** — 一次 `score_factor` 调用的完整链路：

```
api_score_factor
  → tool_score_factor
    → run_validation (validate_factor.py)
      → run_anti_overfit (anti_overfit.py)
        → run_stress_test
          → _calc_subsample_metrics → _max_drawdown
          → _regime_split
        → list_factors (factor_base.py)
          → _load_evolved → _make_func
```

---

### 7. 数据状态路由 (`routes_data.py`)

V7.1 新增的数据状态模块，核心原则是**不静默 fallback**。提供四个端点：

- `/data/overview` — 聚合卡片摘要，统计 active/degraded/inactive/unchecked 数据源数量，新鲜度状态，缺口数量
- `/data/providers` — 每个数据源的成功率、延迟、近期错误
- `/data/freshness` — 委托 `data_quality.FreshnessChecker` 检查文件时效
- `/data/gaps` — 委托 `data_quality.DataGapReporter` 报告数据缺口
- `/data/fetch-log` — 从 JSONL 审计日志读取最近拉取记录

健康数据来源优先级：先尝试 `HealthTracker.check_health()` 获取详细报告，失败时回退到 spec 上的 `health` 摘要字段。

---

## 生命周期与错误处理

### Session 状态机

```
pending ──→ running ──→ completed
                  ├──→ failed
                  ├──→ cancelled
                  └──→ orphaned (进程意外退出)
```

### 错误处理策略

| 层次 | 策略 |
|------|------|
| API 路由 | FastAPI 异常处理 → 400/404/500 JSON 响应 |
| Adapter 子线程 | try/except 捕获 → error 事件写入 events.jsonl → 标记 failed |
| PTY 驱动 | 300s 超时 kill + OSError/ValueError fallback 到缓冲模式 |
| CLI 命令失败 | Hermes 研究模式记录 failed_commands 列表，仍返回部分结果 |
| MCP Server | HTTP 模式的错误直接返回 `{"error": str(e)}`；stdio 模式通过 stderr 输出 |
| Orphan 检测 | `atexit` 注册函数，进程退出前标记所有 running session |

### 备份与恢复

备份路径映射：`agent_console_sessions/{sid} → /mnt/d/HermesReports/session_backups/{sid}`

```python
def restore_backup(backup_id) -> dict
  └── 复制 BACKUP_DIR/{id} → SESSIONS_DIR/{id}（覆盖已存在的目标）
```

备份通过 `routes_backup.py` 中的 `auto_backup()` 也覆盖路线图数据，两个备份系统共享同一 `list_backups`/`recover` 接口。

---

## 配置与依赖

| 配置项 | 位置 | 默认值 |
|--------|------|--------|
| `VENV_PYTHON` | `config.VENV_PYTHON` | 虚拟环境 Python 路径 |
| `SESSIONS_DIR` | `sessions.py` | `~/.hermes/research-assistant/agent_tasks/agent_console_sessions/` |
| `BACKUP_DIR` | `sessions.py` | `/mnt/d/HermesReports/session_backups/` |
| `COMMANDS` | `adapters.py` | `~/.hermes/research-assistant/commands` |
| `CLI` | `adapters.py` | 基于 VENV 推导的 `hermes_cli.py` 路径 |
| `HERMES_CLAUDE_BIN` | 环境变量 | `~/.nvm/versions/node/v22.16.0/bin/claude` |

---

## 测试覆盖

测试文件 `tests/test_agent_console_v7_2.py` 覆盖：

- Session 创建、加载、不存在处理
- answer_delta 的多 chunk 和多行场景
- Diagnostic 事件存储与行数限制（最多 50 条）
- 取消流程（端点 + 已完成的会话取消 + 不存在会话取消）
- SSE 流式事件顺序
- Adapter 元信息声明

测试模式：使用 `_fake_session()` 辅助函数创建临时 session 目录，`tmp_path` fixture 确保隔离。