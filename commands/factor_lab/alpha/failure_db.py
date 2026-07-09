"""V3.6.1 因子失败归因数据库

记录每个被淘汰/失败因子的：
- factor_name, expression, hypothesis（原始信息）
- rejection_reason（IC衰减/跑输等权/过拟合/placebo fail）
- ic_decay_curve（各窗口 IC 序列）
- market_regime（运行期间市场状态）
- failed_at（退役时间）
- created_by（LLM/manual）

持久化到 /mnt/d/HermesData/alpha_failures/
支持按原因/市场状态查询
"""

import json
import os
import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict

CST = timezone(timedelta(hours=8))
FAILURE_DIR = Path("/mnt/d/HermesData/alpha_failures")


# ═══════════════════════════════════════════════════════════════════
# FailureRecord — 单条失败记录的数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FailureRecord:
    """单条因子失败归因记录"""
    factor_name: str = ""
    expression: str = ""
    hypothesis: str = ""
    rejection_reason: str = ""       # ic_decay / not_beat_peer / overfit / placebo_fail / unknown
    ic_decay_curve: dict = field(default_factory=dict)  # {"1D": 0.03, "5D": 0.01, ...}
    market_regime: str = ""          # bullish / bearish / oscillating / structural / unknown
    failed_at: str = ""
    created_by: str = "unknown"
    alpha_id: str = ""
    details: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# FailureDatabase — 因子失败归因数据库
# ═══════════════════════════════════════════════════════════════════


class FailureDatabase:
    """因子失败归因数据库

    append-only 持久化存储，每个失败记录保存在独立目录。
    支持按原因 / 市场状态查询，提供 LLM 友好的汇总输出。

    用法:
        db = FailureDatabase()
        db.record_failure(FailureRecord(...))
        db.query_by_reason("ic_decay")
        db.get_summary()
        db.get_recent_failures(10)  # 可直接嵌入 LLM prompt
    """

    def __init__(self, root: Optional[str | Path] = None):
        self.root = Path(root) if root else FAILURE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_file = self.root / "failures_index.json"
        self._load_index()

    # ── 索引管理 ──────────────────────────────────────────────

    def _load_index(self):
        if self.index_file.exists():
            self.index = json.loads(self.index_file.read_text())
        else:
            self.index = {}

    def _save_index(self):
        self.index_file.write_text(
            json.dumps(self.index, indent=2, ensure_ascii=False)
        )

    # ── 记录写入 ──────────────────────────────────────────────

    def record_failure(self, record: FailureRecord) -> str:
        """记录因子失败

        参数:
            record: FailureRecord 实例

        返回:
            failure_id: str — 可用于后续查询的唯一标识
        """
        now = datetime.now(CST)
        failure_id = (
            f"fail_{record.factor_name or 'unnamed'}_"
            f"{now.strftime('%Y%m%d_%H%M%S')}"
        )
        record.failed_at = now.isoformat()

        # 保存到独立目录（方便扩展元数据、附件等）
        record_dir = self.root / failure_id
        record_dir.mkdir(parents=True, exist_ok=True)

        (record_dir / "failure_record.json").write_text(
            json.dumps(asdict(record), indent=2, ensure_ascii=False)
        )

        # 更新索引
        self.index[failure_id] = {
            "failure_id": failure_id,
            "factor_name": record.factor_name,
            "rejection_reason": record.rejection_reason,
            "failed_at": record.failed_at,
            "market_regime": record.market_regime,
            "created_by": record.created_by,
            "alpha_id": record.alpha_id,
        }
        self._save_index()

        return failure_id

    def record_from_retirement(
        self,
        alpha_id: str,
        spec: dict,
        reason: str = "",
        ic_data: Optional[dict] = None,
    ) -> str:
        """从 RetirementEngine 退役时自动记录失败归因

        参数:
            alpha_id: 被退役的 Alpha ID
            spec: Alpha spec 字典 (来自 get_alpha)
            reason: 退役原因文本
            ic_data: 可选的 IC 数据字典，自动从 spec 提取 IC 历史

        返回:
            failure_id: str
        """
        # 从 spec 提取 IC 历史
        ic_curve = ic_data or {}
        if not ic_curve:
            ic_history = spec.get("ic_mean_history", [])
            if ic_history and isinstance(ic_history, list):
                for entry in ic_history:
                    if isinstance(entry, dict):
                        for k, v in entry.items():
                            if isinstance(v, (int, float)):
                                ic_curve[k] = v

        record = FailureRecord(
            factor_name=spec.get("name", alpha_id),
            expression=spec.get("factor_expression", ""),
            hypothesis=spec.get("hypothesis", ""),
            rejection_reason=self._classify_reason(reason, ic_curve),
            ic_decay_curve=ic_curve,
            market_regime=self._detect_market_regime(),
            created_by=spec.get("source", "unknown"),
            alpha_id=alpha_id,
            details={
                "original_reason": reason,
                "previous_status": spec.get("status", ""),
            },
        )
        return self.record_failure(record)

    # ── 自动分类 ──────────────────────────────────────────────

    def _classify_reason(self, reason: str, ic_data: Optional[dict] = None) -> str:
        """根据退役原因文本自动分类失败原因"""
        reason_lower = reason.lower()

        # 检查 IC 衰减
        if ("ic" in reason_lower and "decay" in reason_lower) or "衰减" in reason_lower:
            return "ic_decay"

        # 检查跑输等权
        if "peer" in reason_lower or "等权" in reason_lower or "benchmark" in reason_lower:
            return "not_beat_peer"

        # 检查过拟合
        if "overfit" in reason_lower or "过拟合" in reason_lower:
            return "overfit"

        # 检查 placebo
        if "placebo" in reason_lower:
            return "placebo_fail"

        # 如果 IC 数据中有明显的衰减模式
        if ic_data and isinstance(ic_data, dict):
            values = [v for v in ic_data.values() if isinstance(v, (int, float))]
            if len(values) >= 2:
                # 短期 > 中期 > 长期 的趋势表明衰减
                if values[0] > 0 and values[-1] < values[0] * 0.5:
                    return "ic_decay"

        return "unknown"

    def _detect_market_regime(self) -> str:
        """检测当前市场状态（轻量实现）

        尝试从基准指数最近 60 个交易日判断市场状态。
        如果不可用，返回 unknown。
        """
        try:
            import numpy as np

            # 尝试加载基准指数数据
            try:
                from factor_lab.portfolio.benchmark import (
                    get_benchmark_returns,
                    make_benchmark_spec,
                )
                bench = get_benchmark_returns(make_benchmark_spec("CSI300"))
            except ImportError:
                # 降级：尝试通过 mx-data 获取
                bench = None
                try:
                    from mx_data import mx_data
                    df = mx_data.get_index_daily(
                        index_code="000300.SH",
                        count=60,
                        fields=["trade_date", "pct_chg"],
                    )
                    if df is not None and not df.empty:
                        returns = df["pct_chg"].values / 100.0
                        # 构造一个类似 Series
                        class _Series:
                            def __init__(self, data):
                                self._data = data
                            def tail(self, n):
                                return _Series(self._data[-n:])
                            def __len__(self):
                                return len(self._data)
                            def prod(self):
                                p = 1.0
                                for v in self._data:
                                    p *= 1 + v
                                return p - 1
                        bench = _Series(returns)
                except Exception:
                    bench = None

            if bench is None or (hasattr(bench, "__len__") and len(bench) < 20):
                return "unknown"

            if hasattr(bench, "tail"):
                recent = bench.tail(min(60, len(bench)))
            else:
                recent = bench

            if hasattr(recent, "prod"):
                cum = recent.prod()
            else:
                # 手动计算
                arr = recent if isinstance(recent, (list, tuple)) else list(recent)
                cum = 1.0
                for v in arr:
                    cum *= 1 + float(v)
                cum -= 1

            if cum > 0.05:
                return "bullish"
            if cum < -0.05:
                return "bearish"
            return "oscillating"

        except Exception:
            return "unknown"

    # ── 查询接口 ──────────────────────────────────────────────

    def query_by_reason(self, reason: str) -> List[dict]:
        """按失败原因查询

        参数:
            reason: 原因类型 (ic_decay / not_beat_peer / overfit / placebo_fail / unknown)

        返回:
            匹配的索引条目列表
        """
        return [
            v for v in self.index.values()
            if v.get("rejection_reason") == reason
        ]

    def query_by_regime(self, regime: str) -> List[dict]:
        """按市场环境查询

        参数:
            regime: 市场状态 (bullish / bearish / oscillating / structural / unknown)

        返回:
            匹配的索引条目列表
        """
        return [
            v for v in self.index.values()
            if v.get("market_regime") == regime
        ]

    def get_failure(self, failure_id: str) -> Optional[dict]:
        """获取单条失败完整记录"""
        record_dir = self.root / failure_id
        record_path = record_dir / "failure_record.json"
        if record_path.exists():
            return json.loads(record_path.read_text())
        return None

    def get_summary(self) -> dict:
        """获取汇总统计

        返回:
            {
                "total_failures": int,
                "by_reason": {"ic_decay": 3, ...},
                "by_regime": {"bearish": 2, ...},
                "latest_failure": str,
            }
        """
        reasons: Dict[str, int] = {}
        regimes: Dict[str, int] = {}
        latest = ""

        for v in self.index.values():
            r = v.get("rejection_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1

            rg = v.get("market_regime", "unknown")
            regimes[rg] = regimes.get(rg, 0) + 1

            ts = v.get("failed_at", "")
            if ts > latest:
                latest = ts

        return {
            "total_failures": len(self.index),
            "by_reason": reasons,
            "by_regime": regimes,
            "latest_failure": latest,
        }

    def get_recent_failures(self, n: int = 10) -> List[dict]:
        """获取最近的 N 个失败记录（输出格式可直接用于 LLM prompt）

        按失败时间降序排列，返回索引摘要信息。
        """
        sorted_items = sorted(
            self.index.values(),
            key=lambda x: x.get("failed_at", ""),
            reverse=True,
        )
        return sorted_items[:n]

    def get_failures_for_llm(self, n: int = 10) -> str:
        """生成 LLM 友好的失败模式反馈文本

        直接嵌入 LLM prompt 使用：
            f"以下是最近失败因子记录:\\n{db.get_failures_for_llm()}"
        """
        recent = self.get_recent_failures(n)
        if not recent:
            return "（暂无失败记录）"

        lines = ["=== 因子失败归因反馈 ==="]
        for r in recent:
            lines.append(
                f"- {r['factor_name']} | "
                f"原因: {r['rejection_reason']} | "
                f"市场: {r['market_regime']} | "
                f"时间: {r['failed_at'][:19]}"
            )

        # 附上汇总
        summary = self.get_summary()
        lines.append("---")
        lines.append(
            f"总计: {summary['total_failures']} 次失败 | "
            f"按原因: {summary['by_reason']} | "
            f"按市场: {summary['by_regime']}"
        )

        return "\n".join(lines)

    # ── 导出 ──────────────────────────────────────────────────

    def export_csv(self, output_path: Optional[str] = None) -> str:
        """导出失败记录为 CSV"""
        if output_path is None:
            output_path = str(self.root / "failure_export.csv")

        fieldnames = [
            "failure_id", "factor_name", "rejection_reason",
            "market_regime", "failed_at", "created_by", "alpha_id",
        ]
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for v in self.index.values():
                w.writerow(v)

        return output_path
