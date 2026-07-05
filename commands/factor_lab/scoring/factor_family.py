"""因子家族分类模块 — Factor Lab

将因子注册表中的因子按照家族（family）进行分类。
家族分类用于:
- 族内/族间比较分析
- 差异化评分阈值（由 scoring_policy.yaml 驱动）
- 风险监控与报告归类

用法:
    from factor_lab.scoring.factor_family import classify_factor, get_family_config, classify_all_factors

    family = classify_factor("ret5", "momentum", "5日收益率动量")
    config = get_family_config("momentum")
    all_factors = classify_all_factors()
"""

import yaml
from pathlib import Path
from typing import Optional

# ─── 家族关键词映射 ──────────────────────────────────────────────
# 通过因子名称关键词匹配所属家族
FAMILY_KEYWORDS = {
    "momentum": ["ret", "mom", "momentum"],
    "reversal": ["reversal", "contrarian"],
    "trend": ["ma_gt_", "close_gt_ma", "ma_gap", "trend"],
    "volume_price": ["vol_ratio", "vol_price", "volume", "turnover", "amount"],
    "volatility": ["volatility", "atr", "std", "ret_std"],
    "defensive": ["defensive", "low_vol", "stability"],
    "value_quality": ["roe", "gross_margin", "debt_ratio", "quality", "pe", "pb"],
}

# ─── factor_base category → family 映射 ─────────────────────────
# 优先级高于关键词匹配
CATEGORY_FAMILY_MAP = {
    "momentum": "momentum",
    "trend": "trend",
    "volume": "volume_price",
    "volatility": "volatility",
    "reversal": "reversal",
    "liquidity": "volume_price",
    "quality": "value_quality",
    "fund_flow": "volume_price",
}

# ─── family → 中文标签 ─────────────────────────────────────────
FAMILY_LABELS = {
    "momentum": "动量",
    "reversal": "反转",
    "trend": "趋势",
    "volume_price": "量价",
    "volatility": "波动",
    "defensive": "防御",
    "value_quality": "价值质量",
    "unknown": "未知",
}


# ═══════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════

def _get_config_path() -> Path:
    """定位 scoring_policy.yaml 的绝对路径（基于当前模块位置推导）"""
    # factor_family.py 位于 commands/factor_lab/scoring/
    # YAML 位于 commands/config/
    return (
        Path(__file__).resolve().parent.parent.parent
        / "config"
        / "factor_scoring_policy.yaml"
    )


def _load_config() -> dict:
    """加载 YAML 评分政策配置，文件不存在时返回空结构"""
    config_path = _get_config_path()
    if not config_path.exists():
        return {"families": {}}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"families": {}}


# ═══════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════

def classify_factor(
    factor_name: str,
    category: str = "",
    description: str = "",
) -> dict:
    """对单个因子进行家族分类。

    分类优先级:
        1. category 非空且在 ``CATEGORY_FAMILY_MAP`` 中 → 直接映射
        2. 否则通过 ``factor_name`` 关键词匹配 ``FAMILY_KEYWORDS``
        3. 都匹配不到 → ``"unknown"``

    参数:
        factor_name: 因子名称（如 ``"ret5"``）
        category:    因子类别（来自 ``factor_base.REGISTRY`` 的 ``category`` 字段）
        description: 因子描述（暂保留供后续扩展使用）

    返回:
        ``{"family": "momentum", "label": "动量"}``
    """
    family: Optional[str] = None

    # ── 优先级 1: category 直接映射 ────────────────────────
    if category:
        lower_cat = category.strip().lower()
        if lower_cat in CATEGORY_FAMILY_MAP:
            family = CATEGORY_FAMILY_MAP[lower_cat]

    # ── 优先级 2: factor_name 关键词匹配 ──────────────────
    if family is None:
        name_lower = factor_name.lower()
        for fam, keywords in FAMILY_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in name_lower:
                    family = fam
                    break
            if family is not None:
                break

    # ── 兜底 ──────────────────────────────────────────────
    if family is None:
        family = "unknown"

    return {
        "family": family,
        "label": FAMILY_LABELS.get(family, "未知"),
    }


def get_family_config(family: str) -> dict:
    """获取指定家族的评分配置阈值。

    读取 ``factor_scoring_policy.yaml`` 中 ``families.<family>`` 节。
    如果家族不存在，返回空字典。

    参数:
        family: 家族名称（如 ``"momentum"``, ``"trend"``, ``"volume_price"``）

    返回:
        YAML 中该家族的完整配置字典，包含:
        - ``label`` / ``keywords``
        - ``max_drawdown_warn`` / ``max_drawdown_fail``
        - ``max_relative_drawdown_vs_peer``
        - ``min_excess_return_vs_peer_for_b``
        - ``min_calmar_for_b``
        - ``allow_high_beta``
        - （其他自定义项视 YAML 配置而定）
    """
    config = _load_config()
    families = config.get("families", {})
    return families.get(family, {})


def classify_all_factors() -> list:
    """遍历 ``factor_base.REGISTRY`` 对所有注册因子进行家族分类。

    返回:
        ``[
            {"name": "ret5", "category": "momentum", "family": "momentum", "label": "动量"},
            ...
        ]``
    """
    from factor_lab.factor_base import REGISTRY

    results: list[dict] = []
    for factor in REGISTRY:
        name = factor.get("name", "")
        category = factor.get("category", "")
        description = factor.get("description", "")
        classification = classify_factor(name, category, description)
        results.append({
            "name": name,
            "category": category,
            "family": classification["family"],
            "label": classification["label"],
        })
    return results


# ═══════════════════════════════════════════════════════════════
# CLI 入口 / 快速验证
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("  因子家族分类 — 快速验证")
    print("=" * 60)

    # 1. 单个因子分类测试
    test_cases = [
        ("ret5", "momentum", "5日收益率动量"),
        ("reversal20", "reversal", "中期反转"),
        ("vol_ratio20", "volume", "20日量比"),
        ("atr20", "volatility", "平均真实波幅"),
        ("dummy_factor", "", "未知因子"),
        ("amihud_illiquidity20", "liquidity", "Amihud非流动性"),
        ("roe_q", "quality", "ROE"),
    ]
    print("\n--- 单个因子分类 ---")
    for name, cat, desc in test_cases:
        result = classify_factor(name, cat, desc)
        print(f"  {name:30s} → {result['family']:15s} ({result['label']})")

    # 2. get_family_config 测试
    print("\n--- 家族配置示例 (momentum) ---")
    cfg = get_family_config("momentum")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))

    # 3. classify_all_factors 测试
    print("\n--- 全因子分类 ---")
    all_factors = classify_all_factors()
    for f in all_factors:
        print(f"  {f['name']:30s} [{f['category']:12s}] → {f['family']:15s} ({f['label']})")
    print(f"\n共 {len(all_factors)} 个因子")
