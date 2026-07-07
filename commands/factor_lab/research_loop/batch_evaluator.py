"""Batch Evaluator — 批量因子并发回测评估

支持 10-20 个表达式并发提交 + 3 波重试 + 结果排序。

基于 QuantGPT scripts/factor_miner.py 移植。
"""

import sys, os, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from dataclasses import dataclass, field, asdict


@dataclass
class FactorResult:
    expression: str
    name: str = ""
    fitness: float = 0.0
    sharpe: float = 0.0
    returns: float = 0.0
    turnover: float = 0.0
    ic: float = 0.0
    ic_ir: float = 0.0
    grade: str = "?"
    score: float = 0.0
    status: str = "pending"
    error: str = ""
    timestamp: str = ""


def _evaluate_single(expression: str, params: dict) -> Optional[FactorResult]:
    """评估单个因子

    在真实场景中，这里调用 factor:validate 机制进行完整回测。
    当前提供占位评估，通过 expression_parser 做基础语法检查。
    """
    from factor_lab.expression_parser import ExpressionParser

    parser = ExpressionParser()
    err = parser.validate(expression)
    if err:
        return FactorResult(
            expression=expression,
            status="failed", error=f"语法错误: {err}",
        )

    # 占位 IC 估算（基于表达式长度和算子复杂度做简单打分）
    # 真实场景应替换为 factor:validate 全流程
    ic_est = _estimate_ic(expression)

    return FactorResult(
        expression=expression,
        name=params.get("name", ""),
        fitness=abs(ic_est) * 0.5,
        sharpe=abs(ic_est) * 3.0,
        ic=ic_est,
        ic_ir=abs(ic_est) * 10.0,
        score=min(abs(ic_est) * 2000, 80),
        grade="B" if abs(ic_est) > 0.02 else "C",
        status="completed",
    )


def _estimate_ic(expression: str) -> float:
    """估算 IC（占位方法 — 基于表达式特征）"""
    # 仅用于演示。实际应运行真实回测。
    import hashlib
    seed = int(hashlib.md5(expression.encode()).hexdigest(), 16) % 1000
    base = 0.03
    # 含 rank/zscore → 略高
    if "rank" in expression or "zscore" in expression:
        base += 0.01
    # 含 ts_corr → 略高
    if "ts_corr" in expression:
        base += 0.005
    # 过长 → 惩罚
    if len(expression) > 150:
        base -= 0.01
    noise = (seed % 20 - 10) * 0.002
    return round(base + noise, 4)


def batch_evaluate(
    expressions: list[str],
    params: Optional[dict] = None,
    max_concurrent: int = 10,
    timeout: int = 600,
    retry_waves: int = 3,
) -> list[dict]:
    """批量因子评估

    Args:
        expressions: 因子表达式列表
        params: 评估参数 (universe, start, end, holding_period 等)
        max_concurrent: 最大并发数
        timeout: 超时秒数
        retry_waves: 重试波次

    Returns:
        按 fitness 降序排列的结果列表
    """
    if params is None:
        params = {}

    results = []
    failed = list(expressions)
    seen = set()

    for wave in range(retry_waves):
        if not failed:
            break
        batch = failed
        failed = []

        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            futures = {
                pool.submit(_evaluate_single, expr, params): expr
                for expr in batch
            }
            for fut in as_completed(futures):
                expr = futures[fut]
                try:
                    r = fut.result(timeout=timeout)
                    if r and r.status == "completed":
                        if expr not in seen:
                            results.append(r)
                            seen.add(expr)
                    else:
                        failed.append(expr)
                except Exception:
                    failed.append(expr)

        if failed and wave < retry_waves - 1:
            time.sleep(2 * (wave + 1))

    # 去重
    seen_exprs = set()
    unique = []
    for r in results:
        if r.expression not in seen_exprs:
            unique.append(r)
            seen_exprs.add(r.expression)

    unique.sort(key=lambda x: x.fitness, reverse=True)
    return [asdict(r) for r in unique]


def cmd_batch_evaluate(
    expressions: list[str],
    max_concurrent: int = 10,
) -> str:
    """CLI 入口：批量评估"""
    results = batch_evaluate(expressions, max_concurrent=max_concurrent)
    lines = [f"📊 批量评估结果 ({len(results)}):\n"]
    for r in results[:20]:
        fitness = r.get("fitness", 0)
        ic = r.get("ic", 0)
        name = r.get("name", r["expression"][:50])
        lines.append(f"  [{r.get('grade','?')}] fitness={fitness:.3f} IC={ic:.4f}  {name}")
    if len(results) > 20:
        lines.append(f"  ... 还有 {len(results)-20} 个")
    return "\n".join(lines)
