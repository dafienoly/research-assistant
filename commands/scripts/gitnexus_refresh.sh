#!/bin/bash
# GitNexus 知识图谱自动更新 — 重索引 + 生成 Wiki 文档
# 用法:
#   ./gitnexus_refresh.sh                    # 增量更新索引 + wiki
#   ./gitnexus_refresh.sh --full             # 完全重建索引 + wiki
#   ./gitnexus_refresh.sh --index-only       # 只更新索引
#   ./gitnexus_refresh.sh --wiki-only        # 只生成 wiki

set -e
VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
REPO=/home/ly/.hermes/research-assistant
WIKI_TARGET=$REPO/docs/gitnexus-wiki
LOG=$HOME/.hermes/gitnexus-refresh.log

mkdir -p "$WIKI_TARGET"

echo "[$(date)] === GitNexus Refresh ===" >> "$LOG"

case "${1:-}" in
  --full)
    echo "  完全重建索引..." | tee -a "$LOG"
    cd "$REPO" && rm -rf .gitnexus && gitnexus analyze 2>&1 | tee -a "$LOG"
    ;;
  --index-only)
    echo "  增量更新索引..." | tee -a "$LOG"
    cd "$REPO" && gitnexus analyze 2>&1 | tee -a "$LOG"
    exit 0
    ;;
  --wiki-only)
    echo "  仅生成 Wiki..." | tee -a "$LOG"
    ;;
  *)
    echo "  增量更新索引+Wiki..." | tee -a "$LOG"
    cd "$REPO" && gitnexus analyze 2>&1 | tee -a "$LOG"
    ;;
esac

# 生成 Wiki 文档
echo "  生成 Wiki 文档..." | tee -a "$LOG"
cd "$REPO" && gitnexus wiki --lang chinese --provider claude --force 2>&1 | tee -a "$LOG"

# 复制到 docs/ 可见目录
echo "  同步到 docs/gitnexus-wiki/ ..." | tee -a "$LOG"
cp "$REPO/.gitnexus/wiki/INDEX_REPORT.md" "$REPO/INDEX_REPORT.md" 2>/dev/null || true
rsync -a --delete "$REPO/.gitnexus/wiki/" "$WIKI_TARGET/" 2>&1 | tee -a "$LOG"
echo "  ✅ 完成: $(ls $WIKI_TARGET/*.md 2>/dev/null | wc -l) 个文档已更新" | tee -a "$LOG"
echo "[$(date)] === Done ===" >> "$LOG"
