"""Knowledge Base — 跨会话因子研究发现管理

三种知识类型:
  - rules:    已验证的稳定规则（必须遵守）
  - findings: 经验发现（参考）
  - failures: 已证伪路径（禁止重复）

目录结构:
  research_notes/knowledge/
  ├── INDEX.md           ← 索引
  ├── rules/             ← 规则文件
  ├── findings/          ← 发现文件
  └── failures/          ← 证伪文件

用法:
  kb = KnowledgeBase()
  kb.add_entry(kind="finding", title="VWAP Decay Reversal", ...)
  kb.search("momentum")
  kb.check_duplicate("close / ts_mean")
"""

import os, json, re, uuid
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

VALID_KINDS = ("rule", "finding", "failure")
KIND_DIRS = {"rule": "rules", "finding": "findings", "failure": "failures"}


@dataclass
class KnowledgeEntry:
    """知识条目"""
    entry_id: str = ""
    kind: str = "finding"           # rule / finding / failure
    title: str = ""
    hypothesis: str = ""            # 原始假设
    evidence: str = ""              # 证据/数据支持
    conclusion: str = ""            # 结论
    source: str = ""                # 来源（哪个研究方向）
    tags: list = field(default_factory=list)
    confidence: float = 0.5         # 置信度 0-1
    created_at: str = ""
    updated_at: str = ""
    cross_reviewed: bool = False    # 是否经过双模型验证
    cross_review_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class KnowledgeBase:
    """知识库管理系统"""

    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or os.path.join(
            os.path.dirname(__file__), "..", "research_notes", "knowledge"
        )).resolve()
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in ("rules", "findings", "failures"):
            (self.root / d).mkdir(parents=True, exist_ok=True)

    # ─── CRUD ────────────────────────────────────────────────────────

    def add_entry(self, entry: KnowledgeEntry) -> str:
        """添加知识条目。返回 entry_id。"""
        if entry.kind not in VALID_KINDS:
            raise ValueError(f"无效 kind: {entry.kind}, 可选: {VALID_KINDS}")
        if not entry.entry_id:
            entry.entry_id = f"k_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        if not entry.created_at:
            entry.created_at = datetime.now(CST).isoformat()
        entry.updated_at = datetime.now(CST).isoformat()
        self._write_entry(entry)
        self._update_index()
        return entry.entry_id

    def get_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """按 entry_id 获取知识条目"""
        for kind in VALID_KINDS:
            d = KIND_DIRS[kind]
            path = self.root / d / f"{entry_id}.json"
            if path.exists():
                return KnowledgeEntry.from_dict(json.loads(path.read_text()))
        return None

    def update_entry(self, entry: KnowledgeEntry) -> bool:
        """更新条目。返回是否成功。"""
        if not entry.entry_id:
            return False
        entry.updated_at = datetime.now(CST).isoformat()
        self._write_entry(entry)
        self._update_index()
        return True

    def delete_entry(self, entry_id: str) -> bool:
        """删除条目。返回是否成功。"""
        for kind in VALID_KINDS:
            d = KIND_DIRS[kind]
            path = self.root / d / f"{entry_id}.json"
            if path.exists():
                path.unlink()
                self._update_index()
                return True
        return False

    def list_entries(self, kind: Optional[str] = None) -> list[dict]:
        """列出条目。可选按 kind 筛选。"""
        results = []
        kinds = [kind] if kind else VALID_KINDS
        for k in kinds:
            if k not in VALID_KINDS:
                continue
            d = KIND_DIRS[k]
            for path in sorted((self.root / d).glob("*.json")):
                results.append(json.loads(path.read_text()))
        return results

    # ─── 搜索 / 查重 ────────────────────────────────────────────────

    def search(self, query: str, kind: Optional[str] = None,
               limit: int = 10) -> list[dict]:
        """全文搜索知识条目（标题 + 假设 + 证据 + 结论）。"""
        q = query.lower()
        results = []
        for entry in self.list_entries(kind):
            text = f"{entry.get('title','')} {entry.get('hypothesis','')} {entry.get('evidence','')} {entry.get('conclusion','')}".lower()
            if q in text or any(q in t.lower() for t in entry.get("tags", [])):
                results.append(entry)
        results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return results[:limit]

    def check_duplicate_hypothesis(self, hypothesis: str) -> Optional[dict]:
        """检查假设是否已存在于知识库。返回匹配条目或 None。"""
        q = hypothesis.lower().strip()
        if not q:
            return None
        for entry in self.list_entries():
            existing = entry.get("hypothesis", "").lower().strip()
            if existing == q:
                return entry
        return None

    def check_duplicate_expression(self, expression: str) -> Optional[dict]:
        """检查表达式变体是否已被实验过。"""
        norm = self._normalize_expr(expression)
        for entry in self.list_entries():
            expr = entry.get("evidence", "")
            if self._normalize_expr(expr) == norm:
                return entry
        return None

    # ─── 内部方法 ────────────────────────────────────────────────────

    def _write_entry(self, entry: KnowledgeEntry):
        d = KIND_DIRS[entry.kind]
        path = self.root / d / f"{entry.entry_id}.json"
        path.write_text(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False))

    def _normalize_expr(self, expr: str) -> str:
        return re.sub(r"\s+", "", expr.lower())

    def _update_index(self):
        """刷新 INDEX.md"""
        lines = [
            "# Knowledge Base Index\n",
            "跨会话因子研究发现资产。\n",
            "## Rules (稳定规则)\n",
        ]
        rules = [p.stem for p in (self.root / "rules").glob("*.json")]
        for eid in sorted(rules):
            entry = self.get_entry(eid)
            if entry:
                lines.append(f"- [{entry.title}] — {entry.conclusion[:80]}")
        lines.extend(["", "## Findings (经验发现)\n"])
        findings = [p.stem for p in (self.root / "findings").glob("*.json")]
        for eid in sorted(findings):
            entry = self.get_entry(eid)
            if entry:
                lines.append(f"- [{entry.title}] — {entry.conclusion[:80]}")
        lines.extend(["", "## Failures (已证伪路径)\n"])
        failures = [p.stem for p in (self.root / "failures").glob("*.json")]
        for eid in sorted(failures):
            entry = self.get_entry(eid)
            if entry:
                lines.append(f"- [{entry.title}] — {entry.conclusion[:80]}")
        (self.root / "INDEX.md").write_text("\n".join(lines) + "\n")

    # ─── 统计 ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "rules": len(list((self.root / "rules").glob("*.json"))),
            "findings": len(list((self.root / "findings").glob("*.json"))),
            "failures": len(list((self.root / "failures").glob("*.json"))),
            "total": sum(len(list((self.root / d).glob("*.json"))) for d in KIND_DIRS.values()),
        }


# ═══════════════════════════════════════════════════════
# CLI 辅助函数
# ═══════════════════════════════════════════════════════

def cmd_knowledge_list(kind: str = "") -> str:
    """知识库列表"""
    kb = KnowledgeBase()
    entries = kb.list_entries(kind if kind else None)
    if not entries:
        return "📭 知识库为空"
    lines = [f"📚 知识条目 ({len(entries)} 个):\n"]
    for e in entries:
        tag_str = f" [{', '.join(e['tags'])}]" if e.get("tags") else ""
        lines.append(f"  [{e['kind']}] {e['title']}{tag_str}")
        lines.append(f"     ID: {e['entry_id']}  |  置信度: {e.get('confidence', 0):.0%}")
        lines.append(f"     {e.get('conclusion', '')[:100]}")
        lines.append("")
    return "\n".join(lines)


def cmd_knowledge_add(kind: str, title: str, hypothesis: str,
                      conclusion: str, evidence: str = "",
                      tags: str = "", source: str = "",
                      confidence: float = 0.5) -> str:
    """添加知识条目"""
    if kind not in VALID_KINDS:
        return f"❌ 无效 kind: {kind}, 可选: {', '.join(VALID_KINDS)}"
    kb = KnowledgeBase()
    entry = KnowledgeEntry(
        kind=kind, title=title, hypothesis=hypothesis,
        conclusion=conclusion, evidence=evidence,
        tags=[t.strip() for t in tags.split(",") if t.strip()] if tags else [],
        source=source, confidence=confidence,
    )
    # 查重
    dup = kb.check_duplicate_hypothesis(hypothesis)
    if dup:
        return f"⚠️ 重复假设，已有条目:\n  [{dup['kind']}] {dup['title']} (ID: {dup['entry_id']})"
    eid = kb.add_entry(entry)
    return f"✅ 已添加: {eid}"


def cmd_knowledge_search(query: str, kind: str = "") -> str:
    """搜索知识库"""
    kb = KnowledgeBase()
    results = kb.search(query, kind if kind else None)
    if not results:
        return f"📭 未找到匹配: {query}"
    lines = [f"🔍 '{query}' 找到 {len(results)} 条:\n"]
    for r in results:
        lines.append(f"  [{r['kind']}] {r['title']}")
        lines.append(f"     ID: {r['entry_id']}  |  {r.get('conclusion', '')[:80]}")
        lines.append("")
    return "\n".join(lines)


def cmd_knowledge_stats() -> str:
    """知识库统计"""
    kb = KnowledgeBase()
    s = kb.stats()
    return f"📊 知识库统计:\n  规则 (rules):   {s['rules']}\n  发现 (findings): {s['findings']}\n  证伪 (failures): {s['failures']}\n  总计: {s['total']}" if s['total'] > 0 else "📭 知识库为空"
