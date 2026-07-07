# ADR-022: 敏捷迭代工作流 — 代码审计门禁 + GitHub 自动推送

## 状态

已采纳 (2026-07-07)

## 背景

Hermes 投研系统依赖 GitHub 进行版本管理。此前代码修改后没有自动化的质量门禁，
问题需要用户端到端测试才能发现。需要建立一条「修改 → 审计 → 修复 → 提交」的
闭环流水线。

## 决策

### 架构

```
┌─ 触发源 ─────────────────────────────────────────────┐
│                                                       │
│  auto_executor 版本完成      直接代码修改 (git push)   │
│         │                            │                │
│         ▼                            ▼                │
│  ┌──────────────┐    ┌──────────────────────┐         │
│  │ advance 前插  │    │  pre-push hook       │         │
│  │ 审计门禁      │    │  (阻止推送至 GitHub)  │         │
│  └──────┬───────┘    └─────────┬────────────┘         │
│         │                      │                      │
│         └──────────┬───────────┘                      │
│                    ▼                                  │
│         ┌─────────────────────┐                       │
│         │  leader:audit-and-  │                       │
│         │  push (独立 CLI)    │                       │
│         │                     │                       │
│         │  1. 检测变更类型     │                       │
│         │  2. 选择 Phase      │                       │
│         │  3. 执行审计         │                       │
│         │  4. 生成报告 (JSON   │                       │
│         │     + Agent Console) │                       │
│         │  5. 判断通过阈值     │                       │
│         │  6. git add+commit  │                       │
│         │     + git push      │                       │
│         └─────────────────────┘                       │
│                    │                                  │
│          ┌─────────┴──────────┐                       │
│          ▼                    ▼                       │
│   审计通过             审计未通过                       │
│   git push main        标记 partial                   │
│   推进版本号            记录 FAIL 清单                  │
│                         企业微信通知                    │
│                         下个 tick Hermes 修复          │
└───────────────────────────────────────────────────────┘
```

### 触发规则

| 触发路径 | Hook | 审计失败行为 |
|----------|------|-------------|
| auto_executor 版本推进 | `advance()` 前插 audit | 标记 partial，不阻塞推进循环，下个 tick 根据报告修复 |
| 直接代码修改 (Hermes 对话 / Claude Code / 手动) | `pre-push` hook | 阻止推送，必须修复后重试 |

### 审计范围 (按变更类型)

| 变更类型 | 判断规则 | 执行 Phase |
|----------|----------|------------|
| 代码变更 | `.py` / `.jsx` / `.sh` + `commands/` 目录 | Phase 1 + 2 + 4 |
| 文档变更 | `.md` / `.txt` | Phase 1 仅基础设施 |
| 配置变更 | `.json` / `.yaml` / `.toml` | Phase 1 仅基础设施 |
| 混合变更 | 同时包含代码和文档 | 按代码变更处理 |

### 审计报告格式

```json
{
  "version": "V6.8",
  "status": "passed | failed",
  "phases_run": ["phase1", "phase2", "phase4"],
  "results": { "passed": 12, "failed": 0, "warnings": 3 },
  "fail_items": [],
  "warn_items": [
    {"type": "ARCH", "file": "auto_executor.py", "line": 81, "msg": "函数 >200 行"}
  ],
  "report_path": "/path/to/report.json"
}
```

### 通过阈值

- **可以提交/推进**: FAIL == 0 (WARN 容忍)
- **阻止提交/推进**: FAIL > 0

## 影响

正面:
- 代码质量门禁自动化，用户不再需要手动端到端测试发现问题
- 审计报告沉淀到 Agent Console，可追溯
- pre-push hook 防止有问题的代码到达 GitHub

负面:
- pre-push hook 可能因审计耗时较长（尤其首次）
- 需要处理审计超时（设置 5 分钟超时，超时则放行并通知）

## 实施计划

1. 创建 `leader:audit-and-push` CLI 命令 (复用 system-audit skill 的逻辑)
2. 在 `auto_executor.py` 的 `advance()` 前插入审计调用
3. 创建 `pre-push` hook，调用 `leader:audit-and-push --mode push-hook`
4. 创建 `pre-commit` hook（轻量检查语法 + lint）
5. 审计报告的 Agent Console 展示
6. 企业微信通知审计结果
