"""组合因子验证引擎 — 复合因子全流程验证

对因子组合 (composite) 进行与单因子相同的完整验证流程:
  1. 用 factor_combiner 计算组合因子值
  2. run_anti_overfit 做反过拟合诊断
  3. run_rolling_validation 做 Walk-Forward 验证
  4. factor_family 分类 (category='composite')
  5. score_factor 评分

两个入口:
  - run_composite_validation()   — 单组合验证
  - validate_composites_batch()  — 批量验证多种组合方法 × 因子组合

用法:
    from factor_lab.composite.composite_validator import run_composite_validation, validate_composites_batch

    # 单组合
    result = run_composite_validation(
        factor_df, close_pivot,
        composite_name="ret5_vol60_weighted",
        factor_names=["ret5", "vol_ratio60"],
        combine_method="weighted_score",
        weights={"ret5": 0.6, "vol_ratio60": 0.4},
    )

    # 批量
    batch = validate_composites_batch(
        leaderboard_path="/mnt/d/HermesReports/factor_leaderboard/.../factor_leaderboard.json",
        combine_methods=["equal_weight_score", "weighted_score"],
        output_dir="/mnt/d/HermesReports/composite_validation",
    )
"""

import sys, os, json, csv, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports/composite_validation")


# ═══════════════════════════════════════════════════════════════════
# 1. 单组合验证
# ═══════════════════════════════════════════════════════════════════


def run_composite_validation(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    composite_name: str,
    factor_names: list,
    combine_method: str = "equal_weight_score",
    weights: Optional[dict] = None,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    start_date: str = "2025-01-02",
    end_date: str = "2026-06-30",
) -> dict:
    """对单个组合因子执行完整验证流程

    步骤:
      a. 用 compute_composite 计算组合因子值
      b. 将组合因子加入 factor_df (列名 = composite_name)
      c. 调用 run_anti_overfit 做反过拟合
      d. 调用 run_rolling_validation 做 Walk-Forward
      e. 从 factor_family 分类 (传入 'composite' 作为 category)
      f. 调用 score_factor 计算评分

    参数:
        factor_df: DataFrame, 含 date, symbol 和各因子列; 所有单因子必须已预先计算
        close_pivot: pivot 表 (date × symbol), 用于回测与基准
        composite_name: 组合因子名称 (也用作 df 中的列名)
        factor_names: 参与组合的单因子列名列表
        combine_method: 组合方法 (传给 factor_combiner.compute_composite)
        weights: {factor_name: weight} — 加权方法使用
        top_quantile: 选股分位数 (默认 0.2 = 前 20%)
        rebalance: 调仓频率 ('monthly' | 'weekly')
        start_date: 验证开始日期
        end_date: 验证结束日期

    返回:
        dict, 包含:
          - composite_name, factor_names, combine_method, weights
          - anti_overfit: run_anti_overfit 输出
          - rolling_validation: run_rolling_validation 输出 (或 limitation dict)
          - factor_score: score_factor 输出
          - family: 家族分类信息
          - limitation: 数据限制状态

    注意:
        - factor_df 中必须已包含 factor_names 列 (调用者需提前计算)
        - 如果数据不足, anti_overfit/rolling_validation 返回 limitation 而非完整结果
        - 不允许静默降级 — insufficient_data/limited 时会在结果中明确标记
    """
    from factor_lab.composite.factor_combiner import compute_composite
    from factor_lab.validation.anti_overfit import run_anti_overfit
    from factor_lab.validation.rolling_validator import run_rolling_validation
    from factor_lab.scoring.factor_score import score_factor
    from factor_lab.scoring.factor_family import classify_factor

    # — 检查必要列是否存在 —
    missing = [f for f in factor_names if f not in factor_df.columns]
    if missing:
        raise ValueError(
            f"组合因子 {composite_name} 缺少基础因子列: {missing}. "
            f"请确保在调用前已计算所有单因子。"
        )

    # — 计算组合因子值 —
    composite_values = compute_composite(
        factor_df, factor_names, method=combine_method, weights=weights,
    )
    factor_df = factor_df.copy()
    factor_df[composite_name] = composite_values

    # — 反过拟合诊断 —
    ao = run_anti_overfit(
        factor_df, composite_name, close_pivot=close_pivot,
        top_quantile=top_quantile, rebalance=rebalance,
    )

    # — Walk-Forward 滚动验证 —
    rv = run_rolling_validation(
        factor_df, composite_name, close_pivot,
        top_quantile=top_quantile, rebalance=rebalance,
        start_date=start_date, end_date=end_date,
    )

    # — 家族分类 (composite 作为 category) —
    family_info = classify_factor(composite_name, category="composite")
    family = family_info.get("family", "composite")
    family_label = family_info.get("label", "组合因子")

    # — 评分 —
    desc = f"{combine_method}({' + '.join(factor_names)})"
    fs = score_factor(
        ao,
        rolling_validation=rv,
        expression=desc,
        family=family,
    )

    # — 确定数据限制状态 —
    limitation = "full"
    if rv.get("limitation") == "insufficient_data":
        limitation = "insufficient_data"
    elif rv.get("limitation") == "limited":
        limitation = "limited"

    return {
        "composite_name": composite_name,
        "factor_names": factor_names,
        "combine_method": combine_method,
        "weights": weights,
        "family": family,
        "family_label": family_label,
        "expression": desc,
        "limitation": limitation,
        "anti_overfit": ao,
        "rolling_validation": rv,
        "factor_score": fs,
        "generated_at": datetime.now(CST).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# 2. 批量验证
# ═══════════════════════════════════════════════════════════════════


def validate_composites_batch(
    leaderboard_path: str,
    factor_names: Optional[list] = None,
    combine_methods: Optional[list] = None,
    start_date: str = "2025-01-02",
    end_date: str = "2026-06-30",
    rebalance: str = "monthly",
    top_n: int = 20,
    output_dir: Optional[str] = None,
) -> dict:
    """批量验证多种组合方法 × 因子组合

    流程:
      a. 从 leaderboard_path 加载候选池 (load_from_leaderboard)
      b. 如果 factor_names 未提供, 用 promoted_name
      c. 加载数据 (共享 K 线, 只加载一次)
      d. 计算所有基础因子值
      e. 对于每个组合方法 → run_composite_validation
      f. 计算因子相关性 (compute_correlation)
      g. 计算 TopN 重合度 (compute_topn_overlap)
      h. 生成排行榜
      i. 保存所有报告
      j. 返回完整结果

    参数:
        leaderboard_path: factor_leaderboard.json 路径
        factor_names: 要参与组合的因子名列表 (默认使用候选池的 promoted_name)
        combine_methods: 组合方法列表 (默认所有 5 种)
        start_date: 验证开始日期
        end_date: 验证结束日期
        rebalance: 调仓频率
        top_n: 选股数量 (转为 top_quantile = top_n / 100)
        output_dir: 输出目录 (默认自动生成)

    返回:
        dict, 包含:
          - config: 配置参数
          - summary: 汇总统计
          - entries: 每个组合的验证结果列表
          - correlation: 因子相关性分析
          - topn_overlap: TopN 重合度
          - method_summary: 按组合方法汇总
          - output_dir: 输出目录
    """
    from factor_lab.pool.candidate_pool import load_from_leaderboard
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from factor_lab.composite.factor_correlation import (
        compute_correlation,
        compute_topn_overlap,
    )
    from strategy_lab.universe import build

    if combine_methods is None:
        combine_methods = [
            "equal_weight_score",
            "weighted_score",
            "gated_score",
            "zscore_blend",
            "rank_blend",
        ]

    top_quantile = top_n / 100 if top_n < 100 else 0.2

    print(f"\n{'='*60}")
    print(f"  组合因子批量验证")
    print(f"  排行榜源: {leaderboard_path}")
    print(f"  组合方法: {combine_methods}")
    print(f"  区间: {start_date} ~ {end_date}")
    print(f"  调仓: {rebalance}, Top{top_n} (分位数={top_quantile:.0%})")
    print(f"{'='*60}\n")

    # — a. 加载候选池 —
    print("[1/8] 加载候选池...")
    pool = load_from_leaderboard(leaderboard_path)

    # — b. 确定因子列表 —
    if factor_names is None:
        factor_names = pool.promoted_names
        if not factor_names:
            factor_names = [e["factor_name"] for e in pool.all_entries
                           if e.get("pass_gate") and e.get("grade", "D") in ("A", "B")]
        if not factor_names:
            sorted_entries = sorted(pool.all_entries, key=lambda e: -e.get("score", 0))
            factor_names = [e["factor_name"] for e in sorted_entries[:10]]
        print(f"  使用的因子: {factor_names}")

    if not factor_names:
        raise ValueError("没有可用的因子用于组合验证。排行榜无 promoted 因子且 entries 为空。")

    if len(factor_names) < 2:
        raise ValueError(
            f"组合验证需要至少 2 个因子, 当前只有 {len(factor_names)} 个: {factor_names}"
        )

    print(f"  共 {len(factor_names)} 个因子, {len(combine_methods)} 种组合方法")
    print(f"  预计产生 {len(combine_methods)} 个组合")

    # — c. 加载数据 (共享, 只加载一次) —
    print("[2/8] 加载股票池...")
    symbols_set = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        try:
            stocks, meta = build(u_name)
            for s in stocks:
                symbols_set.add(s["symbol"])
        except Exception:
            continue
    symbols = sorted(symbols_set)
    print(f"  股票池: {len(symbols)} 只")

    print("[3/8] 加载 K 线...")
    padding_start = pd.Timestamp(start_date) - pd.Timedelta(days=120)
    df = load_stock_kline(
        symbols, start_date=str(padding_start.date()), end_date=end_date,
    )
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))
    print(f"  K 线: {len(df)} 行, {df['date'].min().date()} ~ {df['date'].max().date()}")

    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    # 过滤到有效区间
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    df_valid = df[mask].copy()

    if len(df_valid) < 200:
        raise ValueError(
            f"有效数据不足 {len(df_valid)} 行 (< 200)。请检查 start_date/end_date 设置。"
        )

    # — d. 计算所有基础因子值 —
    print("[4/8] 计算基础因子值...")
    registry = {f["name"]: f for f in list_factors()}
    computed_factors = []

    for fn in factor_names:
        if fn not in registry:
            print(f"  ⚠️ 因子 {fn} 不在注册表, 跳过")
            continue
        if fn in df_valid.columns:
            print(f"  ✓ {fn} (已存在)")
            computed_factors.append(fn)
            continue
        try:
            fdef = registry[fn]
            factor_values = fdef["func"](df, **fdef["params"])
            if hasattr(mask, 'values'):
                df_valid[fn] = factor_values[mask.values]
            elif hasattr(mask, '__iter__'):
                df_valid[fn] = factor_values[mask]
            else:
                df_valid[fn] = factor_values
            computed_factors.append(fn)
            print(f"  ✓ {fn} 计算完成")
        except Exception as e:
            print(f"  ❌ {fn} 计算失败: {e}")

    if len(computed_factors) < 2:
        raise ValueError(f"计算成功的基础因子不足 2 个 (成功: {computed_factors})")

    factor_names = computed_factors
    print(f"  成功计算 {len(factor_names)} 个因子: {factor_names}")

    # — e. 逐组合验证 —
    print(f"\n[5/8] 逐组合验证 ({len(combine_methods)} 种方法)...")
    entries = []

    for i, method in enumerate(combine_methods):
        combo_name = _make_composite_name(factor_names, method)

        print(f"\n  [{i+1}/{len(combine_methods)}] 方法: {method}")
        print(f"     组合名: {combo_name}")

        try:
            # 权重: 加权方法默认等权
            weights = None
            if method in ("weighted_score", "zscore_blend", "rank_blend"):
                weights = {f: 1.0 / len(factor_names) for f in factor_names}

            result = run_composite_validation(
                df_valid,
                close_pivot,
                composite_name=combo_name,
                factor_names=factor_names,
                combine_method=method,
                weights=weights,
                top_quantile=top_quantile,
                rebalance=rebalance,
                start_date=start_date,
                end_date=end_date,
            )

            fs = result["factor_score"]
            ao = result["anti_overfit"]
            rv = result["rolling_validation"]

            entry = {
                "composite_name": combo_name,
                "factor_names": factor_names,
                "combine_method": method,
                "factor_family": result.get("family", "composite"),
                "expression": result.get("expression", ""),
                "limitation": result.get("limitation", "full"),
                "score": fs.get("overall_score", 0),
                "grade": fs.get("grade", "D"),
                "pass_gate": fs.get("pass_gate", False),
                "reject_reasons": fs.get("reject_reasons", []),
                "improvement_suggestions": fs.get("improvement_suggestions", []),
                "cumulative_return": ao.get("peer_benchmark", {}).get("strategy_cumulative_pct") if ao else None,
                "max_drawdown": abs(fs.get("absolute_max_drawdown", 0)),
                "peer_max_drawdown": fs.get("peer_max_drawdown"),
                "relative_drawdown_vs_peer": fs.get("relative_drawdown_vs_peer"),
                "excess_return_vs_peer": fs.get("excess_return_vs_peer"),
                "calmar": fs.get("calmar"),
                "ic_mean": ao.get("ic_stability", {}).get("ic_mean") if ao else None,
                "rank_ic_mean": ao.get("ic_stability", {}).get("rank_ic_mean") if ao else None,
                "ic_ir": ao.get("ic_stability", {}).get("ic_ir") if ao else None,
                "positive_ic_ratio": ao.get("ic_stability", {}).get("positive_ic_ratio") if ao else None,
                "placebo_percentile": ao.get("placebo", {}).get("factor_score_percentile") if ao else None,
                "placebo_pass": ao.get("placebo", {}).get("verdict") == "pass" if ao else None,
                "walk_forward_pass": rv.get("overall_verdict") == "pass" if rv else None,
                "walk_forward_test_return": rv.get("avg_test_cumulative_return_pct") if rv else None,
                "walk_forward_avg_decay": rv.get("avg_decay") if rv else None,
                "base_factor_avg_score": _avg_base_score(pool, factor_names),
                "fs_report": fs,
            }
            entries.append(entry)

            grade_icon = "✅" if entry["pass_gate"] else "❌"
            print(f"     评分: {entry['score']:.1f}/{entry['grade']} {grade_icon}")

        except Exception as e:
            print(f"    ❌ 验证失败: {e}")
            entries.append({
                "composite_name": combo_name,
                "factor_names": factor_names,
                "combine_method": method,
                "factor_family": "composite",
                "expression": f"{method}({' + '.join(factor_names)})",
                "limitation": "error",
                "score": 0,
                "grade": "D",
                "pass_gate": False,
                "error": str(e),
                "reject_reasons": [f"验证异常: {e}"],
                "improvement_suggestions": [],
                "fs_report": {},
            })

    if not entries:
        raise ValueError("所有组合验证均失败, 无有效结果")

    # — f. 因子相关性分析 —
    print(f"\n[6/8] 计算因子相关性...")
    composite_cols = [e["composite_name"] for e in entries]
    correlation = _safe_compute_correlation(df_valid, composite_cols)
    print(f"  平均 Pearson 相关性: {correlation.get('avg_corr', 'N/A')}")

    # — g. TopN 重合度 —
    print(f"[7/8] 计算 TopN 重合度...")
    topn_overlap = _safe_compute_topn_overlap(df_valid, composite_cols, top_quantile)
    print(f"  平均重合度: {topn_overlap.get('avg_overlap', 'N/A')}")

    # — 排序 —
    entries.sort(key=lambda e: -e.get("score", 0))

    # — h. 生成排行榜 —
    print(f"[8/8] 生成排行榜...")

    promoted = [e for e in entries
                if e.get("pass_gate") and e.get("grade", "D") in ("A", "B")]
    rejected = [e for e in entries
                if not (e.get("pass_gate") and e.get("grade", "D") in ("A", "B"))]

    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in entries:
        grade_counts[e.get("grade", "D")] = grade_counts.get(e.get("grade", "D"), 0) + 1

    # 按组合方法汇总
    method_summary = {}
    for e in entries:
        m = e.get("combine_method", "unknown")
        if m not in method_summary:
            method_summary[m] = {"count": 0, "scores": [], "pass_count": 0}
        method_summary[m]["count"] += 1
        method_summary[m]["scores"].append(e.get("score", 0))
        if e.get("pass_gate"):
            method_summary[m]["pass_count"] += 1

    method_summary_out = {}
    for method, data in method_summary.items():
        method_summary_out[method] = {
            "count": data["count"],
            "avg_score": round(float(np.mean(data["scores"])), 1) if data["scores"] else 0,
            "pass_rate": round(data["pass_count"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
        }

    result = {
        "generated_at": datetime.now(CST).isoformat(),
        "config": {
            "n_base_factors": len(factor_names),
            "n_combine_methods": len(combine_methods),
            "n_composites": len(entries),
            "start_date": start_date,
            "end_date": end_date,
            "rebalance": rebalance,
            "top_quantile": top_quantile,
            "top_n": top_n,
            "factor_names": factor_names,
            "combine_methods": combine_methods,
        },
        "summary": {
            "total": len(entries),
            "grade_counts": grade_counts,
            "passed": len(promoted),
            "rejected": len(rejected),
            "errors": sum(1 for e in entries if "error" in e),
            "limitation_insufficient": sum(1 for e in entries if e.get("limitation") == "insufficient_data"),
            "limitation_limited": sum(1 for e in entries if e.get("limitation") == "limited"),
        },
        "entries": entries,
        "promoted": [e["composite_name"] for e in promoted],
        "rejected": [e["composite_name"] for e in rejected],
        "method_summary": method_summary_out,
        "correlation": correlation,
        "topn_overlap": topn_overlap,
    }

    # — i. 保存报告 —
    out_dir = Path(output_dir or str(BASE_OUTPUT / datetime.now(CST).strftime("%Y%m%d_%H%M%S")))
    out_dir.mkdir(parents=True, exist_ok=True)
    result["output_dir"] = str(out_dir)

    # JSON
    _save_json(result, out_dir / "composite_leaderboard.json")

    # CSV
    csv_fields = [
        "composite_name", "combine_method", "factor_family", "score", "grade", "pass_gate",
        "cumulative_return", "max_drawdown", "peer_max_drawdown",
        "relative_drawdown_vs_peer", "excess_return_vs_peer", "calmar",
        "ic_mean", "rank_ic_mean", "ic_ir", "positive_ic_ratio",
        "placebo_percentile", "placebo_pass", "walk_forward_pass",
        "walk_forward_test_return", "walk_forward_avg_decay",
        "base_factor_avg_score", "limitation",
    ]
    _save_csv(entries, csv_fields, out_dir / "composite_leaderboard.csv")

    _save_md_report(promoted, rejected, result["summary"], out_dir)
    _save_html_report(result, out_dir)
    _save_audit(result, out_dir)
    _save_json(correlation, out_dir / "factor_correlation.json")
    _save_json(topn_overlap, out_dir / "factor_topn_overlap.json")
    _save_json(method_summary_out, out_dir / "method_summary.json")

    _print_limitation_warnings(entries, out_dir)
    _print_summary(entries, promoted, rejected, grade_counts, method_summary_out)

    return result


# ═══════════════════════════════════════════════════════════════════
# 3. 辅助工具
# ═══════════════════════════════════════════════════════════════════


def _make_composite_name(factor_names: list, method: str) -> str:
    """为组合因子生成唯一名称"""
    prefix = "_".join(factor_names)
    method_short = {
        "equal_weight_score": "equal",
        "weighted_score": "weighted",
        "gated_score": "gated",
        "zscore_blend": "zscore",
        "rank_blend": "rank",
    }
    suffix = method_short.get(method, method)
    return f"{prefix}_{suffix}"


def _avg_base_score(pool, factor_names: list) -> float:
    """计算基础因子的平均评分 (从候选池中取)"""
    entry_map = {e["factor_name"]: e for e in pool.all_entries}
    scores = []
    for fn in factor_names:
        if fn in entry_map:
            s = entry_map[fn].get("score", 0)
            if s is not None:
                scores.append(s)
    return round(float(np.mean(scores)), 1) if scores else 0.0


def _safe_compute_correlation(df_valid: pd.DataFrame, cols: list) -> dict:
    """安全调用 compute_correlation, 数据不足时返回空结构"""
    from factor_lab.composite.factor_correlation import compute_correlation
    present = [c for c in cols if c in df_valid.columns]
    if len(present) < 2:
        return {"pearson": {}, "spearman": {}, "avg_corr": 0,
                "note": f"数据不足 (有效列 {len(present)} < 2)"}
    try:
        return compute_correlation(df_valid, present)
    except Exception as e:
        return {"pearson": {}, "spearman": {}, "avg_corr": 0,
                "note": f"相关性计算失败: {e}"}


def _safe_compute_topn_overlap(df_valid: pd.DataFrame, cols: list, top_quantile: float) -> dict:
    """安全调用 compute_topn_overlap, 数据不足时返回空结构"""
    from factor_lab.composite.factor_correlation import compute_topn_overlap
    present = [c for c in cols if c in df_valid.columns]
    if len(present) < 2:
        return {"overlap_matrix": {}, "avg_overlap": 0,
                "note": f"数据不足 (有效列 {len(present)} < 2)"}
    try:
        return compute_topn_overlap(df_valid, present, top_quantile=top_quantile)
    except Exception as e:
        return {"overlap_matrix": {}, "avg_overlap": 0,
                "note": f"重叠度计算失败: {e}"}


def _save_json(data: dict, path: Path):
    """保存 dict 为 JSON"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _save_csv(entries: list, fields: list, path: Path):
    """保存 entries 为 CSV"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for e in entries:
            w.writerow(e)


def _save_md_report(promoted: list, rejected: list, summary: dict, out_dir: Path):
    """保存 promoted / rejected markdown 报告"""
    lines = ["# 组合因子推荐", "", f"共 {len(promoted)} 个通过门禁的组合:", ""]
    for e in promoted:
        r = "; ".join(e.get("reject_reasons", [])[:2])
        lines.append(
            f"- **{e['composite_name']}** ({e.get('combine_method','?')}) "
            f"评分={e['score']:.1f}/{e['grade']}"
        )
        if r:
            lines.append(f"  - ⚠️ {r}")
    lines.append("")
    lines.append(f"_批量验证: {summary['passed']} 通过, {summary['rejected']} 淘汰_")
    with open(out_dir / "promoted_composites.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    lines = ["# 淘汰组合", "", f"共 {len(rejected)} 个未通过:", ""]
    for e in rejected:
        reasons = "; ".join(e.get("reject_reasons", [])[:3])
        lines.append(
            f"- **{e['composite_name']}** ({e.get('combine_method','?')}) "
            f"评分={e['score']:.1f}/{e['grade']}"
        )
        if reasons:
            lines.append(f"  - ❌ {reasons}")
    lines.append("")
    lines.append(f"_淘汰率: {summary['rejected']}/{summary['total']}_")
    with open(out_dir / "rejected_composites.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _save_html_report(result: dict, out_dir: Path):
    """保存 HTML 排行榜"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    cfg = result["config"]
    summary = result["summary"]
    entries = result["entries"]
    grade_color_map = {"A": "#00c853", "B": "#64dd17", "C": "#ff9100", "D": "#ff1744"}

    table_rows = ""
    for i, e in enumerate(entries):
        gc = grade_color_map.get(e.get("grade", "D"), "#888")
        pass_icon = "✅" if e.get("pass_gate") else "❌"
        reasons = "; ".join(e.get("reject_reasons", [])[:2])
        badge = _limitation_badge(e.get("limitation", ""))
        table_rows += f"""<tr>
<td>{i+1}</td>
<td style="font-family:monospace;font-size:0.85em;">{e.get('composite_name','?')}</td>
<td style="font-size:0.85em;">{e.get('combine_method','?')}</td>
<td class="num">{e.get('score',0):.1f}</td>
<td><span class="grade" style="color:{gc}">{e.get('grade','?')}</span></td>
<td>{pass_icon}</td>
<td class="num">{e.get('cumulative_return','--')}%</td>
<td class="num">{e.get('max_drawdown','--')}%</td>
<td class="num">{e.get('relative_drawdown_vs_peer','--')}</td>
<td class="num">{e.get('excess_return_vs_peer','--')}%</td>
<td class="num">{e.get('ic_ir','--')}</td>
<td class="num">{e.get('placebo_percentile','--')}%</td>
<td>{badge}</td>
<td style="font-size:0.8em;color:#aaa;">{reasons}</td>
</tr>"""

    method_rows = ""
    for method, data in sorted(result.get("method_summary", {}).items()):
        method_rows += f"""<tr><td style="font-family:monospace;">{method}</td>
<td class="num">{data['count']}</td>
<td class="num">{data['avg_score']}</td>
<td class="num">{data['pass_rate']}%</td></tr>"""

    corr_avg = result.get('correlation', {}).get('avg_corr', 'N/A')
    overlap_avg = result.get('topn_overlap', {}).get('avg_overlap', 'N/A')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>组合因子排行榜 — 批量验证报告</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; background: #1a1a2e; color: #e0e0e0; margin:0; padding:20px; }}
.card {{ background: #16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color: #00bcd4; }} h2 {{ color: #00bcd4; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.grade {{ font-weight:bold; font-size:1.1em; }}
.summary-box {{ display:inline-block; padding:10px 20px; margin:4px; border-radius:6px; text-align:center; }}
.summary-num {{ font-size:1.8em; font-weight:bold; }}
.summary-label {{ font-size:0.8em; color:#aaa; }}
.badge {{ display:inline-block; padding:1px 6px; border-radius:3px; font-size:0.75em; font-weight:bold; }}
.badge-full {{ background:#00c85333; color:#00c853; }}
.badge-limited {{ background:#ff910033; color:#ff9100; }}
.badge-insufficient {{ background:#ff174433; color:#ff1744; }}
.badge-error {{ background:#ff174433; color:#ff1744; }}
</style></head><body>

<div class="card" style="text-align:center;">
<h1>🧩 组合因子排行榜</h1>
<p style="color:#aaa;">{now} | {cfg['n_composites']} 个组合 | {cfg['n_base_factors']} 个基础因子 | {cfg['start_date']} ~ {cfg['end_date']} | 调仓: {cfg['rebalance']}</p>
<p style="color:#666;">基础因子: {', '.join(cfg['factor_names'])}</p>
<div class="summary-box" style="background:#00c85322;"><div class="summary-num">{summary.get('grade_counts',{}).get('A',0)}</div><div class="summary-label">A 级</div></div>
<div class="summary-box" style="background:#64dd1722;"><div class="summary-num">{summary.get('grade_counts',{}).get('B',0)}</div><div class="summary-label">B 级</div></div>
<div class="summary-box" style="background:#ff910022;"><div class="summary-num">{summary.get('grade_counts',{}).get('C',0)}</div><div class="summary-label">C 级</div></div>
<div class="summary-box" style="background:#ff174422;"><div class="summary-num">{summary.get('grade_counts',{}).get('D',0)}</div><div class="summary-label">D 级</div></div>
<div class="summary-box" style="background:#00bcd422;"><div class="summary-num">{summary['passed']}</div><div class="summary-label">✅ 通过</div></div>
<div class="summary-box" style="background:#ff174422;"><div class="summary-num">{summary['rejected']}</div><div class="summary-label">❌ 淘汰</div></div>
</div>

<div class="card">
<h2>🏆 组合因子排行 (按评分降序)</h2>
<div style="overflow-x:auto;">
<table>
<tr><th>#</th><th>组合名</th><th>方法</th><th class="num">评分</th><th>等级</th><th>通过</th>
<th class="num">累计收益</th><th class="num">回撤</th><th class="num">相对回撤</th><th class="num">超额收益</th>
<th class="num">IC_IR</th><th class="num">Placebo</th><th>限制</th><th>淘汰原因</th></tr>
{table_rows}
</table></div></div>

<div class="card">
<h2>📊 组合方法汇总</h2>
<table>
<tr><th>方法</th><th class="num">数量</th><th class="num">平均分</th><th class="num">通过率</th></tr>
{method_rows}
</table>
</div>

<div class="card">
<h2>📋 因子相关性</h2>
<p>平均 Pearson 相关性: <strong>{corr_avg}</strong></p>
<p>平均 Top{cfg.get('top_n', 20)} 重合度: <strong>{overlap_avg}</strong></p>
</div>

<div class="card">
<h2>💡 组合因子说明</h2>
<ul>
<li><strong>组合因子</strong> 是多个基础因子的加权/门控合成, 旨在提升稳定性。</li>
<li>验证流程与单因子完全一致: 反过拟合 + Walk-Forward + 评分。</li>
<li>组合名称编码了参与因子和组合方法, 便于追溯。</li>
<li><strong>数据限制</strong>: insufficient_data/limited 时组合验证仍会完成, 但评分可能不可靠。</li>
</ul>
</div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>Composite Validator | {now}</p>
</div>

</body></html>"""
    with open(out_dir / "composite_leaderboard.html", "w", encoding="utf-8") as f:
        f.write(html)


def _save_audit(result: dict, out_dir: Path):
    """保存审计日志"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    cfg = result["config"]
    summary = result["summary"]
    lines = [
        f"=== COMPOSITE VALIDATION AUDIT LOG ===",
        f"Time: {now}",
        f"Base factors: {cfg['n_base_factors']}",
        f"Combine methods: {cfg['n_combine_methods']}",
        f"Composites validated: {cfg['n_composites']}",
        f"Period: {cfg['start_date']} ~ {cfg['end_date']}",
        f"Rebalance: {cfg['rebalance']}, Top-N: {cfg['top_n']}",
        f"",
        f"--- Summary ---",
        f"Total: {summary['total']}",
        f"A: {summary['grade_counts'].get('A',0)}",
        f"B: {summary['grade_counts'].get('B',0)}",
        f"C: {summary['grade_counts'].get('C',0)}",
        f"D: {summary['grade_counts'].get('D',0)}",
        f"Passed: {summary['passed']}",
        f"Rejected: {summary['rejected']}",
        f"Errors: {summary.get('errors',0)}",
        f"Insufficient data: {summary.get('limitation_insufficient',0)}",
        f"Limited: {summary.get('limitation_limited',0)}",
        f"",
        f"--- Per Composite ---",
    ]
    for e in result["entries"]:
        lines.append(
            f"{e.get('composite_name','?'):40s} | {e.get('combine_method','?'):20s} | "
            f"score={e.get('score',0):5.1f} | grade={e.get('grade','?'):1s} | "
            f"pass={e.get('pass_gate',False)} | limitation={e.get('limitation','full')}"
        )
    lines.append("")
    lines.append("--- End Audit ---")
    with open(out_dir / "audit.log", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _limitation_badge(limitation: str) -> str:
    """生成 limitation HTML 徽章"""
    if limitation == "full":
        return '<span class="badge badge-full">full</span>'
    elif limitation == "limited":
        return '<span class="badge badge-limited">limited</span>'
    elif limitation == "insufficient_data":
        return '<span class="badge badge-insufficient">insufficient</span>'
    else:
        return '<span class="badge badge-error">error</span>'


def _print_limitation_warnings(entries: list, out_dir: Path):
    """打印数据不足的警告并写入 warning.log"""
    limited = [e for e in entries if e.get("limitation") in ("insufficient_data", "limited")]
    if limited:
        print(f"\n⚠️  数据限制警告:")
        for e in limited:
            print(f"    {e['composite_name']}: limitation={e['limitation']}")
        warnings = [
            f"Composite '{e['composite_name']}' "
            f"limitation={e['limitation']} — 结果不可靠, "
            f"请延长数据区间或增加基础因子数量"
            for e in limited
        ]
        with open(out_dir / "limitation_warnings.log", "w", encoding="utf-8") as f:
            f.write("\n".join(warnings))


def _print_summary(entries, promoted, rejected, grade_counts, method_summary):
    """打印控制台摘要"""
    print(f"\n{'='*60}")
    print(f"  组合因子批量验证完成")
    print(f"  A: {grade_counts.get('A',0)}  B: {grade_counts.get('B',0)}  "
          f"C: {grade_counts.get('C',0)}  D: {grade_counts.get('D',0)}")
    print(f"  ✅ 通过: {len(promoted)}  ❌ 淘汰: {len(rejected)}")
    if method_summary:
        print(f"\n  组合方法表现:")
        for method, data in sorted(method_summary.items(), key=lambda x: -x[1]["avg_score"]):
            print(f"    {method:25s} | 平均分: {data['avg_score']:>5.1f} | 通过率: {data['pass_rate']:>4.0f}%")
    if promoted:
        print(f"\n  推荐组合:")
        for e in promoted:
            print(f"    ✅ {e['composite_name']:45s} 评分={e['score']:.1f}/{e['grade']}  超额={e.get('excess_return_vs_peer','?')}%")
    print(f"{'='*60}\n")
