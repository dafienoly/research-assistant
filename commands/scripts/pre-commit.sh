#!/bin/bash
# Git pre-commit hook — 轻量语法检查 (ADR-022)
# 在 commit 前检查 Python 语法 + 基础 lint，不通过则阻止提交
#
# 安装: ln -sf ../../scripts/pre-commit.sh .git/hooks/pre-commit
#       或者直接复制为 .git/hooks/pre-commit

VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3

# 只检查暂存的 .py 文件
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')

if [ -z "$STAGED_PY" ]; then
    exit 0
fi

HAS_ERROR=0

for pyfile in $STAGED_PY; do
    if [ ! -f "$pyfile" ]; then
        continue
    fi

    # Python 语法检查
    $VENV -m py_compile "$pyfile" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "❌ [pre-commit] 语法错误: $pyfile"
        $VENV -m py_compile "$pyfile"
        HAS_ERROR=1
        continue
    fi

    # 基础风格检查：tab vs 空格混用
    grep -Pn "^\t+ " "$pyfile" >/dev/null 2>&1 || grep -Pn "^ +\t" "$pyfile" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "⚠️  [pre-commit] 缩进混用 (tab+空格): $pyfile"
        # 不因此阻止 commit，仅警告
    fi
done

if [ $HAS_ERROR -ne 0 ]; then
    echo "❌ [pre-commit] 语法检查未通过，提交已阻止"
    echo "   修复后重新 git add + git commit"
    exit 1
fi

# 检查技能有变更 → 刷新手册
SCRIPT=/home/ly/.hermes/research-assistant/commands/scripts/refresh_manual.py
if [ -f "$SCRIPT" ]; then
    $VENV $SCRIPT --check >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        # 有变更，执行刷新并提示
        $VENV $SCRIPT --force >/dev/null 2>&1 && \
            echo "📖 [pre-commit] 技能索引已同步到 docs/HERMES_RESEARCH_MANUAL.md"
    fi
fi

exit 0
