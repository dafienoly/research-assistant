# V3.1.2 Top20因子全量验证 — 子代理 Spec

## 依赖：V3.1.1 (真实 benchmark 指数接入) 已完成

## 修改文件

### 1. commands/factor_lab/validate_factor.py（新建/扩展）

新建完整验证流程：

```python
"""V3.1.2 因子全量验证 — 对Top20最常用因子执行完整IC/同池等权/WalkForward/暴露分析"""

VALIDATION_CONFIG = {
    "top_n_factors": [
        "ret5", "ret10", "ret20", "ret60",           # 动量
        "vol_ratio5", "vol_ratio20", "vol_ratio60",   # 成交量
        "ma10_gt_ma20", "ma20_gt_ma60",               # 均线
        "close_gt_ma20",                               # 均线偏离
        "volatility20", "volatility60", "atr20",       # 波动率
        "reversal5", "reversal20",                    # 反转
        "amihud",                                      # 流动性
        "roe_q", "gross_margin_q",                     # 质量(基本面仅有的)
        "macd", "boll_width",                          # 技术指标
    ],
    "validation_period": ("2023-01-01", "2026-06-30"),  # 3.5年
    "oos_windows": [
        ("2023-01", "2024-06", "2024-07", "2025-06"),  # 1.5y train + 1y test
        ("2024-01", "2025-06", "2025-07", "2026-06"),  # 1.5y train + 1y test
    ],
    "output_dir": "research_outputs/factor_validation/",
}

def validate_single_factor(factor_name: str, 
                           df: pd.DataFrame,
                           close_pivot: pd.DataFrame,
                           benchmark_returns: pd.Series) -> dict:
    """对单个因子跑完整验证管线：
    
    1. IC + ICIR + 逐日/月度/季度 IC
    2. 5层分层回测（long-short）
    3. 同池等权对比（check_peer_benchmark）
    4. 真实 benchmark 对比（沪深300/中证500）
    5. Walk-Forward（2个窗口）
    6. 安慰剂检验（100 trials）
    7. IC 衰减（1/3/5/10/20天）
    8. 暴露分析（行业/市值）
    """
    from factor_lab.factor_evaluation import FactorEvaluation
    
    ev = FactorEvaluation()
    result = ev.run_full_evaluation(
        df, close_pivot, factor_name,
        top_quantile=0.2, rebalance="monthly",
    )
    # 添加 benchmark 对比（走真实数据）
    result["benchmark_comparison"] = compare_to_benchmark(...)
    return result

def validate_top_n_factors() -> pd.DataFrame:
    """验证 Top20 因子，输出合并排行榜"""

def compare_to_benchmark(factor_name, ...) -> dict:
    """因子 vs 真实 benchmark（沪深300）对比"""

def generate_validation_report(all_results: list[dict], output_dir: str):
    """生成验证报告 HTML"""
```

### 2. 验证流程（详细步骤）

对每个因子：

```python
def validate_one(factor_name: str) -> dict:
    # Step 1: 加载数据（2023-01 到 2026-06）
    df = load_kline_with_factor(universe, factor_name, "2023-01-01", "2026-06-30")
    close_pivot = build_close_pivot(df)
    
    # Step 2: IC 分析
    ic_result = evaluate_ic(df, factor_name)
    
    # Step 3: 反过拟合
    ao_result = evaluate_anti_overfit(df, factor_name, close_pivot)
    
    # Step 4: Walk-Forward
    wf_result = evaluate_walk_forward(df, factor_name, close_pivot)
    
    # Step 5: 暴露分析
    exp_result = evaluate_exposure(df, factor_name)
    
    # Step 6: Benchmark 对比（使用真实 benchmark）
    bench_result = compare_to_real_benchmark(df, factor_name, close_pivot)
    
    # Step 7: 评分
    score_result = evaluate_scoring(ao_result, wf_result, factor_name)
    
    return {
        "factor_name": factor_name,
        "ic": ic_result,
        "anti_overfit": ao_result,
        "walk_forward": wf_result,
        "exposure": exp_result,
        "benchmark": bench_result,
        "score": score_result,
        "verdict": "promote" / "watch" / "retire",
    }
```

### 3. 输出

目录结构：
```
research_outputs/factor_validation/
├── validation_leaderboard.csv        # 全量排行榜（20行）
├── validation_summary.json            # 汇总统计
├── <factor_name>/                    # 每个因子独立目录
│   ├── report.json                   # 完整验证结果
│   ├── ic_curve.png                   # IC 时间序列图
│   └── layer_returns.png             # 分层收益图
```

`validation_leaderboard.csv` 列：
| factor | ic_mean | ic_ir | pos_ratio | beats_peer | ls_sharpe | wf_verdict | placebo_verdict | exposure_verdict | overall_grade |

### 4. CLI 入口

在 `commands/factor_lab/validate_factor.py` 末尾添加：

```python
if __name__ == "__main__":
    # 运行完整验证
    results = validate_top_n_factors()
    generate_validation_report(results, "research_outputs/factor_validation/")
    print(f"已完成 {len(results)} 个因子验证")
    # 输出 grade 分布
    from collections import Counter
    grades = Counter(r["score"]["grade"] for r in results)
    print(f"等级分布: {dict(grades)}")
```

### 5. 验证验收标准

```python
# 前提：benchmark 数据已接入真实数据
from factor_lab.portfolio.benchmark import get_benchmark_returns, make_benchmark_spec

# 验证 benchmark 可用
bench = get_benchmark_returns(make_benchmark_spec("CSI300"))
assert len(bench) > 500, f"沪深300应有500+交易日, 实际{len(bench)}"
assert 0.05 < bench.std() * sqrt(252) < 0.50, "年化波动率应合理"

# 验证至少一个因子 beats_peer
results = validate_top_n_factors()
beats = [r for r in results if r["anti_overfit"]["peer_benchmark"]["beats_peer"]]
print(f"跑赢同池等权的因子: {len(beats)}/{len(results)}")
assert len(beats) > 0, "至少应有因子跑赢同池等权"

# 输出 grade 分布
print("Grade 分布:", Counter(r["score"]["grade"] for r in results))
```

## 注意事项

1. **必须 V3.1.1 完成后才能运行**（benchmark 数据需要真实）
2. 验证周期 3.5 年（2023-2026），比之前的 18 个月长
3. 每个因子验证约需 2-5 分钟（取决于数据量），20 个因子约 40-100 分钟
4. 验证结果 JSON 是 Alpha Lifecycle 进阶的 Gate 证据
5. 如果有因子在验证中暴露未来函数或数据泄露，标记为 `status: failed`
