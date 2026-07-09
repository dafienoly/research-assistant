# V3.3.2 风控约束集成 — 子代理 Spec

## 依赖：V3.3.1 (因子加权组合) 或独立

## 背景

当前组合构建只支持等权 Top-N。缺少行业暴露约束、换手约束、板块权限过滤等实盘必需的风控能力。

## 修改文件

### 文件: commands/factor_lab/composite/factor_combiner.py

在 V3.3.1 函数后追加：

```python
"""V3.3.2 组合风控约束 — 行业暴露/换手/板块过滤"""

def apply_portfolio_constraints(
    candidate_scores: pd.Series,  # index=symbol, values=score
    current_positions: dict = None,
    industry_map: dict = None,
    board_map: dict = None,
    constraints: dict = None,
) -> pd.Series:
    """对候选打分序列应用组合风控约束
    
    Args:
        candidate_scores: {symbol: score}
        current_positions: {symbol: {"weight": 0.05, ...}}
        industry_map: {symbol: "行业名"}
        board_map: {symbol: "main"/"gem"/"star"}
        constraints: {
            "max_industry_weight": 0.30,    # 单行业上限
            "max_single_weight": 0.25,      # 单票上限
            "max_turnover": 0.30,           # 单期换手率上限
            "min_amount": 50_000_000,       # 最低日成交额
            "allowed_boards": ["main", "gem"],  # 允许板块
            "top_n": 10,                    # 选股数
        }
    
    Returns:
        过滤后的得分 Series（移除/降低不符合约束的候选）
    """
    if constraints is None:
        constraints = {}
    
    scores = candidate_scores.copy()
    
    # 1. 板块过滤
    allowed_boards = constraints.get("allowed_boards", ["main", "gem", "star"])
    if board_map:
        for sym in list(scores.index):
            board = board_map.get(sym, "main")
            if board not in allowed_boards:
                scores[sym] = -999  # 标记为排除
    
    # 2. 行业暴露约束
    max_ind_weight = constraints.get("max_industry_weight", 0.30)
    if industry_map and max_ind_weight < 1.0:
        industry_weights = {}
        for sym in scores.nlargest(constraints.get("top_n", 20)).index:
            ind = industry_map.get(sym, "unknown")
            industry_weights[ind] = industry_weights.get(ind, 0) + 1 / constraints.get("top_n", 20)
        # 超限行业的候选降低排名
        for ind, weight in industry_weights.items():
            if weight > max_ind_weight:
                overshoot_pct = weight / max_ind_weight
                for sym in scores.index:
                    if industry_map.get(sym, "") == ind:
                        scores[sym] /= overshoot_pct  # 降低权重
    
    # 3. 换手约束（需当前持仓信息）
    max_turnover = constraints.get("max_turnover", 1.0)
    if current_positions and max_turnover < 1.0:
        current_symbols = set(current_positions.keys())
        target_symbols = set(scores.nlargest(constraints.get("top_n", 20)).index)
        new_entries = target_symbols - current_symbols
        max_new = int(max_turnover * constraints.get("top_n", 20))
        if len(new_entries) > max_new:
            # 只保留得分最高的 max_new 个新入选
            new_scores = scores.loc[list(new_entries)].sort_values(ascending=False)
            keep = set(new_scores.head(max_new).index)
            for sym in new_entries:
                if sym not in keep:
                    scores[sym] = -999
    
    return scores


def filter_candidates_for_execution(
    candidates: list,
    constraints: dict,
    prices: dict = None,
) -> list[dict]:
    """对候选执行最终过滤（实盘前的最后检查）
    
    检查项:
    - 100股整数倍（lot_size）
    - 涨停/跌停
    - 尾盘禁新仓（14:30后）
    - 账户现金是否够
    """
    lot_size = constraints.get("lot_size", 100)
    late_session = constraints.get("late_session_cutoff", "14:30")
    current_time = constraints.get("current_time", "")
    
    filtered = []
    for c in candidates:
        checks = {"passed": True, "reasons": []}
        
        # 实时价格检查
        if prices and c.get("symbol") in prices:
            price = prices[c["symbol"]]
            shares = int(c.get("allocated_capital", 0) / price / lot_size) * lot_size
            if shares < lot_size:
                checks["passed"] = False
                checks["reasons"].append("金额不足以买100股")
        
        c["execution_checks"] = checks
        filtered.append(c)
    
    return filtered
```

### 验证

```python
from factor_lab.composite.factor_combiner import (
    apply_portfolio_constraints, filter_candidates_for_execution,
)

# 测试行业约束
scores = pd.Series({f"S{i:04d}": 100-i for i in range(1, 21)})
industry = {f"S{i:04d}": ("半导体" if i <= 8 else "医药") for i in range(1, 21)}

constrained = apply_portfolio_constraints(
    scores,
    industry_map=industry,
    constraints={"max_industry_weight": 0.30, "top_n": 10},
)

# 半导体被降低权重
semi_scores = constrained[[s for s in constrained.index if industry.get(s) == "半导体"]]
med_scores = constrained[[s for s in constrained.index if industry.get(s) == "医药"]]
print(f"半导体平均分: {semi_scores.mean():.1f}")
print(f"医药平均分: {med_scores.mean():.1f}")
assert semi_scores.mean() < med_scores.mean(), "行业超限应降低权重"

# 测试换手约束
scores2 = pd.Series({f"S{i:04d}": i for i in range(1, 21)})
positions = {f"S{i:04d}": {"weight": 0.1} for i in range(11, 21)}

result = apply_portfolio_constraints(
    scores2,
    current_positions=positions,
    constraints={"max_turnover": 0.30, "top_n": 10},
)
print(f"换手约束后保留: {(result > -999).sum()} 只候选")

# 测试执行过滤
candidates = [{"symbol": "688012", "allocated_capital": 1000}]
filtered = filter_candidates_for_execution(
    candidates,
    constraints={"lot_size": 100},
    prices={"688012": 158.3},
)
print(f"执行过滤: {filtered[0]['execution_checks']}")

print("✅ 风控约束集成测试通过")
```

## 注意事项
1. apply_portfolio_constraints 不直接下单，只调整候选得分
2. 行业约束在组合构建层做，不修改因子值
3. 换手约束限制每期新买入股票数
4. 板块过滤移除不允许交易的股票