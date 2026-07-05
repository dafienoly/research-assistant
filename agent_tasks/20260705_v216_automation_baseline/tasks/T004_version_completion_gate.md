# T004 — Version completion gate

- Version: V2.16
- Priority: P0
- Owner: ci_engineer
- Status: pending

## 目标

建立每个版本完成后的统一门禁，保证 GitHub 同步前已经完成必要验收。

## 要求

新增或完善 `leader:version-complete` 命令，执行：

1. 读取 latest_completion.json。
2. 确认 status=completed。
3. 确认 remaining_tasks=[]。
4. 运行版本相关测试。
5. 运行 leader:status。
6. 执行 leader:github-sync --version <version> --summary <summary>。
7. 输出 commit hash。

如果 status=partial/failed/blocked，不允许 github-sync 标记版本完成。

## 验收标准

- completed 状态可以通过门禁。
- partial/failed/blocked 状态会被拒绝。
- 输出 GitHub commit hash。
- 新增测试覆盖四类 status。

## 安全边界

只做代码、测试、文档、GitHub 归档，不做交易动作。
