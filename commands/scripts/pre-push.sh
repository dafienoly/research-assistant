#!/bin/bash
# Git pre-push hook — 推送前执行代码审计门禁 (ADR-022)
# 审计未通过则阻止推送。使用 --skip-audit 绕过（通过环境变量）
#
# 安装: ln -sf ../../scripts/pre-push.sh .git/hooks/pre-push
#       或者直接复制为 .git/hooks/pre-push

if [ "$HERMES_SKIP_AUDIT" = "1" ]; then
    exit 0
fi

VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
CLI=/home/ly/.hermes/research-assistant/commands/hermes_cli.py

# 获取本次推送的分支
while read local_ref local_sha remote_ref remote_sha; do
    # 只拦截推送到 main 的请求
    if [[ "$remote_ref" == "refs/heads/main" ]]; then
        echo ""
        echo "⏳ [pre-push] 运行代码审计 (ADR-022)..."
        echo "   环境变量 HERMES_SKIP_AUDIT=1 可跳过"
        echo ""

        $VENV $CLI leader:audit-and-push --mode push-hook
        EXIT_CODE=$?

        if [ $EXIT_CODE -eq 0 ]; then
            echo ""
            echo "⏳ [pre-push] 运行反偷工减料审计 (4闸门)..."
            timeout 60 $VENV $CLI leader:anti-cheat-audit --skip gate4
            EXIT_CODE=$?
        fi

        if [ $EXIT_CODE -ne 0 ]; then
            echo ""
            echo "❌ [pre-push] 审计未通过，推送已阻止"
            echo "   修复后重新 git push"
            echo "   紧急跳过: HERMES_SKIP_AUDIT=1 git push"
            exit 1
        fi

        echo ""
        echo "✅ [pre-push] 审计通过"
    fi
done

exit 0
