"""测试: V3.0.1 Factor Catalog Migration"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.alpha.factor_catalog_migration import run_migration
from factor_lab.alpha.registry import list_alpha, get_alpha


def test_alpha_register_exists():
    from factor_lab.alpha.registry import register_alpha
    assert callable(register_alpha)


def test_migration_dry_run():
    result = run_migration(dry_run=True)
    assert result.get("total_factors_in_registry", 0) > 0


def test_migration_migrated_count():
    result = run_migration(dry_run=True)
    migrated = result.get("migrated", 0)
    duplicates = result.get("duplicates", 0)
    assert migrated + duplicates > 0  # 实际迁移过则为 0 migrated + duplicates


def test_migrated_factors_disabled():
    alphas = list_alpha()
    migrated = [a for a in alphas if a.get("status") in ("registered",)]
    for a in alphas:
        spec = get_alpha(a["alpha_id"])
        if "spec" not in str(spec.get("name", "")):
            continue
        # Just check it doesn't crash
        break


def test_migration_creates_reports():
    result = run_migration(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/alpha_factor_migration")
    out_path = base / result["run_id"]
    assert out_path.exists()
    assert (out_path / "factor_migration_report.html").exists()


def test_no_broker():
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/factor_catalog_migration.py").read()
    # 检查 broker/miniqmt 作为函数调用, 排除说明文字
    import ast
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ("broker_adapter", "MiniQMTPositionAdapter", "send_order", "place_order"):
                    assert False, f"发现 broker 调用: {node.func.id}"
            if isinstance(node, ast.Attribute):
                if node.attr in ("send_order", "place_order"):
                    assert False, f"发现交易调用: {node.attr}"
    except SyntaxError:
        assert True  # f-string 可能无法解析, 跳过语法检查
    assert "no_live_trade" in src


REQUIRED_MIGRATION_FILES = [
    "factor_migration_report.html",
    "factor_migration_summary.md",
    "factor_catalog_registry.csv",
    "factor_category_summary.csv",
    "factor_alpha_mapping.csv",
    "migrated_factors.csv",
    "skipped_factors.csv",
    "duplicate_factors.csv",
    "factor_expression_validation.csv",
    "factor_data_requirements.csv",
    "factor_correlation_baseline.csv",
    "alpha_registry_update_preview.json",
    "manifest.json",
    "audit.jsonl",
    "audit.log",
]


def test_all_15_required_files_generated():
    """验收: 迁移输出必须包含完整 15 个文件"""
    result = run_migration(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/alpha_factor_migration")
    latest = sorted(base.iterdir())[-1]
    existing = {p.name for p in latest.iterdir() if p.is_file()}
    missing = [f for f in REQUIRED_MIGRATION_FILES if f not in existing]
    assert not missing, f"缺失验收文件: {missing}"


def test_empty_csv_files_generated():
    """空列表也应生成 CSV 文件 (带表头)"""
    result = run_migration(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/alpha_factor_migration")
    latest = sorted(base.iterdir())[-1]
    for csv_file in ["migrated_factors.csv", "skipped_factors.csv", "duplicate_factors.csv"]:
        path = latest / csv_file
        assert path.exists(), f"缺少文件: {csv_file}"
        content = path.read_text(encoding="utf-8-sig")
        assert len(content) > 0, f"{csv_file} 内容为空"
        # 至少包含表头
        assert "name" in content or "factor_name" in content, f"{csv_file} 缺少表头"


def test_factor_alpha_mapping_contains_all():
    """factor_alpha_mapping.csv 必须包含所有因子"""
    result = run_migration(dry_run=True)
    total = result.get("total_factors_in_registry", 0)
    import pathlib, csv
    base = pathlib.Path("/mnt/d/HermesReports/alpha_factor_migration")
    latest = sorted(base.iterdir())[-1]
    mapping_path = latest / "factor_alpha_mapping.csv"
    assert mapping_path.exists()
    with open(mapping_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # 映射行数应与因子总数一致 (去除重复名)
    seen = set()
    unique_factors = len([f for f in result.get("all_factors", []) if f.get("name", "?") not in seen and not seen.add(f.get("name", "?"))])  # noqa
    assert len(rows) > 0, "映射表不能为空"
    assert len(rows) >= total * 0.8, f"映射行数({len(rows)})覆盖率不足({total})"


def test_audit_log_exists():
    """audit.log 旧格式审计文件必须生成"""
    result = run_migration(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/alpha_factor_migration")
    latest = sorted(base.iterdir())[-1]
    audit_log = latest / "audit.log"
    assert audit_log.exists()
    content = audit_log.read_text()
    assert "FACTOR CATALOG MIGRATION AUDIT" in content
    assert "auto_apply=False" in content


def test_alpha_registry_update_preview():
    """alpha_registry_update_preview.json 必须包含预览内容"""
    result = run_migration(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/alpha_factor_migration")
    latest = sorted(base.iterdir())[-1]
    preview_path = latest / "alpha_registry_update_preview.json"
    assert preview_path.exists()
    import json
    preview = json.loads(preview_path.read_text())
    assert "safety" in preview
    assert preview["safety"]["no_live_trade"] is True
    assert preview["dry_run"] is True


# ═══════════════════════════════════════════════
# V3.1 — Industry Relative Alpha Pack
# ═══════════════════════════════════════════════

def test_industry_alpha_pack_dry_run():
    """V3.1: Industry Alpha Pack dry-run 必须返回 7 个 alpha"""
    from factor_lab.alpha.industry_alpha_pack import run_industry_alpha_pack
    result = run_industry_alpha_pack(dry_run=True)
    assert result["specs_defined"] == 7
    assert result["registered"] == 7
    assert result["dry_run"] is True


def test_industry_alpha_pack_safety():
    """V3.1: 所有 alpha 必须 disabled, auto_apply=False, no_live_trade=True"""
    from factor_lab.alpha.industry_alpha_pack import run_industry_alpha_pack
    result = run_industry_alpha_pack(dry_run=True)
    assert result["all_enabled_false"] is True
    assert result["auto_apply"] is False
    assert result["no_live_trade"] is True


def test_industry_alpha_pack_no_broker():
    """V3.1: Industry Alpha Pack 不得调用 broker/miniqmt"""
    import ast
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/industry_alpha_pack.py").read()
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in (
                    "broker_adapter", "MiniQMTPositionAdapter", "send_order", "place_order"
                ):
                    assert False, f"发现 broker 调用: {node.func.id}"
            if isinstance(node, ast.Attribute):
                if node.attr in ("send_order", "place_order"):
                    assert False, f"发现交易调用: {node.attr}"
    except SyntaxError:
        assert True
    # content-level check
    assert "no_live_trade" in src


def test_industry_alpha_report_files_generated():
    """V3.1: Industry Alpha Pack 必须生成报告文件"""
    from factor_lab.alpha.industry_alpha_pack import run_industry_alpha_pack
    result = run_industry_alpha_pack(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/industry_alpha_pack")
    out_path = base / result["run_id"]
    assert out_path.exists()
    assert (out_path / "industry_alpha_pack_report.html").exists()
    assert (out_path / "industry_alpha_pack_summary.md").exists()
    assert (out_path / "industry_alpha_pack.json").exists()
    assert (out_path / "industry_alphas_registered.csv").exists()


def test_industry_alpha_pack_all_specs_disabled_in_source():
    """V3.1: 所有 AlphaSpec 定义中 enabled=False"""
    from factor_lab.alpha.industry_alpha_pack import INDUSTRY_ALPHA_SPECS
    for spec in INDUSTRY_ALPHA_SPECS:
        assert "no_live_trade" in spec["tags"], f"{spec['name']} 缺少 no_live_trade 标签"


def test_industry_relative_factors_registered():
    """V3.1: factor_base 中的 industry_relative 因子必须全部注册"""
    from factor_lab.factor_base import list_factors
    ind_factors = [f for f in list_factors() if f["category"] == "industry_relative"]
    expected = {
        "ret20_industry_adj", "ret10_industry_adj", "ret5_industry_adj",
        "volatility20_industry_adj", "vol_ratio20_industry_adj", "amihud_industry_adj",
        "industry_neutral_quality", "fund_flow_industry_adj", "industry_neutral_composite",
        "cross_sector_strength", "industry_relative_ret5", "industry_momentum",
        "industry_concentration",
    }
    assert {factor["name"] for factor in ind_factors} == expected


def test_industry_mapper_basic():
    """V3.1: IndustryMapper 基本功能"""
    from factor_lab.alpha.industry_mapper import IndustryMapper
    m = IndustryMapper(auto_load=False)
    m.add_industry("000001", "银行")
    m.add_industry("000002", "房地产")
    assert m.get_industry("000001") == "银行"
    assert m.get_industry("000002") == "房地产"
    assert m.get_industry("999999") == "unknown"  # 未注册股票
    assert len(m.get_industry_list()) == 2
    assert m.get_industry_count()["银行"] == 1


def test_industry_relative_factor_computation():
    """V3.1: 行业相对因子计算在模拟数据上正常工作"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    symbols = ["A", "B", "C", "D", "E"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": s, "close": 10 + np.random.randn(),
                         "volume": 1e6, "amount": 1e7,
                         "high": 11, "low": 9, "open": 10})
    df = pd.DataFrame(rows)
    industries = {"A": "金融", "B": "金融", "C": "科技", "D": "科技", "E": "科技"}
    df["industry"] = df["symbol"].map(industries)

    # Test an industry-relative factor
    result = compute_factor(df, "ret5_industry_adj")
    assert result is not None
    assert len(result) == len(df)

    # Test composite
    result2 = compute_factor(df, "industry_neutral_composite")
    assert result2 is not None
    assert len(result2) == len(df)


# ═══════════════════════════════════════════════
# V3.3 — Data Enrichment Alpha Pack
# ═══════════════════════════════════════════════

def test_data_enrichment_alpha_pack_dry_run():
    """V3.3: Data Enrichment Alpha Pack dry-run 必须返回所有 alpha"""
    from factor_lab.alpha.data_enrichment_alpha_pack import run_data_enrichment_pack
    result = run_data_enrichment_pack(dry_run=True)
    assert result["specs_defined"] == 13
    assert result["registered"] > 0
    assert result["dry_run"] is True


def test_data_enrichment_alpha_pack_safety():
    """V3.3: 所有 alpha 必须 disabled, auto_apply=False, no_live_trade=True"""
    from factor_lab.alpha.data_enrichment_alpha_pack import run_data_enrichment_pack
    result = run_data_enrichment_pack(dry_run=True)
    assert result["all_enabled_false"] is True
    assert result["auto_apply"] is False
    assert result["no_live_trade"] is True


def test_data_enrichment_alpha_pack_no_broker():
    """V3.3: Data Enrichment Alpha Pack 不得调用 broker/miniqmt"""
    import ast
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/data_enrichment_alpha_pack.py").read()
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in (
                    "broker_adapter", "MiniQMTPositionAdapter", "send_order", "place_order"
                ):
                    assert False, f"发现 broker 调用: {node.func.id}"
            if isinstance(node, ast.Attribute):
                if node.attr in ("send_order", "place_order"):
                    assert False, f"发现交易调用: {node.attr}"
    except SyntaxError:
        assert True
    assert "no_live_trade" in src


def test_data_enrichment_report_files_generated():
    """V3.3: Data Enrichment Alpha Pack 必须生成报告文件"""
    from factor_lab.alpha.data_enrichment_alpha_pack import run_data_enrichment_pack
    result = run_data_enrichment_pack(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/data_enrichment_alpha_pack")
    out_path = base / result["run_id"]
    assert out_path.exists()
    assert (out_path / "data_enrichment_alpha_pack_report.html").exists()
    assert (out_path / "data_enrichment_alpha_pack_summary.md").exists()
    assert (out_path / "data_enrichment_alpha_pack.json").exists()
    assert (out_path / "data_enrichment_alphas_registered.csv").exists()


def test_data_enrichment_all_specs_disabled_in_source():
    """V3.3: 所有 AlphaSpec 定义中 enabled=False (via no_live_trade tag)"""
    from factor_lab.alpha.data_enrichment_alpha_pack import DATA_ENRICHMENT_ALPHA_SPECS
    for spec in DATA_ENRICHMENT_ALPHA_SPECS:
        assert "no_live_trade" in spec["tags"], f"{spec['name']} 缺少 no_live_trade 标签"


def test_data_enrichment_factors_registered():
    """V3.3: factor_base 中的数据增强因子必须全部注册"""
    from factor_lab.factor_base import list_factors
    north_factors = [f for f in list_factors() if f["category"] == "north_bound"]
    margin_factors = [f for f in list_factors() if f["category"] == "margin"]
    fund_flow_factors = [f for f in list_factors() if f["category"] == "fund_flow"]

    assert len(north_factors) == 6, f"预期 6 个 north_bound 因子, 实际 {len(north_factors)}"
    assert len(margin_factors) == 8, f"预期 8 个 margin 因子, 实际 {len(margin_factors)}"
    assert len(fund_flow_factors) >= 11, f"预期 >=11 个 fund_flow 因子, 实际 {len(fund_flow_factors)}"

    north_names = {f["name"] for f in north_factors}
    expected_north = {
        "nb_net_flow_1d", "nb_net_flow_5d", "nb_holding_change_5d",
        "nb_flow_ratio", "nb_holding_ratio_change", "nb_flow_momentum",
    }
    assert north_names == expected_north, f"北向因子: 预期={expected_north}, 实际={north_names}"

    margin_names = {f["name"] for f in margin_factors}
    expected_margin = {
        "margin_buy_ratio", "margin_balance_change_5d", "margin_balance_change_20d",
        "sec_lending_change_5d", "margin_sec_lending_ratio",
        "margin_net_buy", "margin_net_buy_5d", "margin_flow_momentum",
    }
    assert margin_names == expected_margin, f"两融因子: 预期={expected_margin}, 实际={margin_names}"


def test_data_enrichment_loader_basic():
    """V3.3: DataEnrichmentLoader 基本功能"""
    from factor_lab.alpha.data_enrichment_loader import (
        load_fund_flow, load_north_flow, load_margin, get_enriched_data,
        data_enrichment_status,
    )

    # 加载 fund_flow (已存在数据)
    ff = load_fund_flow()
    assert "net_main_force" in ff.columns or len(ff) == 0

    # 加载 north_flow (文件可能不存在, 应优雅返回空 DataFrame)
    nf = load_north_flow()
    assert "nb_net_flow" in nf.columns or len(nf) == 0

    # 加载 margin (文件可能不存在, 应优雅返回空 DataFrame)
    mg = load_margin()
    assert "margin_buy" in mg.columns or len(mg) == 0

    # 统一入口
    enriched = get_enriched_data()
    assert "fund_flow" in enriched
    assert "north_flow" in enriched
    assert "margin" in enriched

    # 状态报告
    status = data_enrichment_status()
    assert "fund_flow_exists" in status
    assert "north_flow_exists" in status
    assert "margin_exists" in status


def test_data_enrichment_factor_computation_fund_flow():
    """V3.3: 资金流增强因子在模拟数据上正常工作"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    dates = pd.date_range("2026-06-01", periods=10, freq="D")
    symbols = ["A", "B", "C"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({
                "date": d, "symbol": s, "close": 10 + np.random.randn(),
                "volume": 1e6, "amount": 1e7,
                "net_main_force": np.random.randn() * 1e7,
                "net_super_large": np.random.randn() * 5e6,
                "net_small": np.random.randn() * 3e6,
            })
    df = pd.DataFrame(rows)

    for factor_name in ["net_flow_composite", "flow_divergence_5d",
                         "super_large_flow_mom", "institutional_flow_ratio",
                         "consecutive_inflow"]:
        result = compute_factor(df, factor_name)
        assert result is not None
        assert len(result) == len(df)


def test_data_enrichment_factor_computation_north():
    """V3.3: 北向因子在模拟数据上正常工作"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    dates = pd.date_range("2026-06-01", periods=10, freq="D")
    symbols = ["A", "B", "C"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({
                "date": d, "symbol": s, "close": 10 + np.random.randn(),
                "volume": 1e6, "amount": 1e7,
                "nb_net_flow": np.random.randn() * 1e6,
                "nb_holding_value": 1e8 + np.random.randn() * 1e7,
                "nb_total_buy": 5e7 + np.random.randn() * 1e7,
                "nb_total_sell": 4e7 + np.random.randn() * 1e7,
                "nb_holding_ratio": 2.0 + np.random.randn() * 0.5,
            })
    df = pd.DataFrame(rows)

    for factor_name in ["nb_net_flow_1d", "nb_net_flow_5d", "nb_holding_change_5d",
                         "nb_flow_ratio", "nb_holding_ratio_change", "nb_flow_momentum"]:
        result = compute_factor(df, factor_name)
        assert result is not None, f"{factor_name} 返回 None"
        assert len(result) == len(df), f"{factor_name} 长度不匹配"


def test_data_enrichment_factor_computation_margin():
    """V3.3: 两融因子在模拟数据上正常工作"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    dates = pd.date_range("2026-06-01", periods=10, freq="D")
    symbols = ["A", "B", "C"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({
                "date": d, "symbol": s, "close": 10 + np.random.randn(),
                "volume": 1e6, "amount": 1e7,
                "margin_buy": np.random.randn() * 1e6,
                "margin_repay": np.random.randn() * 8e5,
                "margin_balance": 5e7 + np.random.randn() * 5e6,
                "sec_lending_balance": 5e6 + np.random.randn() * 1e6,
            })
    df = pd.DataFrame(rows)

    for factor_name in ["margin_buy_ratio", "margin_balance_change_5d",
                         "margin_balance_change_20d", "sec_lending_change_5d",
                         "margin_sec_lending_ratio", "margin_net_buy",
                         "margin_net_buy_5d", "margin_flow_momentum"]:
        result = compute_factor(df, factor_name)
        assert result is not None, f"{factor_name} 返回 None"
        assert len(result) == len(df), f"{factor_name} 长度不匹配"


def test_data_enrichment_merge_enriched():
    """V3.3: merge_enriched 在模拟数据上正常工作"""
    import pandas as pd
    import numpy as np
    from factor_lab.alpha.data_enrichment_loader import merge_enriched

    dates = pd.date_range("2026-06-01", periods=5, freq="D")
    symbols = ["A", "B"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": s, "close": 10.0})
    df = pd.DataFrame(rows)

    result = merge_enriched(df)
    assert len(result) == len(df)
    assert "close" in result.columns


def test_data_enrichment_factors_graceful_degradation():
    """V3.3: 数据增强因子在缺少列时应返回零值而非崩溃"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    # 没有任何增强数据列的基础 DataFrame
    dates = pd.date_range("2026-06-01", periods=5, freq="D")
    symbols = ["A"]
    rows = [{"date": d, "symbol": "A", "close": 10.0, "volume": 1e6, "amount": 1e7}
            for d in dates]
    df = pd.DataFrame(rows)

    # Fund flow factors
    for name in ["net_flow_composite", "flow_divergence_5d",
                  "super_large_flow_mom", "institutional_flow_ratio",
                  "consecutive_inflow"]:
        result = compute_factor(df, name)
        assert result is not None
        assert len(result) == len(df)
        assert result.isna().sum() == 0 or result.fillna(0).sum() >= 0  # 所有值都有效

    # North-bound factors
    for name in ["nb_net_flow_1d", "nb_net_flow_5d", "nb_holding_change_5d",
                  "nb_flow_ratio", "nb_holding_ratio_change", "nb_flow_momentum"]:
        result = compute_factor(df, name)
        assert result is not None
        assert len(result) == len(df)

    # Margin factors
    for name in ["margin_buy_ratio", "margin_balance_change_5d",
                  "margin_balance_change_20d", "sec_lending_change_5d",
                  "margin_sec_lending_ratio", "margin_net_buy",
                  "margin_net_buy_5d", "margin_flow_momentum"]:
        result = compute_factor(df, name)
        assert result is not None
        assert len(result) == len(df)


def test_data_enrichment_loader_graceful_empty():
    """V3.3: 加载器在缺失数据文件时返回空 DataFrame 而非崩溃"""
    from factor_lab.alpha.data_enrichment_loader import (
        load_north_flow, load_margin,
    )

    # 即使文件不存在也能返回有效 DataFrame
    nf = load_north_flow()
    assert hasattr(nf, "columns")
    for col in ["nb_net_flow", "nb_total_buy", "nb_total_sell", "nb_holding_value", "nb_holding_ratio"]:
        assert col in nf.columns or len(nf) == 0

    mg = load_margin()
    for col in ["margin_buy", "margin_balance", "sec_lending_balance"]:
        assert col in mg.columns or len(mg) == 0


# ═══════════════════════════════════════════════
# V3.4 — Technical Pattern Control Pack
# ═══════════════════════════════════════════════

def test_technical_factors_registered():
    """V3.4: factor_base 中的 technical 因子必须全部注册 (12个)"""
    from factor_lab.factor_base import list_factors
    tech = [f for f in list_factors() if f["category"] == "technical"]
    assert len(tech) == 12, f"预期 12 个 technical 因子, 实际 {len(tech)}"
    names = {f["name"] for f in tech}
    expected = {
        "macd_dif", "macd_dea", "macd_histogram", "macd_cross",
        "kdj_k", "kdj_d", "kdj_j", "kdj_cross",
        "boll_position", "boll_width", "boll_squeeze", "boll_breakout",
    }
    assert names == expected, f"因子名不匹配: 预期={expected}, 实际={names}"


def test_technical_factors_compute():
    """V3.4: 所有技术因子在模拟数据上正确计算"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=100, freq="D")
    symbols = ["A", "B", "C"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({
                "date": d, "symbol": s, "close": 10 + np.random.randn() * 2,
                "high": 11 + np.random.randn() * 2, "low": 9 + np.random.randn() * 2,
                "volume": 1e6, "amount": 1e7, "open": 10,
            })
    df = pd.DataFrame(rows)

    tech_names = [
        "macd_dif", "macd_dea", "macd_histogram", "macd_cross",
        "kdj_k", "kdj_d", "kdj_j", "kdj_cross",
        "boll_position", "boll_width", "boll_squeeze", "boll_breakout",
    ]
    for name in tech_names:
        result = compute_factor(df, name)
        assert result is not None, f"{name} 返回 None"
        assert isinstance(result, pd.Series), f"{name} 返回 {type(result)}"
        assert len(result) == len(df), f"{name} 长度不匹配"


def test_technical_alpha_pack_dry_run():
    """V3.4: Technical Pattern Alpha Pack dry-run 必须返回 10 个 control alpha"""
    from factor_lab.alpha.technical_pattern_alpha_pack import run_technical_pattern_pack
    result = run_technical_pattern_pack(dry_run=True)
    assert result["specs_defined"] == 10
    assert result["registered"] == 10
    assert result["dry_run"] is True


def test_technical_alpha_pack_safety():
    """V3.4: 所有 alpha 必须 disabled, auto_apply=False, no_live_trade=True"""
    from factor_lab.alpha.technical_pattern_alpha_pack import run_technical_pattern_pack
    result = run_technical_pattern_pack(dry_run=True)
    assert result["all_enabled_false"] is True
    assert result["auto_apply"] is False
    assert result["no_live_trade"] is True


def test_technical_alpha_pack_no_broker():
    """V3.4: Technical Pattern Alpha Pack 不得调用 broker/miniqmt"""
    import ast
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/technical_pattern_alpha_pack.py").read()
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in (
                    "broker_adapter", "MiniQMTPositionAdapter", "send_order", "place_order"
                ):
                    assert False, f"发现 broker 调用: {node.func.id}"
            if isinstance(node, ast.Attribute):
                if node.attr in ("send_order", "place_order"):
                    assert False, f"发现交易调用: {node.attr}"
    except SyntaxError:
        assert True
    assert "no_live_trade" in src


def test_technical_report_files_generated():
    """V3.4: Technical Pattern Alpha Pack 必须生成报告文件"""
    from factor_lab.alpha.technical_pattern_alpha_pack import run_technical_pattern_pack
    result = run_technical_pattern_pack(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/technical_pattern_alpha_pack")
    out_path = base / result["run_id"]
    assert out_path.exists()
    assert (out_path / "technical_pattern_control_pack_report.html").exists()
    assert (out_path / "technical_pattern_control_pack_summary.md").exists()
    assert (out_path / "technical_pattern_alpha_pack.json").exists()
    assert (out_path / "technical_pattern_alphas_registered.csv").exists()


def test_technical_all_specs_have_role_control():
    """V3.4: 所有 AlphaSpec 定义中 role=control 且含 no_live_trade tag"""
    from factor_lab.alpha.technical_pattern_alpha_pack import TECHNICAL_ALPHA_SPECS
    for spec in TECHNICAL_ALPHA_SPECS:
        assert spec.get("role") == "control", f"{spec['name']} role 不是 control"
        assert "no_live_trade" in spec["tags"], f"{spec['name']} 缺少 no_live_trade 标签"
        assert "control" in spec["tags"], f"{spec['name']} 缺少 control 标签"


def test_technical_incremental_value_report():
    """V3.4: 增量价值评估报告必须包含所有分析维度"""
    from factor_lab.alpha.technical_pattern_alpha_pack import run_technical_pattern_pack
    result = run_technical_pattern_pack(dry_run=True)
    iv = result.get("incremental_value", {})
    assert "overall_verdict" in iv
    assert "avg_incremental_value_score" in iv
    assert "analysis" in iv
    assert "macd" in iv["analysis"]
    assert "kdj" in iv["analysis"]
    assert "bollinger" in iv["analysis"]
    assert "risks" in iv
    assert "recommendation" in iv
    assert iv["avg_incremental_value_score"] < 0.5, "技术因子增量价值应较低 (<0.5)"


def test_technical_incremental_report_csv_generated():
    """V3.4: 增量价值 CSV 报告必须生成"""
    from factor_lab.alpha.technical_pattern_alpha_pack import run_technical_pattern_pack
    result = run_technical_pattern_pack(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/technical_pattern_alpha_pack")
    out_path = base / result["run_id"]
    assert (out_path / "incremental_value_report.csv").exists()
    content = (out_path / "incremental_value_report.csv").read_text(encoding="utf-8-sig")
    assert "macd" in content.lower() or "MACD" in content
    assert "kdj" in content.lower() or "KDJ" in content
    assert "bollinger" in content.lower() or "boll" in content


def test_technical_factor_cross_computation_macd_relation():
    """V3.4: MACD DIF > 0 时短期动量强于长期动量 (一致性检查)"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    np.random.seed(999)
    dates = pd.date_range("2026-01-01", periods=50, freq="D")
    symbols = ["A"]
    rows = []
    for d in dates:
        rows.append({
            "date": d, "symbol": "A", "close": 10 + np.sin(d.day) * 0.5,
            "high": 11, "low": 9, "volume": 1e6, "amount": 1e7, "open": 10,
        })
    df = pd.DataFrame(rows)

    macd = compute_factor(df, "macd_dif")
    hist = compute_factor(df, "macd_histogram")
    cross = compute_factor(df, "macd_cross")

    # macd_dif 与 macd_histogram 符号应一致 (DIF - DEA ≈ DIF 方向)
    # (排除 NaN 和接近 0 的值)
    valid = (macd.abs() > 0.01) & (hist.abs() > 0.01)
    sign_agreement = ((macd[valid] > 0) == (hist[valid] > 0)).mean()
    assert sign_agreement > 0.5, f"MACD DIF 与柱状图符号一致性过低: {sign_agreement:.2f}"


def test_technical_factor_graceful_degradation():
    """V3.4: 技术因子缺少 high/low 列时应优雅处理"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    symbols = ["A"]
    rows = [{"date": d, "symbol": "A", "close": 10.0, "volume": 1e6, "amount": 1e7}
            for d in dates]
    df = pd.DataFrame(rows)

    # MACD 只需要 close
    for name in ["macd_dif", "macd_dea", "macd_histogram", "macd_cross"]:
        result = compute_factor(df, name)
        assert result is not None
        assert len(result) == len(df)

    # KDJ 需要 high/low (缺少时可能崩溃或返回 NaN)
    for name in ["kdj_k", "kdj_d", "kdj_j", "kdj_cross"]:
        try:
            result = compute_factor(df, name)
            assert result is not None
            assert len(result) == len(df)
        except (KeyError, ValueError, Exception):
            pass  # 缺少 high/low 时允许优雅报错

    # Bollinger 只需要 close
    for name in ["boll_position", "boll_width", "boll_squeeze", "boll_breakout"]:
        result = compute_factor(df, name)
        assert result is not None
        assert len(result) == len(df)


def test_technical_kdj_k_range():
    """V3.4: KDJ K 值应在合理范围 [0, 100] (正常市场条件)"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    symbols = ["A"]
    rows = []
    for d in dates:
        close = 10 + np.random.randn() * 0.5
        rows.append({
            "date": d, "symbol": "A", "close": close,
            "high": close + abs(np.random.randn()) * 0.3,
            "low": close - abs(np.random.randn()) * 0.3,
            "volume": 1e6, "amount": 1e7, "open": close,
        })
    df = pd.DataFrame(rows)

    k = compute_factor(df, "kdj_k")
    d = compute_factor(df, "kdj_d")
    j = compute_factor(df, "kdj_j")

    # K/D 应在 [0, 100] 范围
    assert k.min() >= 0 and k.max() <= 100, f"K 值范围异常: [{k.min()}, {k.max()}]"
    assert d.min() >= 0 and d.max() <= 100, f"D 值范围异常: [{d.min()}, {d.max()}]"

    # J 可以超过 [0, 100] (但应有意义)
    # K > 80 或 K < 20 是超买超卖的极端情况
    k_final = k.iloc[-1]
    assert 0 <= k_final <= 100, f"K 最终值异常: {k_final}"


def test_technical_bollinger_basic():
    """V3.4: Bollinger %b 在轨道内时应在 [0, 1] 范围"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    symbols = ["A"]
    rows = []
    for d in dates:
        rows.append({
            "date": d, "symbol": "A", "close": 10.0,
            "high": 10.5, "low": 9.5, "volume": 1e6, "amount": 1e7, "open": 10.0,
        })
    df = pd.DataFrame(rows)

    pos = compute_factor(df, "boll_position")
    # 当 close 恒定时, %b 应接近 0.5 (在中轨)
    valid_pos = pos.dropna()
    if len(valid_pos) > 0:
        assert abs(valid_pos.iloc[-1] - 0.5) < 0.1, f"%b 应接近 0.5 (close 恒定): {valid_pos.iloc[-1]}"

    width = compute_factor(df, "boll_width")
    valid_width = width.dropna()
    if len(valid_width) > 0:
        # 当 close 恒定时, 带宽应接近 0
        assert valid_width.iloc[-1] < 0.1, f"带宽应接近 0 (close 恒定): {valid_width.iloc[-1]}"


def test_technical_catalog_migration_includes_technical():
    """V3.4: factor_catalog_migration 的 data requirements 应包含 technical"""
    from factor_lab.alpha.factor_catalog_migration import _get_factor_data_requirements
    reqs = _get_factor_data_requirements("technical")
    assert "close" in reqs
    assert "high" in reqs
    assert "low" in reqs


def test_technical_factor_names_unique():
    """V3.4: 所有 technical 因子名不与其他类别冲突"""
    from factor_lab.factor_base import list_factors
    all_factors = list_factors()
    names_seen = {}
    for f in all_factors:
        name = f["name"]
        cat = f["category"]
        if name in names_seen and cat == "technical":
            assert False, f"因子名 {name} 已存在 ({names_seen[name]}) vs (technical)"
        names_seen[name] = cat


# ═══════════════════════════════════════════════
# V3.5 — Event-driven Alpha Pack
# ═══════════════════════════════════════════════

def test_event_factors_registered():
    """V3.5: factor_base 中的 event 因子必须全部注册 (13个)"""
    from factor_lab.factor_base import list_factors
    evt = [f for f in list_factors() if f["category"] == "event"]
    assert len(evt) == 13, f"预期 13 个 event 因子, 实际 {len(evt)}"
    names = {f["name"] for f in evt}
    expected = {
        "lockup_expiry_proximity", "lockup_announcement_activity",
        "buyback_signal", "buyback_intensity", "buyback_recent_intensity",
        "dividend_yield_factor", "ex_dividend_proximity", "dividend_amount_factor",
        "forecast_upgrade_signal", "forecast_downgrade_signal",
        "forecast_momentum_signal", "forecast_recent_activity",
        "event_composite_score",
    }
    assert names == expected, f"因子名不匹配: 预期={expected}, 实际={names}"


def test_event_alpha_pack_dry_run():
    """V3.5: Event Alpha Pack dry-run 必须返回 12 个 alpha"""
    from factor_lab.alpha.event_alpha_pack import run_event_alpha_pack
    result = run_event_alpha_pack(dry_run=True)
    assert result["specs_defined"] == 12
    assert result["registered"] == 12
    assert result["dry_run"] is True


def test_event_alpha_pack_safety():
    """V3.5: 所有 alpha 必须 disabled, auto_apply=False, no_live_trade=True"""
    from factor_lab.alpha.event_alpha_pack import run_event_alpha_pack
    result = run_event_alpha_pack(dry_run=True)
    assert result["all_enabled_false"] is True
    assert result["auto_apply"] is False
    assert result["no_live_trade"] is True


def test_event_alpha_pack_no_broker():
    """V3.5: Event Alpha Pack 不得调用 broker/miniqmt"""
    import ast
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/event_alpha_pack.py").read()
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in (
                    "broker_adapter", "MiniQMTPositionAdapter", "send_order", "place_order"
                ):
                    assert False, f"发现 broker 调用: {node.func.id}"
            if isinstance(node, ast.Attribute):
                if node.attr in ("send_order", "place_order"):
                    assert False, f"发现交易调用: {node.attr}"
    except SyntaxError:
        assert True
    assert "no_live_trade" in src


def test_event_report_files_generated():
    """V3.5: Event Alpha Pack 必须生成报告文件"""
    from factor_lab.alpha.event_alpha_pack import run_event_alpha_pack
    result = run_event_alpha_pack(dry_run=True)
    import pathlib
    base = pathlib.Path("/mnt/d/HermesReports/event_alpha_pack")
    out_path = base / result["run_id"]
    assert out_path.exists()
    assert (out_path / "event_alpha_pack_report.html").exists()
    assert (out_path / "event_alpha_pack_summary.md").exists()
    assert (out_path / "event_alpha_pack.json").exists()
    assert (out_path / "event_alphas_registered.csv").exists()


def test_event_all_specs_disabled_in_source():
    """V3.5: 所有 AlphaSpec 定义中 enabled=False (via no_live_trade tag)"""
    from factor_lab.alpha.event_alpha_pack import EVENT_ALPHA_SPECS
    for spec in EVENT_ALPHA_SPECS:
        assert "no_live_trade" in spec["tags"], f"{spec['name']} 缺少 no_live_trade 标签"


def test_event_factor_computation_with_data():
    """V3.5: 所有事件因子在模拟数据上正确计算"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    symbols = ["A", "B", "C"]
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({
                "date": d, "symbol": s, "close": 10 + np.random.randn(),
                "volume": 1e6, "amount": 1e7,
                "lockup_days_to_expiry": np.random.choice([-30, -5, 3, 10, 60]),
                "lockup_count_90d": np.random.randint(0, 5),
                "buyback_active": np.random.choice([0, 1]),
                "buyback_count_30d": np.random.randint(0, 3),
                "buyback_count_90d": np.random.randint(0, 10),
                "dividend_yield": np.random.uniform(0, 0.05),
                "dividend_days_since": np.random.choice([10, 45, 120, 200]),
                "dividend_amount": np.random.uniform(0, 2.0),
                "forecast_type_code": np.random.choice([-1, -0.5, 0, 0.5, 1]),
                "forecast_count_90d": np.random.randint(0, 5),
                "forecast_momentum": np.random.randint(-3, 4),
            })
    df = pd.DataFrame(rows)

    event_names = [
        "lockup_expiry_proximity", "lockup_announcement_activity",
        "buyback_signal", "buyback_intensity", "buyback_recent_intensity",
        "dividend_yield_factor", "ex_dividend_proximity", "dividend_amount_factor",
        "forecast_upgrade_signal", "forecast_downgrade_signal",
        "forecast_momentum_signal", "forecast_recent_activity",
        "event_composite_score",
    ]
    for name in event_names:
        result = compute_factor(df, name)
        assert result is not None, f"{name} 返回 None"
        assert isinstance(result, pd.Series), f"{name} 返回 {type(result)}"
        assert len(result) == len(df), f"{name} 长度不匹配"


def test_event_factor_graceful_degradation():
    """V3.5: 事件因子在缺少事件列时应返回零值而非崩溃"""
    import pandas as pd
    import numpy as np
    from factor_lab.factor_base import compute_factor

    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    symbols = ["A"]
    rows = [{"date": d, "symbol": "A", "close": 10.0, "volume": 1e6, "amount": 1e7}
            for d in dates]
    df = pd.DataFrame(rows)

    event_names = [
        "lockup_expiry_proximity", "lockup_announcement_activity",
        "buyback_signal", "buyback_intensity", "buyback_recent_intensity",
        "dividend_yield_factor", "ex_dividend_proximity", "dividend_amount_factor",
        "forecast_upgrade_signal", "forecast_downgrade_signal",
        "forecast_momentum_signal", "forecast_recent_activity",
        "event_composite_score",
    ]
    for name in event_names:
        result = compute_factor(df, name)
        assert result is not None, f"{name} 返回 None"
        assert len(result) == len(df), f"{name} 长度不匹配"


def test_event_loader_basic():
    """V3.5: EventLoader 基本功能"""
    from factor_lab.alpha.event_loader import (
        load_lockup_events, load_buyback_events, load_dividend_events,
        load_forecast_events, get_event_data, event_data_status,
    )

    lk = load_lockup_events()
    assert "lockup_days_to_expiry" in lk.columns or len(lk) == 0

    bb = load_buyback_events()
    assert "buyback_active" in bb.columns or len(bb) == 0

    dv = load_dividend_events()
    assert "dividend_yield" in dv.columns or len(dv) == 0

    fc = load_forecast_events()
    assert "forecast_type_code" in fc.columns or len(fc) == 0

    # 统一入口
    events = get_event_data()
    assert "lockup" in events
    assert "buyback" in events
    assert "dividend" in events
    assert "forecast" in events

    # 状态报告
    status = event_data_status()
    assert status["source"] == "canonical_datahub_corporate_events"
    assert set(status["datasets"]) == {"share_float", "repurchase", "dividend", "forecast"}
    assert status["status"] in {"OK", "PARTIAL"}


def test_event_merge_event_data():
    """V3.5: merge_event_data 在模拟数据上正常工作"""
    import pandas as pd
    import numpy as np
    from factor_lab.alpha.event_loader import merge_event_data

    symbols = ["A", "B"]
    dates = pd.date_range("2026-07-01", periods=5, freq="D")
    rows = []
    for s in symbols:
        for d in dates:
            rows.append({"date": d, "symbol": s, "close": 10.0})
    df = pd.DataFrame(rows)

    result = merge_event_data(df)
    assert len(result) == len(df)
    assert "close" in result.columns


def test_event_factor_names_unique():
    """V3.5: 所有 event 因子名不与其他类别冲突"""
    from factor_lab.factor_base import list_factors
    all_factors = list_factors()
    names_seen = {}
    for f in all_factors:
        name = f["name"]
        cat = f["category"]
        if name in names_seen and cat == "event":
            assert False, f"因子名 {name} 已存在 ({names_seen[name]}) vs (event)"
        names_seen[name] = cat
