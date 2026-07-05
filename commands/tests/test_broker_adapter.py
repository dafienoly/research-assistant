"""测试: V2.1 Broker Adapter + Position Source"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.broker.broker_position_adapter import read_positions, normalize_to_csv, DEFAULT_FIELD_MAP, STANDARD_FIELDS


def test_csv_broker_adapter():
    """读取标准 CSV 持仓"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "positions.csv")
        with open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write("symbol,name,shares,available_shares,cost_price,current_price\n000001,平安,200,200,10.0,12.0\n000002,万科,100,100,15.0,14.0\n")
        result = read_positions(csv_path)
        assert result["status"] in ("ok", "partial")
        assert len(result["normalized"]) > 0


def test_field_mapping():
    """中文字段映射"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "pos.csv")
        with open(csv_path, "w", encoding="gbk") as f:
            f.write("证券代码,证券名称,持仓数量,可用股数,成本价,最新价\n000001,平安,200,200,10.0,12.0\n")
        result = read_positions(csv_path)
        assert result["status"] in ("ok", "partial")
        assert len(result["normalized"]) > 0
        n = result["normalized"][0]
        assert n["symbol"] == "000001"


def test_encoding_auto_detect():
    """自动识别编码"""
    with tempfile.TemporaryDirectory() as tmp:
        for enc in ["utf-8-sig", "gbk"]:
            csv_path = os.path.join(tmp, f"test_{enc}.csv")
            with open(csv_path, "w", encoding=enc) as f:
                f.write("symbol,shares\n000001,100\n")
            result = read_positions(csv_path)
            assert result["status"] in ("ok", "partial"), f"{enc} 读取失败"


def test_no_fake_fallback():
    """文件不存在不返回假数据"""
    result = read_positions("/nonexistent/path.csv")
    assert result["status"] in ("failed", "partial")


def test_normalizer_standard_schema():
    """标准化后包含标准字段"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "pos.csv")
        with open(csv_path, "w") as f:
            f.write("symbol,shares\n000001,100\n")
        result = read_positions(csv_path)
        for n in result.get("normalized", []):
            for field in ["symbol", "shares"]:
                assert field in n, f"缺少标准字段 {field}"


def test_cash_parsed():
    """CASH 行正确解析"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "pos.csv")
        with open(csv_path, "w") as f:
            f.write("symbol,market_value\nCASH,50000\n")
        result = read_positions(csv_path)
        assert result["cash"] == 50000.0


def test_normalize_to_csv():
    """标准化输出 CSV"""
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"symbol": "000001", "shares": 100, "board": "main", "source": "test"}]
        out = os.path.join(tmp, "out.csv")
        normalize_to_csv(rows, out)
        assert os.path.exists(out)
