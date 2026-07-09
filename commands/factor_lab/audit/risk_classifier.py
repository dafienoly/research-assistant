"""
Risk Classifier — 根据变更文件 + diff 模式判断风险等级

等级:
  LOW     — 文档/注释/非核心格式修改
  MEDIUM  — 新增普通模块/修改CLI/非实盘alpha
  HIGH    — 数据源/风控/交易/回测/实盘/注册表

用于 Gate 自动选择（runner.py 中决定跑哪些 gate）。
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional


# ── 高风险路径 ────────────────────────────────────────────────
HIGH_RISK_PATHS = {
    "data/providers", "execution", "risk", "portfolio",
    "backtest", "live", "paper", "broker",
}

HIGH_RISK_FILES = {
    "hermes_cli.py",
}

HIGH_RISK_REGISTRIES = {
    "CommandRegistry", "AlphaRegistry", "GateEngine",
    "ReportBuilder", "DataProviderRegistry",
}

# ── 高风险 diff 内容模式 ─────────────────────────────────────
HIGH_RISK_PATTERNS = re.compile(
    r"fallback|mock_data|demo_data|sample_data|"
    r"except\s+\w*(Exception|Error)\s*:\s*(pass|return None|return \[\])|"
    r"hardcoded.*(price|volume|amount)|"
    r"use_demo\s*=\s*True|"
    r"delete.*test|"
    r"modify.*risk|"
    r"modify.*broker|"
    r"modify.*execution",
    re.IGNORECASE,
)

# ── 低风险文件扩展名 ──────────────────────────────────────────
LOW_RISK_EXT = {".md", ".txt", ".rst", ".png", ".jpg", ".svg"}
LOW_RISK_FILES_RE = re.compile(r"(docs/|README|\.gitignore|CHANGELOG)", re.IGNORECASE)


class RiskLevel:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @staticmethod
    def all() -> list[str]:
        return [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]


def classify_risk(changed_files: list[str], diff_text: str = "") -> str:
    """判断变更风险等级。

    Args:
        changed_files: git diff 中的变更文件列表
        diff_text: git diff 文本内容（用于模式匹配）

    Returns:
        "LOW" | "MEDIUM" | "HIGH"
    """
    # 纯低风险文件 → LOW
    all_low = True
    for f in changed_files:
        ext = Path(f).suffix.lower()
        if ext not in LOW_RISK_EXT and not LOW_RISK_FILES_RE.search(f):
            all_low = False
            break
    if all_low and changed_files:
        return RiskLevel.LOW

    # 高风险路径 → HIGH
    for f in changed_files:
        for hp in HIGH_RISK_PATHS:
            if f.startswith(hp) or f"/{hp}/" in f:
                # 排除测试文件
                if "/tests/" not in f and not f.startswith("tests/"):
                    return RiskLevel.HIGH
        for hf in HIGH_RISK_FILES:
            if f == hf or f.endswith(f"/{hf}"):
                return RiskLevel.HIGH

    # 高风险 diff 模式 → HIGH
    if diff_text and HIGH_RISK_PATTERNS.search(diff_text):
        return RiskLevel.HIGH

    # 涉及注册表 → HIGH
    for f in changed_files:
        try:
            src = Path(f).read_text(encoding="utf-8", errors="replace")
            for reg in HIGH_RISK_REGISTRIES:
                if reg in src:
                    return RiskLevel.HIGH
        except (OSError, IOError):
            pass

    # 其余 → MEDIUM
    return RiskLevel.MEDIUM


def required_gates(risk: str, context: Optional[dict] = None) -> list[str]:
    """根据风险等级返回必须执行的闸门列表。

    Args:
        risk: "LOW" | "MEDIUM" | "HIGH"
        context: 可选上下文（用于进一步定制）

    Returns:
        gate 名称列表，按执行顺序
    """
    base_gates = ["gate1", "gate2", "gate3"]

    if risk == RiskLevel.LOW:
        return base_gates[:2]  # Gate 1 + Gate 2

    if risk == RiskLevel.MEDIUM:
        return base_gates + ["gate4", "gate5"]  # 全量不含 semgrep

    if risk == RiskLevel.HIGH:
        return base_gates + ["gate4", "gate5", "semgrep"]

    return base_gates
