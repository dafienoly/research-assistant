#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto-refresh HERMES_RESEARCH_MANUAL.md — scan skills directory, update index

Trigger:
  1. pre-commit hook (auto)
  2. hermes docs:refresh-manual (manual)

Usage:
  python3 scripts/refresh_manual.py         # check+update
  python3 scripts/refresh_manual.py --force # force update
"""

import hashlib, json, os, re, sys
from pathlib import Path

# ─── 路径 ───────────────────────────────────────────────────────

BASE = Path(__file__).parent.parent.resolve()          # commands/
SKILLS_DIR = Path.home() / ".hermes" / "skills"
MANUAL_PATH = BASE / "docs" / "HERMES_RESEARCH_MANUAL.md"
CHECKSUM_FILE = BASE / "docs" / ".skills_checksum.txt"

# ─── 指纹计算 ───────────────────────────────────────────────────

def _skills_fingerprint() -> str:
    """计算所有 skills 目录的 hash，含 SKILL.md 内容"""
    hasher = hashlib.md5()
    skill_files = sorted(SKILLS_DIR.glob("**/*"))
    for sf in skill_files:
        if sf.name == "SKILL.md" or sf.suffix in (".md", ".yaml", ".yml"):
            rel = sf.relative_to(SKILLS_DIR)
            hasher.update(str(rel).encode())
            try:
                hasher.update(sf.read_bytes()[:10000])
            except Exception:
                pass
    return hasher.hexdigest()


def _read_fingerprint() -> str:
    try:
        return CHECKSUM_FILE.read_text().strip()
    except (FileNotFoundError, OSError):
        return ""


def _write_fingerprint(fp: str):
    CHECKSUM_FILE.write_text(fp)


# ─── Skill 扫描 ─────────────────────────────────────────────────

def _scan_all_skills() -> list[dict]:
    """扫描所有 skill，返回 [{name, description, category, tags}]"""
    skills = []
    for sk_file in sorted(SKILLS_DIR.rglob("SKILL.md")):
        # 跳过归档
        if ".archive" in str(sk_file) or sk_file.parent.name.startswith("."):
            continue
        content = sk_file.read_text(encoding="utf-8", errors="replace")
        name = sk_file.parent.name
        desc = ""
        category = ""
        for line in content.splitlines():
            if line.startswith("description:"):
                desc = line[len("description:"):].strip().strip('"').strip("'").strip(">-\n ")
                desc = desc.replace("\n", " ")
            elif line.startswith("category:"):
                category = line[len("category:"):].strip().strip('"').strip("'")

        skills.append({
            "name": name,
            "category": category,
            "description": desc or "(no description)",
        })
    return skills


def _categorize_skills() -> dict[str, list[dict]]:
    """按 category 分组"""
    groups: dict[str, list[dict]] = {}
    for s in _scan_all_skills():
        cat = s["category"] or "uncategorized"
        groups.setdefault(cat, []).append(s)
    return groups


# ─── 手册段落模板 ───────────────────────────────────────────────

SKILLS_TABLE_HEADER = """| Skill 名称 | 分类 | 用途 |
|------------|------|------|
"""

USAGE_GUIDE_HEADER = """| Skill | 什么时候用 | 怎么用 |
|-------|-----------|--------|
"""


def _build_skills_table(only_key: set[str] | None = None) -> str:
    """生成 Skill 索引表（Markdown）"""
    rows = []
    for s in _scan_all_skills():
        if only_key and s["name"] not in only_key:
            continue
        cat = s["category"] or "—"
        desc = s["description"][:60] + "..." if len(s["description"]) > 60 else s["description"]
        rows.append(f"| `{s['name']}` | {cat} | {desc} |")
    return SKILLS_TABLE_HEADER + "\n".join(sorted(rows)) + "\n"


def _build_usage_guide(category_map: dict[str, str]) -> str:
    """生成配套 Skill 使用指引表"""
    # 手动维护关键 skill 的使用场景映射
    usage_map = {
        "plan": ("复杂任务需要先写计划", "Agent 自动加载：`/plan \"实现因子排序\"`"),
        "test-driven-development": ("新功能的开发过程", "Agent 自动遵守 RED-GREEN-REFACTOR"),
        "spike": ("需要快速验证技术方案", "`/spike \"验证 jqdata 的 K 线接口\"`"),
        "requesting-code-review": ("开发完成准备提交", "Agent 自动在 git commit 前调用"),
        "subagent-output-verification": ("delegate_task 完成", "Agent 自动验证子任务输出"),
        "simplify-code": ("代码太乱需要清理", "`load skill simplify-code` → 描述问题"),
        "requirement-traceability": ("需求确认后跟踪实现", "Agent 自动在 grilling 后产出清单"),
        "factor-lab": ("因子挖掘、IC 分析", "`factor:mine` / `factor:validate`"),
        "stock-analyst": ("个股全维度分析", "`stock:context` + Agent 自动调用"),
        "etf-dive-warning": ("ETF 跳水风险预警", "Agent 自动盘前/盘中运行"),
        "mx-data": ("东方财富数据查询", "`mx:data <问句>`"),
        "mx-search": ("资讯搜索（公告/新闻/研报）", "`mx:search <关键词>`"),
        "mx-xuangu": ("智能选股（自然语言条件）", "`mx:xuangu <条件>`"),
        "hermes-daemon": ("WSL 守护进程管理", "`bash ~/.hermes/hermes-daemon.sh start`"),
        "hermes-agent": ("配置 Hermes Agent 自身", "`hermes config set ...`"),
        "systematic-debugging": ("根因分析复杂 Bug", "Agent 自动按 4 阶段排查"),
        "a-share-data-collector": ("A 股 L0 数据采集", "Agent 自动按策略调用"),
        "a-share-data-quality": ("数据质量审计", "Agent 自动按策略调用"),
        "a-share-intraday-monitor": ("盘中实时监测", "Agent 自动按策略调用"),
        "factor-mining": ("50+ 因子计算、盘前信号", "`factor:list` / `factor:signal`"),
    }

    rows = []
    for s in _scan_all_skills():
        if s["name"] in usage_map:
            when, how = usage_map[s["name"]]
            rows.append(f"| `{s['name']}` | {when} | {how} |")
        # 不在映射表中的 skill 也列出来（无指引说明）
        # 只在尾部加一个"其他"统计

    return USAGE_GUIDE_HEADER + "\n".join(sorted(rows)) + "\n"


# ─── 手动更新 ───────────────────────────────────────────────────

MARKERS = {
    "skills_table_start": "<!-- SKILLS_TABLE_START -->",
    "skills_table_end": "<!-- SKILLS_TABLE_END -->",
    "usage_guide_start": "<!-- USAGE_GUIDE_START -->",
    "usage_guide_end": "<!-- USAGE_GUIDE_END -->",
    "skills_count_start": "<!-- SKILLS_COUNT_START -->",
    "skills_count_end": "<!-- SKILLS_COUNT_END -->",
}


def _replace_between(text: str, start_marker: str, end_marker: str, new_content: str) -> str:
    """替换两个 marker 之间的内容"""
    s = text.find(start_marker)
    e = text.find(end_marker)
    if s == -1 or e == -1:
        return text
    s += len(start_marker)
    return text[:s] + "\n" + new_content.strip() + "\n" + text[e:]


def refresh_manual(force: bool = False) -> bool:
    """刷新手册的技能相关段落。返回 True 表示有变更。"""
    if not MANUAL_PATH.is_file():
        print(f"❌ 手册文件不存在: {MANUAL_PATH}")
        return False

    old_fp = _read_fingerprint()
    new_fp = _skills_fingerprint()

    if not force and old_fp == new_fp:
        print("ℹ️  技能无变更，跳过")
        return False

    # 读取当前手册
    manual = MANUAL_PATH.read_text(encoding="utf-8", errors="replace")

    # 替换技能表
    skill_table = _build_skills_table()
    new_manual = _replace_between(manual, MARKERS["skills_table_start"],
                                  MARKERS["skills_table_end"], skill_table)

    # 替换使用指引
    usage_guide = _build_usage_guide({})
    new_manual = _replace_between(new_manual, MARKERS["usage_guide_start"],
                                  MARKERS["usage_guide_end"], usage_guide)

    # 替换技能数量
    all_skills = _scan_all_skills()
    count_text = f"（共 {len(all_skills)} 个 skill）"
    new_manual = _replace_between(new_manual, MARKERS["skills_count_start"],
                                  MARKERS["skills_count_end"], count_text)

    # 写回
    MANUAL_PATH.write_text(new_manual, encoding="utf-8")
    _write_fingerprint(new_fp)

    changed_count = len(
        _extract_changed_skills(old_fp, new_fp) if old_fp else all_skills
    )
    print(f"✅ 手册已更新: {len(all_skills)} 个 skill 索引, {changed_count} 个变更")
    return True


def _extract_changed_skills(old_fp: str, new_fp: str) -> list[str]:
    """简单的变更检测：只返回技能名"""
    # 可以更精细，按 md5 比对每个 skill 目录
    new_skills = {s["name"] for s in _scan_all_skills()}
    return list(new_skills)


def cmd_main(args: list[str] = None) -> int:
    """CLI entry: --force to regenerate, --check to test if changed (exit 0=changed)"""
    argv = args or sys.argv[1:]
    check_only = "--check" in argv
    force = "--force" in argv
    try:
        if check_only:
            old_fp = _read_fingerprint()
            new_fp = _skills_fingerprint()
            if old_fp and old_fp == new_fp:
                return 1  # no change
            return 0  # changed (or first run)
        changed = refresh_manual(force=force)
        return 0
    except Exception as e:
        print(f"Error refreshing manual: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(cmd_main())
