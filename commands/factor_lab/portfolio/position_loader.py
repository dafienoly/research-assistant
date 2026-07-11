"""持仓加载与校验"""
import csv
import json
import os
from datetime import timezone, timedelta

CST = timezone(timedelta(hours=8))

POSITION_FIELDS = ["symbol", "name", "shares", "available_shares", "cost_price",
                   "current_price", "market_value", "weight", "board", "source", "updated_at"]


class PositionLoader:
    def __init__(self, path: str = None):
        self.positions = []
        self.cash = 0.0
        self.warnings = []
        self.errors = []
        self.partial = False

    def load_csv(self, path: str) -> list:
        """从 CSV 加载持仓"""
        if not os.path.exists(path):
            self.errors.append(f"文件不存在: {path}")
            return []

        rows = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        return self._validate(rows, "csv")

    def load_json(self, path: str) -> list:
        if not os.path.exists(path):
            self.errors.append(f"文件不存在: {path}")
            return []
        with open(path) as f:
            data = json.load(f)
        return self._validate(data, "json")

    def from_qmt(self, connect_if_needed: bool = True) -> list:
        """通过统一 QMT Bridge 拉取实时持仓（只读）。

        需要:
            - QMT 客户端在本地运行
            - pip install xtquant -i https://pypi.org/simple

        QMT 不可用时记录显式错误，禁止静默空持仓。
        """
        try:
            from factor_lab.broker.miniqmt_position_adapter import MiniQMTPositionAdapter

            del connect_if_needed  # QMT Bridge owns connection lifecycle and health checks
            adapter = MiniQMTPositionAdapter()
            positions = adapter.normalize_positions(adapter.load_positions())
            if not positions:
                raise RuntimeError("QMT Bridge returned an empty position response")
            return self._validate(positions, "qmt_bridge")
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as exc:
            self.errors.append(f"QMT Bridge 持仓读取失败: {exc}")
            self.partial = True
            return []

    def _validate(self, rows: list, source: str) -> list:
        """校验持仓字段"""
        validated = []
        for i, row in enumerate(rows):
            sym = row.get("symbol", "")
            if not sym:
                self.warnings.append(f"第{i+1}行缺少 symbol")
                continue

            # shares 校验
            try:
                shares = int(float(row.get("shares", 0)))
                if shares % 100 != 0:
                    self.warnings.append(f"{sym}: shares={shares} 不是100的整数倍")
                row["shares"] = shares
            except (ValueError, TypeError):
                self.errors.append(f"{sym}: shares 格式错误")
                self.partial = True
                continue

            # available_shares
            try:
                avail = int(float(row.get("available_shares", shares)))
                if avail > shares:
                    self.warnings.append(f"{sym}: available_shares>{shares}")
                row["available_shares"] = avail
            except (ValueError, TypeError):
                row["available_shares"] = shares

            # current_price
            try:
                row["current_price"] = float(row.get("current_price", 0))
            except (ValueError, TypeError):
                self.errors.append(f"{sym}: current_price 格式错误")
                self.partial = True

            # market_value 校验
            if "market_value" in row and row["market_value"]:
                try:
                    mv = float(row["market_value"])
                    expected = shares * float(row.get("current_price", 0))
                    if abs(mv - expected) > expected * 0.01:
                        self.warnings.append(f"{sym}: market_value {mv} ≠ shares*price {expected:.0f}")
                except (ValueError, TypeError):
                    pass

            validated.append(row)

        # 现金
        for row in rows:
            if row.get("symbol", "").upper() == "CASH":
                try:
                    self.cash = float(row.get("market_value", row.get("shares", 0)))
                except (ValueError, TypeError):
                    pass

        if self.warnings:
            self.partial = True
        return validated
