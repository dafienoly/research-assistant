"""CLI adapter for all Hermes VNext commands."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import PolicyHypothesisBacktester, RobustnessValidator
from .contracts import DataStatus, TradingMode
from .datasets import MLRankingDatasetBuilder, PolicyBacktestDatasetBuilder
from .execution import (
    AuditJournal,
    GovernedExecutionEngine,
    OrderDraft,
    PaperBroker,
    QMTProbeBroker,
    SafetyContext,
    ShadowBroker,
)
from .ml import CrossSectionalRanker, MLFactorSelector
from .review import AntifragileReviewEngine
from .service import VNextService
from .trading import PaperShadowLoop, summarize_execution_comparison


COMMANDS = {
    "portfolio:multi-regime",
    "strategy:policy-put",
    "semi:mainline-state",
    "ml:ranker-train",
    "ml:ranker-score",
    "trading:paper-run",
    "trading:shadow-run",
    "approval:telegram-test",
    "broker:qmt-probe",
    "review:antifragile",
    "report:vnext-premarket",
    "vnext:backtest-validate",
    "vnext:backtest-build",
    "vnext:ml-dataset-build",
}


def _arg(args: list[str], name: str, default: str | None = None) -> str | None:
    try:
        index = args.index(name)
    except ValueError:
        return default
    return args[index + 1] if index + 1 < len(args) else default


def _date(args: list[str]) -> str:
    return str(_arg(args, "--date", date.today().isoformat()))


def _project_path(value: str | None, project_root: Path) -> str | None:
    """Resolve CLI file arguments from the repository root.

    ``hermes_cli.py`` intentionally changes cwd to ``commands/`` for legacy
    imports.  VNext inputs are user-facing repository paths, so resolving
    relative values here keeps ``--input examples/...`` usable from the
    top-level CLI while preserving absolute paths unchanged.
    """
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else project_root / path)


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def handle(command: str, args: list[str]) -> bool:
    if command not in COMMANDS:
        return False
    if os.environ.get("HERMES_VNEXT_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        _print(
            {
                "status": DataStatus.BLOCKED.value,
                "component": "vnext",
                "reason": "HERMES_VNEXT_ENABLED=false",
                "no_live_trade": True,
                "real_broker_called": False,
            }
        )
        return True
    service = VNextService()
    as_of = _date(args)
    input_path = _project_path(_arg(args, "--input"), service.project_root)

    if command in {"portfolio:multi-regime", "strategy:policy-put", "semi:mainline-state", "report:vnext-premarket"}:
        bundle = service.run_daily(as_of, input_path=input_path)
        component = {
            "portfolio:multi-regime": "portfolio_risk",
            "strategy:policy-put": "policy_put",
            "semi:mainline-state": "semi_mainline",
            "report:vnext-premarket": "reports",
        }[command]
        _print(bundle.get(component, service.component(component.replace("_", "-"), as_of)))
        return True

    if command == "ml:ranker-train":
        training_path = Path(input_path or service.project_root / "data" / "vnext" / "ml" / "training.csv")
        if not training_path.exists():
            start = str(_arg(args, "--start", "2021-01-01"))
            end = str(_arg(args, "--end", as_of))
            scoring_path = service.project_root / "data" / "vnext" / "ml" / f"scoring_{as_of}.csv"
            max_symbols_text = _arg(args, "--max-symbols")
            built = MLRankingDatasetBuilder(service.project_root).build(
                start,
                end,
                training_path,
                scoring_path,
                max_symbols=int(max_symbols_text) if max_symbols_text else None,
            )
            if built.get("status") == DataStatus.MISSING.value:
                _print(built)
                return True
        frame = pd.read_csv(training_path)
        target_name = str(_arg(args, "--target", "forward_return"))
        date_name = str(_arg(args, "--date-column", "date"))
        symbol_name = str(_arg(args, "--symbol-column", "symbol"))
        excluded = {target_name, date_name, symbol_name}
        frame[date_name] = pd.to_datetime(frame[date_name], errors="coerce")
        start = _arg(args, "--start")
        end = _arg(args, "--end")
        if start:
            frame = frame[frame[date_name] >= pd.Timestamp(start)]
        if end:
            frame = frame[frame[date_name] <= pd.Timestamp(end)]
        if frame.empty:
            _print(service.store.missing("ml-ranker", as_of, "no training rows remain in the requested window"))
            return True
        features = [column for column in frame.columns if column not in excluded and pd.api.types.is_numeric_dtype(frame[column])]
        selector = MLFactorSelector().select(frame[features], frame[target_name])
        selected = selector["selected_factors"] or features
        ranker = CrossSectionalRanker(model_type=str(_arg(args, "--model", "ridge")))
        card = ranker.fit(frame[selected], frame[target_name], frame[date_name])
        card["factor_selection"] = selector
        card["training_data"] = str(training_path)
        model_path = service.store.root / "ml" / "models" / f"{card['model_version']}.joblib"
        artifact = ranker.save_model(model_path)
        card["model_artifact"] = artifact
        service.store.write("ml-ranker", as_of, card)
        registry_card = ranker.save_registry_entry(service.store.root / "ml" / "model_registry.json")
        registry_path = service.store.root / "ml" / "model_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        for item in registry.get("models", []):
            if item.get("model_version") == registry_card["model_version"]:
                item["model_artifact"] = artifact
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        _print(card)
        return True

    if command == "ml:ranker-score":
        scoring_path = Path(input_path or service.project_root / "data" / "vnext" / "ml" / f"scoring_{as_of}.csv")
        registry_path = service.store.root / "ml" / "model_registry.json"
        if not scoring_path.exists() or not registry_path.exists():
            reason = f"scoring data missing: {scoring_path}" if not scoring_path.exists() else "model registry missing"
            _print(service.store.missing("ml-ranker", as_of, reason))
            return True
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        models = registry.get("models", [])
        if not models:
            _print(service.store.missing("ml-ranker", as_of, "no registered model"))
            return True
        selected_model = models[-1]
        artifact = selected_model.get("model_artifact", {})
        ranker = CrossSectionalRanker.load_model(artifact["model_path"], expected_sha256=artifact.get("sha256"))
        frame = pd.read_csv(scoring_path)
        symbol_column = str(_arg(args, "--symbol-column", "symbol"))
        symbols = frame[symbol_column].astype(str).tolist() if symbol_column in frame else [str(i) for i in frame.index]
        scores = ranker.score(frame, symbols=symbols)
        card = ranker.model_card()
        payload = {
            "status": card["status"],
            "as_of": as_of,
            "confidence": card["confidence"],
            "risk_warning": card["risk_warning"],
            "model_card": card,
            "scores": scores,
            "direct_buy_sell_output": False,
            "input": str(scoring_path),
        }
        service.store.write("ml-ranker", as_of, payload)
        _print(payload)
        return True

    if command in {"trading:paper-run", "trading:shadow-run"}:
        orders_path = Path(input_path or service.store.root / "orders" / f"{as_of}.json")
        if not orders_path.exists():
            payload = service.store.missing("paper" if command.endswith("paper-run") else "shadow", as_of, f"order draft input missing: {orders_path}")
        else:
            raw = json.loads(orders_path.read_text(encoding="utf-8"))
            entries = raw.get("orders", []) if isinstance(raw, dict) else raw
            parsed = []
            for entry in entries:
                parsed.append((OrderDraft(**entry["order"]), SafetyContext(**entry["safety"])))
            mode = TradingMode.PAPER if command.endswith("paper-run") else TradingMode.SHADOW
            journal = AuditJournal(service.store.root / "audit" / "execution.jsonl")
            engine = GovernedExecutionEngine(mode, journal)
            broker = PaperBroker(journal) if mode == TradingMode.PAPER else ShadowBroker(journal)
            loop = PaperShadowLoop(engine, broker, lambda: parsed)
            cycles = int(_arg(args, "--cycles", "1") or 1)
            interval = int(_arg(args, "--interval", "60") or 60)
            runs = loop.run_continuous(interval_seconds=interval, max_cycles=cycles)
            payload = {
                "status": DataStatus.OK.value,
                "as_of": as_of,
                "mode": mode.value,
                "orders_path": str(orders_path),
                "cycles": runs,
                "comparison": summarize_execution_comparison(runs),
                "real_broker_called": False,
            }
        component = "paper" if command.endswith("paper-run") else "shadow"
        service.store.write(component, as_of, payload)
        _print(payload)
        return True

    if command == "approval:telegram-test":
        configured = service.execution_status(as_of)["telegram_configured"]
        result = {
            "status": DataStatus.OK.value if configured else DataStatus.MISSING.value,
            "dry_run": True,
            "credentials_configured": configured,
            "message": "Telegram test is approval-only and cannot execute an order",
            "pending_approvals": len(service.approvals.list()),
        }
        _print(result)
        return True

    if command == "broker:qmt-probe":
        try:
            from factor_lab.broker.qmt_client import QMTClient

            client = QMTClient()
        except Exception:
            client = None
        result = QMTProbeBroker(client).probe()
        result.update({"no_live_trade": True, "live_enabled": False, "real_broker_called": False})
        service.store.write("qmt-probe", as_of, result)
        _print(result)
        return True

    if command == "review:antifragile":
        review_path = Path(input_path or service.store.root / "review-inputs" / f"{as_of}.json")
        if not review_path.exists():
            payload = service.store.missing("antifragile-review", as_of, f"review input missing: {review_path}")
        else:
            event = json.loads(review_path.read_text(encoding="utf-8"))
            payload = AntifragileReviewEngine().review(event, as_of=as_of)
            AntifragileReviewEngine.append_training_sample(service.store.root / "review" / "training_samples.jsonl", payload)
        service.store.write("antifragile-review", as_of, payload)
        _print(payload)
        return True

    if command == "vnext:backtest-validate":
        backtest_path = Path(input_path or service.store.root / "backtest-inputs" / "policy_hypotheses.csv")
        if not backtest_path.exists():
            start = str(_arg(args, "--start", "2021-01-01"))
            built = PolicyBacktestDatasetBuilder(service.project_root).build(start, as_of, backtest_path)
            if built.get("status") == DataStatus.MISSING.value:
                payload = built
            else:
                payload = None
        else:
            payload = None
        if payload is None:
            frame = pd.read_csv(backtest_path)
            date_column = str(_arg(args, "--date-column", "date"))
            if date_column in frame:
                frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
                frame = frame.set_index(date_column).sort_index()
            targets = str(_arg(args, "--targets", "semiconductor,technology")).split(",")
            benchmarks = str(_arg(args, "--benchmarks", "csi300,csi500,csi1000,all_a,semi_etf,pool_equal,old_topn,cash")).split(",")
            requested_signals = _arg(args, "--signals")
            backtester = PolicyHypothesisBacktester()
            if requested_signals:
                payload = backtester.evaluate(
                    frame,
                    signal_columns=str(requested_signals).split(","),
                    target_columns=targets,
                    benchmark_columns=benchmarks,
                    as_of=as_of,
                    threshold_variant=str(_arg(args, "--threshold-variant", "custom")),
                )
            else:
                fixed = backtester.evaluate(
                    frame,
                    signal_columns=["policy_support_signal", "breadth_divergence_signal", "upper_box_risk_signal"],
                    target_columns=targets,
                    benchmark_columns=benchmarks,
                    as_of=as_of,
                    threshold_variant="fixed",
                )
                dynamic = backtester.evaluate(
                    frame,
                    signal_columns=["policy_support_dynamic_signal", "breadth_divergence_signal", "upper_box_dynamic_risk_signal"],
                    target_columns=targets,
                    benchmark_columns=benchmarks,
                    as_of=as_of,
                    threshold_variant="dynamic",
                )
                payload = dict(fixed)
                payload["hypothesis_results"] = fixed.get("hypothesis_results", []) + dynamic.get("hypothesis_results", [])
                payload["fixed_variant"] = fixed
                payload["dynamic_variant"] = dynamic
                payload["threshold_comparison"] = backtester.compare_threshold_variants(fixed, dynamic)
                if DataStatus.MISSING.value in {fixed.get("status"), dynamic.get("status")}:
                    payload["status"] = DataStatus.MISSING.value
                elif DataStatus.PARTIAL.value in {fixed.get("status"), dynamic.get("status")}:
                    payload["status"] = DataStatus.PARTIAL.value
            if "strategy_return" in frame.columns and "turnover" in frame.columns:
                available_benchmarks = {name: frame[name] for name in benchmarks if name in frame.columns}
                regimes = frame["regime"] if "regime" in frame.columns else None
                payload["robustness"] = RobustnessValidator().evaluate(
                    frame["strategy_return"],
                    available_benchmarks,
                    turnover=frame["turnover"],
                    regimes=regimes,
                )
            else:
                payload["robustness"] = {
                    "status": DataStatus.MISSING.value,
                    "missing_evidence": [column for column in ("strategy_return", "turnover") if column not in frame.columns],
                }
        service.store.write("backtests", as_of, payload)
        _print(payload)
        return True

    if command == "vnext:backtest-build":
        start = str(_arg(args, "--start", "2021-01-01"))
        output = Path(input_path or service.store.root / "backtest-inputs" / "policy_hypotheses.csv")
        _print(PolicyBacktestDatasetBuilder(service.project_root).build(start, as_of, output))
        return True

    if command == "vnext:ml-dataset-build":
        start = str(_arg(args, "--start", "2021-01-01"))
        end = str(_arg(args, "--end", as_of))
        training_path = service.project_root / "data" / "vnext" / "ml" / "training.csv"
        scoring_path = service.project_root / "data" / "vnext" / "ml" / f"scoring_{as_of}.csv"
        max_symbols_text = _arg(args, "--max-symbols")
        _print(
            MLRankingDatasetBuilder(service.project_root).build(
                start,
                end,
                training_path,
                scoring_path,
                max_symbols=int(max_symbols_text) if max_symbols_text else None,
            )
        )
        return True

    return True
