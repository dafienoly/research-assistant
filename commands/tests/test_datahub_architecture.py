"""Architecture gate: downstream runtime modules must consume DataHub, not providers."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOTS = (
    ROOT / "commands/factor_lab/decision_loop",
    ROOT / "commands/factor_lab/api_server",
)
PROHIBITED_MODULES = {
    "akshare",
    "baostock",
    "tushare",
    "factor_lab.data.tushare_client",
    "eastmoney_direct",
    "provider_matrix",
    "rsscast_mcp",
}


def provider_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name in PROHIBITED_MODULES or any(name.startswith(f"{item}.") for item in PROHIBITED_MODULES):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
    return found


def test_runtime_modules_do_not_bypass_datahub():
    violations = []
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*.py"):
            violations.extend(provider_imports(path))
    assert violations == [], "runtime provider bypasses:\n" + "\n".join(violations)


def test_vnext_and_decision_loop_do_not_implement_notification_networking():
    violations = []
    for root in (ROOT / "commands/factor_lab/vnext", ROOT / "commands/factor_lab/decision_loop"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(name.startswith(("urllib", "requests", "httpx")) for name in names):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{','.join(names)}")
    assert violations == [], "notification transport bypasses:\n" + "\n".join(violations)


def test_vnext_event_truth_is_read_only_datahub_consumer():
    path = ROOT / "commands/factor_lab/vnext/event_truth_sources.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "data/normalized/events/event_truth" in source
    assert "._query(" not in source


def test_vnext_policy_dataset_is_read_only_datahub_consumer():
    path = ROOT / "commands/factor_lab/vnext/datasets.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "data/normalized/market_series" in source
    assert "get_ts_client" not in source


def test_vnext_snapshot_is_read_only_datahub_consumer():
    path = ROOT / "commands/factor_lab/vnext/snapshot.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "market_series_root" in source
    assert "TushareFetcher" not in source
    assert "get_ts_client" not in source


def test_vnext_provider_router_has_no_structured_market_provider_client():
    path = ROOT / "commands/factor_lab/vnext/providers.py"
    source = path.read_text(encoding="utf-8")
    assert "class TushareFetcher" not in source
    assert "client._query" not in source


def test_universe_builders_are_read_only_datahub_consumers():
    path = ROOT / "commands/universes.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "UniverseDataHubSnapshot" in source
    assert "get_ts_client" not in source
    assert "._query(" not in source
    assert "requests." not in source


def test_intraday_monitor_is_read_only_datahub_consumer():
    path = ROOT / "commands/intraday_monitor.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "read_live_snapshot" in source
    assert "fetch_stock_prices" not in source
    assert "fetch_sina_quotes" not in source
    assert "stock_zh_a_spot_em" not in source


def test_etf_dive_warning_is_read_only_datahub_consumer():
    path = ROOT / "commands/etf_dive_warning.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "read_live_snapshot" in source
    assert "fund_etf_spot_em" not in source
    assert "subprocess.run" not in source
    assert "mx.py" not in source


def test_monitor_588710_quote_path_is_read_only_datahub_consumer():
    path = ROOT / "commands/monitor_588710.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_quotes")
    quote_source = ast.get_source_segment(source, function) or ""
    assert "read_live_snapshot" in quote_source
    assert "EastmoneyProvider" not in quote_source
    assert "fetch_stock_prices" not in quote_source
    assert "SinaProvider" not in quote_source
    assert "requests.get" not in quote_source

    for function_name in ("_load_holdings", "get_north_flow", "get_kospi"):
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
        function_source = ast.get_source_segment(source, function) or ""
        assert "read_" in function_source or "DataHub" in function_source
        assert "subprocess.run" not in function_source
        assert "akshare" not in function_source
        assert "get_ts_client" not in function_source


def test_dive_live_predictor_is_read_only_datahub_consumer():
    path = ROOT / "commands/dive_prediction/live_predictor.py"
    assert provider_imports(path) == []
    source = path.read_text(encoding="utf-8")
    assert "read_live_snapshot" in source
    assert "urllib.request" not in source
    assert "qt.gtimg.cn" not in source
    assert "os.environ.pop" not in source
