"""VNext evidence-first premarket report renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import DataStatus, now_iso


def _payload(component: Mapping[str, Any]) -> Mapping[str, Any]:
    return component.get("payload", component)


def _value(component: Mapping[str, Any], key: str, default: Any = "MISSING") -> Any:
    value = _payload(component).get(key)
    return default if value is None else value


class VNextReportRenderer:
    def render(self, bundle: Mapping[str, Any]) -> str:
        as_of = str(bundle.get("as_of", "unknown"))
        policy = bundle.get("policy_put", {})
        semi = bundle.get("semi_mainline", {})
        regime = bundle.get("regime", {})
        portfolio = bundle.get("portfolio_risk", {})
        candidates = bundle.get("candidates", {})
        data_health = bundle.get("data_health", {})
        execution = bundle.get("execution_status", {})
        policy_payload = _payload(policy)
        semi_payload = _payload(semi)
        regime_payload = _payload(regime)
        portfolio_payload = _payload(portfolio)
        missing = sorted(
            set(policy.get("missing_evidence", []))
            | set(semi.get("missing_evidence", []))
            | set(regime.get("missing_evidence", []))
            | set(portfolio.get("missing_evidence", []))
        )
        evidence = policy.get("evidence", []) + semi.get("evidence", []) + regime.get("evidence", [])
        lines = [
            f"# Hermes VNext 盘前报告 — {as_of}",
            "",
            "> 研究结论与交易动作严格分离。本报告不会触发真实委托；所有 live 路径受 no_live_trade、Kill Switch 与 Telegram 审批约束。",
            "",
            "## 一页决策摘要",
            "",
            f"- 数据状态：`{data_health.get('status', 'MISSING')}`；交易模式：`{execution.get('trading_mode', 'READ_ONLY')}`；no_live_trade：`{execution.get('no_live_trade', True)}`。",
            f"- 当前 Regime：`{regime_payload.get('regime_name', 'MISSING')}`，置信度 `{regime.get('confidence', 0):.2f}`。",
            f"- 半导体主线：`{semi_payload.get('state', 'MISSING')}`，动作偏置 `{semi_payload.get('recommended_action_bias', 'watch_only')}`，置信度 `{semi.get('confidence', 0):.2f}`。",
            f"- 指数箱体：`{policy_payload.get('index_zone', 'MISSING')}`，位置 `{policy_payload.get('index_box_position')}`。",
            f"- 政策托底代理：`{policy_payload.get('policy_support_proxy_score')}`；广度背离：`{policy_payload.get('breadth_divergence_score')}`；上沿派发风险：`{policy_payload.get('upper_box_distribution_risk')}`。",
            f"- 允许新开仓：`{regime_payload.get('allow_new_buy', False)}`；允许隔夜：`{regime_payload.get('allow_overnight', False)}`。",
            f"- 假分散预警：`{portfolio_payload.get('false_diversification_warning', 'MISSING')}`；组合 Sharpe：`{portfolio_payload.get('portfolio_sharpe', 'MISSING')}`。",
            "",
            "## 20 项必答检查",
            "",
            f"1. 当前指数箱体位置：{policy_payload.get('index_box_position', 'MISSING')}（{policy_payload.get('index_zone', 'MISSING')}）。",
            f"2. 是否接近政策托底区：代理分数 {policy_payload.get('policy_support_proxy_score', 'MISSING')}，仅为可回测代理，不代表‘国家队’事实。",
            f"3. 是否接近上沿风险区：风险分数 {policy_payload.get('upper_box_distribution_risk', 'MISSING')}。",
            f"4. 市场广度是否与指数背离：{policy_payload.get('breadth_divergence_score', 'MISSING')}。",
            f"5. 半导体是否逆势走强：相对强度证据见状态机，当前状态 {semi_payload.get('state', 'MISSING')}。",
            f"6. 科技中军是否承接：{next((item for item in semi.get('evidence', []) if 'anchor_support' in item), 'MISSING')}。",
            f"7. 半导体主线状态：{semi_payload.get('state', 'MISSING')}。",
            f"8. 当前 Regime：{regime_payload.get('regime_name', 'MISSING')}。",
            f"9. 动作偏置：{semi_payload.get('recommended_action_bias', 'watch_only')}。",
            f"10. 是否建议个股：仅列研究候选；账户可交易候选 {len(_payload(candidates).get('account_tradable_candidates', []))} 个，仍需逐项风控。",
            f"11. 是否建议 ETF 替代：替代候选 {len(_payload(candidates).get('etf_substitution_candidates', []))} 个，均标记 substitution。",
            f"12. 是否建议港股科技：预算由 Regime 决定；无可交易权限/新鲜数据时仅 watch-only。",
            f"13. 是否需要红利/黄金/债券/现金防守：防守预算 {regime_payload.get('defensive_budget', 'MISSING')}，现金预算 {regime_payload.get('cash_budget', 'MISSING')}。",
            f"14. 新候选是否提高 Sharpe：{portfolio_payload.get('marginal_sharpe_contribution', 'MISSING')}。",
            f"15. 是否存在假分散：{portfolio_payload.get('false_diversification_warning', 'MISSING')}。",
            f"16. 支持证据：{'; '.join(evidence[:20]) if evidence else 'MISSING'}。",
            f"17. 缺失证据：{'; '.join(missing) if missing else '无'}。",
            f"18. 置信度：Regime {regime.get('confidence', 0):.2f}；半导体 {semi.get('confidence', 0):.2f}；政策代理 {policy.get('confidence', 0):.2f}。",
            f"19. 是否允许隔夜：{regime_payload.get('allow_overnight', False)}。",
            f"20. 是否允许新开仓：{regime_payload.get('allow_new_buy', False)}。",
            "",
            "## 风险与失效条件",
            "",
            "- 固定 3900/3950/4050/4100/4200 是用户假设阈值，必须与 60/120 日动态箱体做样本外比较，不能被视为永久规律。",
            "- MISSING / STALE / PARTIAL 数据会降低置信度；不会用 demo、mock 或其他数据源静默替换。",
            "- watch-only、创业板/科创板受限个股、海外代理不得进入账户可执行组合。",
            "- 没有真实持仓输入时不会生成 SELL 草案；所有草案必须具备 approval_id 和审计记录。",
            "",
            "## 数据来源与时间",
            "",
            f"```json\n{json.dumps(data_health, ensure_ascii=False, indent=2, default=str)}\n```",
            "",
            f"生成时间：{now_iso()}",
        ]
        return "\n".join(lines) + "\n"

    def write(self, bundle: Mapping[str, Any], path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(self.render(bundle), encoding="utf-8")
        temporary.replace(destination)
        return destination
