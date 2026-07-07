"""持仓加载与校验"""
import csv, json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

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
        """从 QMT 客户端拉取实时持仓（只读）

        需要:
            - QMT 客户端在本地运行
            - pip install xtquant -i https://pypi.org/simple

        无 QMT 时返回空列表，不报错。
        """
        try:
            from factor_lab.miniqmt import connect, query_positions, query_account

            if connect_if_needed:
                connect()

            positions = query_positions()
            account = query_account()

            if positions:
                self.cash = account.get("cash", 0)
                return self._validate(positions, "qmt")

            self.warnings.append("QMT 未返回持仓数据（客户端未运行或未登录）")
            return []
        except ImportError:
            self.warnings.append("xtquant 未安装，无法连接 QMT")
            return []
        except Exception as e:
            self.errors.append(f"QMT 连接异常: {e}")
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
                except:
                    pass

            validated.append(row)

        # 现金
        for row in rows:
            if row.get("symbol", "").upper() == "CASH":
                try:
                    self.cash = float(row.get("market_value", row.get("shares", 0)))
                except:
                    pass

        if self.warnings:
            self.partial = True
        return validated
