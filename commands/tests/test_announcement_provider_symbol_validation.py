from __future__ import annotations

from provider_matrix import AnnouncementProvider
import json
import urllib.request


def test_announcement_provider_rejects_results_for_other_security(monkeypatch):
    provider = AnnouncementProvider()
    monkeypatch.setattr(provider, "get_cninfo", lambda _symbol: [
        {"source": "cninfo", "source_symbol": "163209", "title": "unrelated"},
        {"source": "cninfo", "source_symbol": "688012", "title": "matched"},
    ])
    monkeypatch.setattr(provider, "get_sse", lambda _symbol: [])
    monkeypatch.setattr(provider, "get_szse", lambda _symbol: [])

    result = provider.get_all("688012")

    assert [item["title"] for item in result] == ["matched"]


def test_announcement_provider_rejects_unverifiable_symbol(monkeypatch):
    provider = AnnouncementProvider()
    monkeypatch.setattr(provider, "get_cninfo", lambda _symbol: [{"source": "cninfo", "title": "unknown"}])
    monkeypatch.setattr(provider, "get_sse", lambda _symbol: [])
    monkeypatch.setattr(provider, "get_szse", lambda _symbol: [])

    assert provider.get_all("688012") == []


def test_cninfo_uses_verified_org_id_for_symbol_specific_page(monkeypatch):
    calls = []
    responses = iter([
        {"announcements": [
            {"secCode": "163209", "orgId": "x", "announcementTitle": "unrelated"},
            {"secCode": "688012", "orgId": "gfbj0830342", "announcementTitle": "discovery"},
        ]},
        {"announcements": [{
            "secCode": "688012", "orgId": "gfbj0830342", "announcementTitle": "specific",
            "announcementTime": 1783699200000, "announcementId": "a1",
        }]},
    ])

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

    def urlopen(request, timeout):
        calls.append((json.loads(request.data.decode()), timeout))
        return Response(next(responses))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    result = AnnouncementProvider().get_cninfo("688012", page_size=10)

    assert calls[1][0]["stock"] == "688012,gfbj0830342"
    assert result[0]["title"] == "specific"
    assert result[0]["source_symbol"] == "688012"
