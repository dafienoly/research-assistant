"""Durable official A-share limit/suspension/dividend/adjustment truth registry."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


class EventTruthSourceBuilder:
    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.output_root = self.root / "data/vnext/event-truth"

    def fetch(self, symbols: list[str], start_date: str, end_date: str) -> dict:
        from factor_lab.data.tushare_client import get_ts_client

        client = get_ts_client()
        results = []
        for symbol in symbols:
            datasets = {}
            errors = []
            for dataset, api_name, fields in (
                ("stk_limit", "stk_limit", "ts_code,trade_date,up_limit,down_limit"),
                ("suspend_d", "suspend_d", "ts_code,trade_date,suspend_type"),
                ("adj_factor", "fund_adj", "ts_code,trade_date,adj_factor"),
                ("dividend", "fund_div", "ts_code,ex_date,div_cash,div_proc"),
            ):
                try:
                    params = {"ts_code": symbol, "fields": fields}
                    if dataset != "dividend":
                        params.update({"start_date": start_date, "end_date": end_date})
                    frame = client._query(api_name, **params)
                    datasets[dataset] = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
                except Exception as exc:
                    datasets[dataset] = pd.DataFrame()
                    errors.append({"dataset": dataset, "api_name": api_name, "error": type(exc).__name__})
            merged = self._merge(datasets, start_date, end_date)
            destination = self.output_root / f"{symbol}.csv"
            destination.parent.mkdir(parents=True, exist_ok=True)
            merged.to_csv(destination, index=False, encoding="utf-8-sig")
            results.append({
                "symbol": symbol,
                "path": str(destination),
                "rows": len(merged),
                "coverage": {name: len(frame) for name, frame in datasets.items()},
                "errors": errors,
                "status": "OK" if not errors and len(datasets["stk_limit"]) > 0 and len(datasets["adj_factor"]) > 0 else "PARTIAL",
            })
        manifest = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "source": "tushare_official_structured_gateway",
            "start_date": start_date,
            "end_date": end_date,
            "results": results,
            "status": "OK" if results and all(row["status"] == "OK" for row in results) else "PARTIAL",
            "conflict_policy": "retain source observation; never replace with calculated values",
        }
        path = self.output_root / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    @staticmethod
    def _merge(datasets: dict[str, pd.DataFrame], start_date: str, end_date: str) -> pd.DataFrame:
        dates = pd.DataFrame({"trade_date": pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date), freq="D").strftime("%Y%m%d")})
        for name in ("stk_limit", "suspend_d", "adj_factor"):
            frame = datasets[name].copy()
            if frame.empty or "trade_date" not in frame:
                continue
            keep = [column for column in frame.columns if column != "ts_code"]
            dates = dates.merge(frame[keep].drop_duplicates("trade_date", keep="last"), on="trade_date", how="left")
        dividend = datasets["dividend"].copy()
        if not dividend.empty and "ex_date" in dividend:
            dividend = dividend.rename(columns={"ex_date": "trade_date"})
            if "div_cash" in dividend:
                dividend = dividend.rename(columns={"div_cash": "cash_div"})
            keep = [column for column in dividend.columns if column != "ts_code"]
            dates = dates.merge(dividend[keep].drop_duplicates("trade_date", keep="last"), on="trade_date", how="left")
        dates["source_provider"] = "tushare"
        dates["observed_at"] = datetime.now().astimezone().isoformat()
        return dates


def load_event_truth(project_root: Path, symbol: str) -> pd.DataFrame:
    path = project_root / "data/vnext/event-truth" / f"{symbol}.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, dtype={"trade_date": str})
    if frame.empty or "trade_date" not in frame:
        return pd.DataFrame()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
    return frame.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last").set_index("trade_date")
