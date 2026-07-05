# Hermes A股投研助手 — 命令参考

## 命令体系

所有命令通过 `hermes <group>:<action>` 格式调用。

### 行情类

| 命令 | 说明 | 频率 |
|------|------|------|
| `hermes market:update-daily` | 更新全 A 日 K 数据 | 每日盘后 |
| `hermes market:update-live-snapshot` | 更新全 A 实时快照 | 盘中 5-10min |
| `hermes market:update-priority-minute` | 更新重点池分钟线 | 盘中 30-60s |

### 基本面类

| 命令 | 说明 |
|------|------|
| `hermes fundamentals:update` | 更新全部基本面数据 |
| `hermes announcements:parse` | 解析最新公告 |
| `hermes policy:update-events` | 更新政策与行业事件 |
| `hermes tags:update` | 更新产业链/主题标签 |

### 数据质量类

| 命令 | 说明 |
|------|------|
| `hermes data:freshness-check` | 检查所有数据新鲜度 |
| `hermes data:gap-report` | 生成数据缺口报告 |

### 盘中监测类

| 命令 | 说明 |
|------|------|
| `hermes intraday:prepare` | 初始化盘中状态（读取 positions 等） |
| `hermes intraday:check-once` | 单次盘中检查（调试用） |
| `hermes intraday:watch` | 盘中循环监测 |
| `hermes intraday:publish-alerts` | 发布当前预警包到 incoming |
| `hermes intraday:stop` | 停止循环监测 |

### 企业微信类

| 命令 | 说明 |
|------|------|
| `hermes wechat:test` | 测试 webhook 连通性 |
| `hermes wechat:send-digest` | 发送累积摘要 |

### 发布类

| 命令 | 说明 |
|------|------|
| `hermes package:publish-preopen` | 发布盘前事件包 |
| `hermes package:publish-market` | 发布行情数据包 |
| `hermes package:publish-intraday-alerts` | 发布盘中预警包 |
| `hermes package:publish-all` | 发布所有待发数据 |

## 执行规则

- 所有命令在 WSL 内部 `~/.hermes/research-assistant/` 环境执行
- 发布类命令最终写入 `/mnt/c/Users/ly/.codex/data/a-share-data-hub/incoming_from_hermes/`
- 盘中监测命令支持 `--dry-run` 参数用于调试
- 所有命令通过 Hermes 工具链执行（terminal/execute_code），不依赖外部 shell 脚本

## 盘中 SOP 自动流程

详见 `docs/daily-research-sop.md`
