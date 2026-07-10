from factor_lab.api_server.main import app


def test_main_app_registers_vnext_router():
    paths = set(app.openapi()["paths"])
    assert "/api/vnext/status" in paths
    assert "/api/vnext/reports/download" in paths
