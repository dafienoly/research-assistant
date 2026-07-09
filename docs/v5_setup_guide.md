# Hermes V5 首次配置引导

## 1. 前提条件

```bash
# 确认环境
python3 --version          # ≥ 3.10
node --version             # ≥ 18
npm --version              # ≥ 9
```

需要安装的 Python 依赖已存在于 `.venv_quant/`。

---

## 2. 首次启动

```bash
cd /home/ly/.hermes/research-assistant

# 第一步：启动后端 API
cd commands
../.venv_quant/bin/python3 -c "from factor_lab.api_server.main import serve; serve()"

# 第二步（新终端）：启动前端开发服务器
cd /home/ly/.hermes/research-assistant/commands/frontend
npm run dev
```

访问: http://localhost:5173

---

## 3. 一键启动脚本

```bash
cd /home/ly/.hermes/research-assistant

# 启动（开发模式）
bash scripts/start_v5.sh

# 启动（生产模式：构建前端 + 后端托管）
bash scripts/start_v5.sh --prod

# 先构建再启动开发模式
bash scripts/start_v5.sh --build
```

---

## 4. 首次配置检查清单

启动后打开浏览器，逐项确认：

- [ ] **首页** — 显示系统状态、数据健康、QMT 状态、Live Readiness
- [ ] **数据中心** — `/data` — 显示 Tushare 数据源能力和覆盖
- [ ] **股票池** — `/stocks` — U0-U4 六个 Tab 可切换
- [ ] **半导体主题** — `/semi` — 显示主题强弱和建议仓位
- [ ] **因子实验室** — `/factors` — 显示因子排行榜
- [ ] **QMT 实盘** — `/qmt` — 显示 QMT 连接状态（离线=红色提示）
- [ ] **任务中心** — `/tasks` — 显示任务列表
- [ ] **设置** — `/settings` — 显示配置表单（token 脱敏）

---

## 5. 配置环境变量（可选）

```bash
# 1. 启用 UI 认证
export HERMES_UI_TOKEN="your-secret-token"
# 前端需在 localStorage 设置 token: localStorage.setItem('token', 'your-secret-token')

# 2. 自定义 CORS
export HERMES_ALLOWED_ORIGINS="http://localhost:5173,http://localhost:8766"

# 3. 自定义报告目录
export HERMES_REPORTS_BASE="/mnt/d/HermesReports"
```

---

## 6. 关闭

```bash
# 方式一：一键脚本 stop
cd /home/ly/.hermes/research-assistant
kill $(cat /tmp/hermes_v5.pid 2>/dev/null | cut -d= -f2) 2>/dev/null

# 方式二：手动关
# 前端终端 Ctrl+C
# 后端终端 Ctrl+C

# 方式三：停止后端端口
kill $(lsof -t -i:8766) 2>/dev/null
```

---

## 7. 生产部署

```bash
cd /home/ly/.hermes/research-assistant

# 1. 构建前端
cd commands/frontend && npm run build && cd ../..

# 2. 只启动后端（自动托管前端 dist/）
cd commands
../.venv_quant/bin/python3 -c "from factor_lab.api_server.main import serve; serve()"

# 访问: http://127.0.0.1:8766
```

---

## 8. 常见配置问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 前端白屏 | 后端未启动 | 先启动后端再刷新 |
| 页面 spinner 卡死 | API 请求失败 | F12 → Console 查看错误 |
| CORS 错误 | 端口不匹配 | 检查 `HERMES_ALLOWED_ORIGINS` |
| `universes.json` 未找到 | 股票池未构建 | `python3 commands/hermes_cli.py universe:build` |
| 模块导入错误 | 路径错误 | 始终从 `commands/` 目录启动后端 |
| QMT 状态红色 | QMT Bridge 离线 | 启动 QMT 客户端 |
| `npm run dev` 端口被占 | 5173 被占用 | `lsof -ti:5173 | xargs kill` |
