from fastapi.testclient import TestClient
from src.main import app
import src.services.yfinance_service as yf_mod

client = TestClient(app)

_MOCK_BARS = {"ticker": "AAPL", "range": "1M", "bars": [{"timestamp": "2026-04-24T00:00:00", "open": 180.0, "high": 182.5, "low": 179.1, "close": 181.8, "volume": 50000000}]}
_MOCK_SNAP = {"ticker": "AAPL", "name": "Apple Inc.", "price": 189.45, "open": 188.0, "high": 190.0, "low": 187.0, "close": 189.45, "volume": 50000000, "marketCap": None, "week52High": None, "week52Low": None}
_MOCK_IDX = [{"symbol": "^GSPC", "name": "S&P 500", "price": 5321.4, "change": 12.3, "changePct": 0.23}]


def test_history(monkeypatch):
    monkeypatch.setattr(yf_mod, "get_history", lambda t, r: _MOCK_BARS)
    r = client.get("/stocks/AAPL/history?range=1M")
    assert r.status_code == 200
    assert r.json()["ticker"] == "AAPL"


def test_snapshot(monkeypatch):
    monkeypatch.setattr(yf_mod, "get_snapshot", lambda t: _MOCK_SNAP)
    r = client.get("/stocks/AAPL")
    assert r.status_code == 200
    assert r.json()["price"] == 189.45


def test_indices(monkeypatch):
    monkeypatch.setattr(yf_mod, "get_indices", lambda: _MOCK_IDX)
    r = client.get("/market/indices")
    assert r.status_code == 200
    assert len(r.json()) == 1
