# Hermes 版本完成后 GitHub 发布策略

更新时间：2026-07-05

远程仓库：`https://github.com/dafienoly/research-assistant`

## 目标

每完成一个 Hermes 版本开发任务，都自动把代码、测试、文档、工作流和任务契约上传到 GitHub，避免本地系统丢失，也方便后续做 CI/CD、回滚、审计和跨 Agent 协作。

## 仓库根目录

```text
/home/ly/.hermes/research-assistant
```

## 上传范围

应上传：

- `commands/`
- `commands/tests/`
- `docs/`
- `skills/`
- `strategies/`
- `.github/workflows/`
- `.gitignore`
- `.gitattributes`
- 重要的手工任务契约与 roadmap

不上传：

- `.venv_quant/`
- `__pycache__/`
- `.pytest_cache/`
- `logs/`
- 大型运行数据
- 实时行情缓存
- 自动生成的 `agent_tasks/auto_*`
- `latest.json`
- `latest_completion.json`
- token、secret、本地私有配置

## 新增命令

```bash
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 hermes_cli.py leader:github-sync --version V2.15.1 --summary "complete dry-run workloop"
```

预览变更：

```bash
../.venv_quant/bin/python3 hermes_cli.py leader:github-sync --version V2.15.1 --dry-run
```

## 自动工作循环接入规则

Hermes 每完成一个版本后写 `latest_completion.json`。

Leader 判断：

| completion.status | 行为 |
|---|---|
| `completed` | 先跑验收，再执行 `leader:github-sync` |
| `partial` | 不推送，继续派发剩余任务 |
| `failed` | 不推送，派发 bugfix/remediation |
| `blocked` | 不推送，停在人工确认 |

## 推荐发布门禁

每个版本推送前必须满足：

1. `pytest -q` 通过，或者至少版本相关测试通过并在 completion 中说明原因。
2. `leader:accept` 通过关键 blocker。
3. 不包含 secret/token。
4. 不包含 `.venv_quant`、运行缓存、大型行情数据。
5. `latest_completion.json.status=completed`。
6. 对于涉及 paper/live config 的版本，必须有人工确认记录。

## GitHub 提交格式

```text
chore: publish Hermes V2.15.1

<summary>
```

## 回滚策略

使用 GitHub commit hash 回滚：

```bash
git log --oneline -20
git checkout <commit>
```

正式回滚应通过新 commit 恢复，不建议长期 detached HEAD。

## 下一步增强

1. `leader:dispatch --from-latest-completion` 在 status=completed 且验收通过时自动调用 `leader:github-sync`。
2. GitHub Actions 跑 `pytest -q`。
3. 为每个版本创建 tag，例如 `hermes-v2.15.1`。
4. 生成 GitHub Release，附带本地报告路径摘要。
