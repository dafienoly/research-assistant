# Codex 数据包发布协议

## 概述

本文档定义 Hermes（WSL 侧）向 Codex（Windows 侧）发布数据包的标准协议。

## 发布目录

```
/mnt/c/Users/ly/.codex/data/a-share-data-hub/incoming_from_hermes/
```

Windows 对应：`C:\Users\ly\.codex\data\a-share-data-hub\incoming_from_hermes\`

## 发布流程

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  WSL data/ 生成  │ ──→ │  组装 package    │ ──→ │  原子写入 incoming   │
│  payload + hash   │     │  manifest.json    │     │  <pkg_id>/_SUCCESS   │
└──────────────────┘     └──────────────────┘     └──────────────────────┘
```

## Package 结构

```
incoming_from_hermes/
  <package_id>/
    manifest.json       -- 包描述文件（必选）
    payload/            -- 数据负载目录
      market/           -- 行情数据（可选）
      fundamentals/     -- 基本面数据（可选）
      events/           -- 事件数据（可选）
      tags/             -- 标签数据（可选）
      intraday/         -- 盘中数据（可选）
      audit/            -- 审计数据（可选）
    _SUCCESS            -- 完成标记文件（必选）
```

## Package ID 命名

```
YYYYMMDD_HHmmss_<type>
```

| type | 说明 | 频率 |
|------|------|------|
| `preopen_events` | 盘前事件 | 每日 08:30-09:20 |
| `market_snapshot` | 行情快照 | 盘中 5-10min |
| `intraday_alerts` | 盘中预警 | 事件驱动或定期 |
| `market_daily` | 收盘数据 | 每日 15:30 |
| `fundamentals_daily` | 基本面数据 | 每日 |
| `audit_report` | 审计报告 | 每日 |
| `tags_update` | 标签更新 | 按需 |

## manifest.json 规范

```json
{
  "package_id": "20260702_104230_intraday_alerts",
  "producer": "hermes",
  "env": "wsl",
  "created_at": "2026-07-02T10:42:30+08:00",
  "type": "intraday_alerts",
  "data_date": "2026-07-02",
  "files": [
    {
      "path": "intraday/codex_escalations.jsonl",
      "rows": 1,
      "sha256": "abc123..."
    }
  ],
  "freshness": {
    "status": "ok",
    "blocking": false,
    "max_delay_seconds": 30
  },
  "source_summary": [
    {
      "source": "market_snapshot",
      "status": "ok",
      "records": 80
    }
  ]
}
```

freshness.status: `ok` / `warning` / `stale`
freshness.blocking: `true` 表示数据延迟超过阈值，阻断 Codex 使用

## 原子写入保障

### 步骤

1. 在 WSL 侧完成数据生成和校验
2. 在 incoming_from_hermes 创建 `<package_id>.tmp` 目录
3. 写入所有 payload 文件
4. 计算每个文件的 sha256
5. 写入 manifest.json
6. 执行 `mv <package_id>.tmp <package_id>`（跨文件系统重命名）
7. 写入 `_SUCCESS` 文件

### 保障

- `.tmp` 前缀确保 Codex 不会读到不完整的包
- 重命名操作在 Linux 内核跨文件系统时是原子的（copy + rename）
- `_SUCCESS` 文件存在 = 包完整可消费
- Codex 只消费有 `_SUCCESS` 的包

## Codex 消费协议

Codex 侧应：

1. 定期扫描 `incoming_from_hermes/` 下所有含 `_SUCCESS` 的目录
2. 读取 `manifest.json` 验证 sha256（可选）
3. 消费后移入 `incoming_from_hermes/_processed/` 或 `_archive/`
4. 异常包（无 `_SUCCESS`、sha256 不匹配）移入 `_failed/`

## 包的校验

Hermes 侧验证：

- 所有声明在 manifest.files 中的文件确实存在
- sha256 与实际文件一致
- freshness.blocking 与实际情况一致
- `_SUCCESS` 文件存在
