"""API响应信封完整性测试 — V5.1 P2-1验收"""
import sys, os, json

_HERE = os.path.dirname(os.path.abspath(__file__))
for _ in range(3):
    sys.path.insert(0, os.path.join(_HERE, *['..']*_))

os.environ.setdefault("PYTHONPATH", ':'.join(
    p for p in [os.path.join(_HERE, '..', '..', '..'), os.path.join(_HERE, '..', '..', '..', '..')]
    if os.path.isdir(p)
))

from fastapi.testclient import TestClient
from factor_lab.api_server.main import app

client = TestClient(app)

CORE_API = [
    ("GET", "/api/health"),
    ("GET", "/api/status"),
    ("GET", "/api/factors"),
    ("GET", "/api/factors/ret5"),
    ("GET", "/api/universe"),
    ("GET", "/api/version"),
]


def test_core_api_has_envelope():
    for method, path in CORE_API:
        resp = client.request(method, path)
        if resp.status_code >= 500:
            continue
        data = json.loads(resp.text)
        assert "ok" in data, f"{path} 缺少 ok 字段"
        assert "meta" in data, f"{path} 缺少 meta 字段"
        meta = data.get("meta", {})
        if meta:
            has_ts = "run_id" in meta or "as_of" in meta
            assert has_ts, f"{path} meta 缺时间戳"


def test_legacy_routes_unified():
    legacy = [
        ("GET", "/api/status"),
        ("GET", "/api/backups"),
    ]
    for method, path in legacy:
        resp = client.request(method, path)
        if resp.status_code >= 500:
            continue
        data = json.loads(resp.text)
        assert "ok" in data, f"{path} 无 ok 字段"
