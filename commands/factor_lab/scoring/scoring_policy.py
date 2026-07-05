"""评分政策加载器 — 从 YAML 加载/合并评分政策配置

提供:
  - load_policy:           加载 YAML 配置, 合并 global 默认值和 families 配置
  - get_family_thresholds: 获取某家族的评分阈值
  - get_weights:           获取某家族的评分权重 (已归一化)
  - evaluate_risk:         评估回撤与风险, 使用家族特定的阈值判断
"""

from pathlib import Path
from typing import Optional

import yaml


# ─── 路径解析 ───────────────────────────────────────────────────────


def _default_policy_path() -> Path:
    """从本文件位置向上解析到 config/factor_scoring_policy.yaml"""
    return (
        Path(__file__).resolve().parent.parent.parent
        / "config"
        / "factor_scoring_policy.yaml"
    )


# ─── 1. load_policy ─────────────────────────────────────────────────


def load_policy(path: Optional[str] = None) -> dict:
    """加载 YAML 配置, 合并 global 默认值和 families 配置.

    Args:
        path: YAML 文件路径, 默认自动查找
              ``config/factor_scoring_policy.yaml``

    Returns:
        dict with keys:

        - **global**: 原始 global 段
        - **default_weights**: 基础评分权重
        - **families**: 每个家族配置已合并 global 默认值
          (不包含 ``default_weights``, 该字段单独在顶层)
    """
    if path is None:
        path = str(_default_policy_path())

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"评分政策配置未找到: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    global_config = raw.get("global", {})
    default_weights = global_config.get("default_weights", {})
    families_raw = raw.get("families", {})

    # 合并 global 默认值到每个家族（家族值优先）
    families = {}
    for fam_name, fam_cfg in families_raw.items():
        merged = dict(global_config)
        merged.pop("default_weights", None)  # 权重单独管理
        merged.update(fam_cfg)  # 家族覆盖
        families[fam_name] = merged

    # 确保 unknown 兜底家族存在
    if "unknown" not in families:
        families["unknown"] = dict(global_config)
        families["unknown"].pop("default_weights", None)
        families["unknown"].setdefault("max_grade", "B")

    return {
        "global": global_config,
        "default_weights": default_weights,
        "families": families,
    }


# ─── 阈值 key 清单 ──────────────────────────────────────────────────

_THRESHOLD_KEYS = [
    "max_drawdown_warn",
    "max_drawdown_fail",
    "max_relative_drawdown_vs_peer",
    "min_excess_return_vs_peer_for_b",
    "min_calmar_for_b",
    "allow_high_beta",
    "risk_control_weight",
    "peer_excess_weight",
    "max_grade",
]

# ─── 2. get_family_thresholds ───────────────────────────────────────


def get_family_thresholds(family: str, policy: dict) -> dict:
    """返回某家族的阈值配置.

    Args:
        family: 家族名称 (如 ``momentum``, ``reversal``)
        policy: ``load_policy`` 返回的完整配置

    Returns:
        包含 ``_THRESHOLD_KEYS`` 各项的 dict.
        若家族未定义, 使用 ``unknown`` 的配置；
        ``max_grade`` 默认为 ``"A"`` (无限制).
    """
    families = policy.get("families", {})
    fam = families.get(family) or families.get("unknown", {})

    result = {}
    for key in _THRESHOLD_KEYS:
        result[key] = fam.get(key)

    if result["max_grade"] is None:
        result["max_grade"] = "A"

    return result


# ─── 3. get_weights ─────────────────────────────────────────────────


def get_weights(family: str, policy: dict) -> dict:
    """返回某家族的评分权重, 归一化使总和为 1.0.

    权重来源:
      1. 以 ``default_weights`` 为基础
      2. 若家族定义了 ``risk_control_weight``, 覆写 ``risk_control``
      3. 若家族定义了 ``peer_excess_weight``, 覆写 ``peer_excess``
      4. 归一化至总和 1.0

    Returns:
        ``{ic_stability, monotonicity, peer_excess, risk_control, walk_forward, simplicity}``
    """
    weights = dict(policy.get("default_weights", {}))

    families = policy.get("families", {})
    fam = families.get(family)
    if fam:
        rc = fam.get("risk_control_weight")
        if rc is not None:
            weights["risk_control"] = rc
        pe = fam.get("peer_excess_weight")
        if pe is not None:
            weights["peer_excess"] = pe

    # 归一化
    total = sum(weights.values())
    if total > 0 and abs(total - 1.0) > 1e-9:
        for k in weights:
            weights[k] = weights[k] / total

    return weights


# ─── 4. evaluate_risk ───────────────────────────────────────────────

_VERDICT_ORDER = {"pass": 0, "warn": 1, "fail": 2}


def _worse_verdict(a: str, b: str) -> str:
    return a if _VERDICT_ORDER.get(a, 0) >= _VERDICT_ORDER.get(b, 0) else b


def evaluate_risk(
    family: str,
    strategy_max_dd: float,
    peer_max_dd: float,
    excess_return: float,
    sharpe: float,
    calmar: float,
    beta_vs_hs300: float,
    policy: dict,
) -> dict:
    """评估回撤与风险, 使用家族特定的阈值判断.

    Args:
        family: 家族名称
        strategy_max_dd: 策略最大回撤 (**负值**, 如 ``-0.25``)
        peer_max_dd: 同池等权最大回撤 (**负值**)
        excess_return: 超额收益 (小数, 如 ``0.15``)
        sharpe: 夏普比率
        calmar: Calmar 比率
        beta_vs_hs300: Beta vs 沪深 300
        policy: ``load_policy`` 返回的完整配置

    Returns:
        dict 包含以下字段:

        - **absolute_max_drawdown**: ``strategy_max_dd``
        - **peer_max_drawdown**: ``peer_max_dd``
        - **relative_drawdown_vs_peer**: ``strategy_max_dd / peer_max_dd``
        - **excess_return_vs_peer**: ``excess_return``
        - **calmar**: ``calmar``
        - **return_drawdown_efficiency**: ``excess_return / |strategy_max_dd|``
        - **max_drawdown_verdict**: ``'pass'`` / ``'warn'`` / ``'fail'``
        - **relative_drawdown_verdict**: ``'pass'`` / ``'warn'`` / ``'fail'``
        - **risk_verdict**: 两者中更严格的判定
        - **risk_detail**: 中文判定说明
    """
    thresholds = get_family_thresholds(family, policy)

    abs_max_dd = abs(strategy_max_dd)
    peer_abs = abs(peer_max_dd)
    relative_dd = (abs_max_dd / peer_abs) if peer_abs > 0 else float("inf")
    rde = excess_return / abs_max_dd if abs_max_dd > 0 else 0.0

    # — max_drawdown_verdict —
    warn_th = thresholds.get("max_drawdown_warn", 0.35)
    fail_th = thresholds.get("max_drawdown_fail", 0.50)
    if abs_max_dd >= fail_th:
        dd_verdict = "fail"
    elif abs_max_dd >= warn_th:
        dd_verdict = "warn"
    else:
        dd_verdict = "pass"

    # — relative_drawdown_verdict —
    rel_th = thresholds.get("max_relative_drawdown_vs_peer", 1.20)
    rel_verdict = "fail" if relative_dd >= rel_th else "pass"

    # — 综合 risk_verdict —
    risk_verdict = _worse_verdict(dd_verdict, rel_verdict)

    # — risk_detail —
    parts = []
    if dd_verdict != "pass":
        parts.append(
            f"最大回撤 {abs_max_dd:.1%} (阈 {warn_th:.0%}/{fail_th:.0%}) [{dd_verdict}]"
        )
    if rel_verdict != "pass":
        parts.append(
            f"相对回撤 {relative_dd:.2f}x (阈 {rel_th:.2f}x) [{rel_verdict}]"
        )
    if abs_max_dd < 0.05:
        parts.append("回撤控制优秀")
    min_excess = thresholds.get("min_excess_return_vs_peer_for_b", 0.03)
    if excess_return < min_excess:
        parts.append(f"超额收益 {excess_return:.1%} 低于 B 级阈值 {min_excess:.0%}")
    risk_detail = "; ".join(parts) if parts else "风险指标均在阈值范围内"

    return {
        "absolute_max_drawdown": strategy_max_dd,
        "peer_max_drawdown": peer_max_dd,
        "relative_drawdown_vs_peer": relative_dd,
        "excess_return_vs_peer": excess_return,
        "calmar": calmar,
        "return_drawdown_efficiency": rde,
        "max_drawdown_verdict": dd_verdict,
        "relative_drawdown_verdict": rel_verdict,
        "risk_verdict": risk_verdict,
        "risk_detail": risk_detail,
    }


def _downgrade(current: str, target: str) -> str:
    """取更严格的等级"""
    order = {"A": 1, "B": 2, "C": 3, "D": 4}
    return target if order.get(target, 4) > order.get(current, 4) else current
