#!/bin/bash
# Git pre-push hook — run one deterministic full audit.
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
    if [[ "$local_sha" != "0000000000000000000000000000000000000000" ]]; then
        echo ""
        echo "⏳ [pre-push] 运行完整代码审计..."
        echo "   环境变量 HERMES_SKIP_AUDIT=1 可跳过"
        echo ""

        if [[ "$remote_sha" == "0000000000000000000000000000000000000000" ]]; then
            BASE_REF="HEAD~1"
        else
            BASE_REF="$remote_sha"
        fi
        $VENV $CLI audit:code --profile full --scope compare --base "$BASE_REF"
        EXIT_CODE=$?

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
