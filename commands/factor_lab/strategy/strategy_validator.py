"""策略验证引擎 (独立版)

运行每个策略 → 过滤因子构建 → 回测 → vs baseline 对比 → 评分
"""
import numpy as np
import pandas as pd
from factor_lab.metrics import compute_metrics


class StrategyValidator:
    def __init__(self, factor_df, close_pivot, backtester=None):
        self.factor_df = factor_df if "date" in factor_df.columns else factor_df.reset_index()
        self.close_pivot = close_pivot
        self.backtester = backtester
        self.canonical_baseline = None

    def validate_all(self, strategies: list) -> dict:
        results = []
        for spec in strategies:
            r = self.run_strategy(spec)
            results.append(r)
            m = r.get("metrics", {})
            beats = r.get("beats_baseline", False)
            icon = "✅" if beats else "❌"
            print(f"  {icon} {spec.name:30s} Sharpe={m.get('sharpe','?'):>7} 收益={m.get('cumulative_return_pct','?'):>7}%")
        best = max(results, key=lambda r: r.get("score", 0)) if results else None
        return {"strategies": results, "best_strategy": best["name"] if best else None}

    def run_strategy(self, spec) -> dict:
        filtered = self._build_filtered_factor(spec)
        col = f"_sv_{spec.name}"
        td = self.factor_df.copy()
        td[col] = filtered

        metrics = self._backtest(td, col, spec.top_n, spec.rebalance)
        vs = self._vs_canonical(metrics)
        beats = self._beats_baseline(vs, metrics)
        score = self._score(metrics, vs, [], False)

        return {"name": spec.name, "description": spec.description,
                "filter_type": spec.filter_type, "metrics": metrics,
                "vs_baseline": vs, "beats_baseline": beats, "score": score,
                "execution_log": [], "partial_validation": False}

    def _backtest(self, df, col, top_n=20, rebalance="monthly") -> dict:
        """独立回测, 不依赖 AShareBacktester"""
        dates = self.close_pivot.index
        dr = self.close_pivot.pct_change()
        rb = dates[dates.is_month_start] if rebalance == "monthly" else dates[dates.dayofweek == 0]
        rs = set(rb)
        rets = pd.Series(0.0, index=dates)
        pp = []
        tc = 0.0003 + 0.001 + 10 / 10000

        for d in dates:
            if d in rs:
                dd = df[df["date"] == d] if "date" in df.columns else df
                if col not in dd.columns:
                    rets[d] = 0; continue
                vv = dd.dropna(subset=[col])
                vv = vv[vv[col] > -998]
                n = min(top_n, len(vv))
                pp = list(vv.nlargest(n, col)["symbol"]) if n > 0 else pp

            if not pp:
                rets[d] = 0; continue

            av = [s for s in pp if s in dr.columns]
            ret = dr.loc[d, av].mean() if av else 0
            if d in rs:
                ret -= tc
            rets[d] = ret

        return compute_metrics(rets.fillna(0))

    def _build_filtered_factor(self, spec) -> pd.Series:
        df = self.factor_df
        p = spec.factor_names[0] if spec.factor_names else "ret5"
        if p not in df.columns:
            return pd.Series(0.0, index=df.index)
        ft = spec.filter_type

        if ft == "none":
            return df[p]
        elif ft == "gate":
            s = spec.factor_names[1] if len(spec.factor_names) > 1 else ""
            if s not in df.columns:
                return df[p]
            c = df[s] > spec.filter_params.get("gate_threshold", 0)
            r = df[p].copy(); r[~c.values] = -999; return r
        elif ft == "vol_filter":
            s = spec.factor_names[1] if len(spec.factor_names) > 1 else "volatility20"
            if s not in df.columns:
                return df[p]
            ep = spec.filter_params.get("exclude_top_pct", 0.2)
            rk = df.groupby("date")[s].rank(pct=True)
            r = df[p].copy(); r[rk > (1 - ep)] = -999; return r
        elif ft == "turn_filter":
            el = spec.filter_params.get("exclude_low_pct", 0.2)
            eh = spec.filter_params.get("exclude_high_pct", 0.95)
            if "amount_rank20" in df.columns:
                rk = df.groupby("date")["amount_rank20"].rank(pct=True)
            else:
                return df[p]
            r = df[p].copy(); r[rk < el] = -999; r[rk > eh] = -999; return r
        elif ft == "crowding_filter":
            s = spec.factor_names[1] if len(spec.factor_names) > 1 else "vol_ratio20"
            if s not in df.columns:
                return df[p]
            ep = spec.filter_params.get("exclude_top_pct", 0.2)
            rk = df.groupby("date")[s].rank(pct=True)
            r = df[p].copy(); r[rk > (1 - ep)] = -999; return r
        elif ft == "regime_filter":
            return df[p]
        elif ft == "combined":
            r = df[p].copy()
            if len(spec.factor_names) > 1 and spec.factor_names[1] in df.columns:
                c = df[spec.factor_names[1]] > 0; r[~c.values] = -999
            if "volatility20" in df.columns:
                vk = df.groupby("date")["volatility20"].rank(pct=True); r[vk > 0.8] = -999
            if "amount_rank20" in df.columns:
                ak = df.groupby("date")["amount_rank20"].rank(pct=True); r[ak < 0.2] = -999
            return r
        return df[p]

    def _vs_canonical(self, m: dict) -> dict:
        if not self.canonical_baseline:
            return {}
        b = self.canonical_baseline
        return {"return_delta": round(m.get("cumulative_return_pct", 0) - b.get("cumulative_return_pct", 0), 2),
                "max_drawdown_delta": round(m.get("max_drawdown_pct", 0) - b.get("max_drawdown_pct", 0), 2),
                "sharpe_delta": round(m.get("sharpe", 0) - b.get("sharpe", 0), 4)}

    def _beats_baseline(self, vs: dict, m: dict) -> bool:
        if not vs:
            return False
        # sharpe_delta > 0.03 = Sharpe提升;  max_drawdown_delta > 0.5 = 回撤改善(更接近0)
        return vs.get("sharpe_delta", 0) > 0.03 or vs.get("max_drawdown_delta", 0) > 0.5

    def _score(self, m, vs, logs, partial) -> float:
        if not vs:
            return 50
        s = 50 + max(min(vs.get("sharpe_delta", 0) * 50, 20), -20)
        s += max(min(-vs.get("max_drawdown_delta", 0) * 10, 15), -15)
        return max(0, min(s, 100))

    def run_parameter_sensitivity(self, spec, grid: dict) -> dict:
        results = []
        for pn, vals in grid.items():
            for v in vals:
                try:
                    from factor_lab.strategy.strategy_spec import StrategySpec
                    mod = StrategySpec(f"{spec.name}_{pn}={v}", spec.description,
                                       spec.factor_names.copy(), spec.filter_type,
                                       spec.filter_params.copy(), spec.top_n, spec.rebalance)
                    if pn == "top_n":
                        mod.top_n = v
                    elif pn == "rebalance":
                        mod.rebalance = v
                    r = self.run_strategy(mod)
                    mm = r.get("metrics", {})
                    results.append({"param": pn, "value": str(v), "sharpe": mm.get("sharpe"),
                                    "cumulative_return_pct": mm.get("cumulative_return_pct")})
                except Exception as e:
                    results.append({"param": pn, "value": str(v), "error": str(e)})
        return {"parameter": spec.name, "results": results}

    @staticmethod
    def sensitivity_grid() -> dict:
        return {"top_n": [10, 20, 30], "rebalance": ["weekly", "monthly"]}
