import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from src.main import app
import src.services.strategy_store as store_mod
import src.services.engine_adapter as adapter_mod
from trading_strategy_engine.models import RunResult

client = TestClient(app)


def _mock_result(sid: str) -> RunResult:
    return RunResult(strategy_id=sid, state="completed", started_at=datetime.now(timezone.utc))


def test_run_returns_202(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    sid = client.post("/strategies", json={"name": "Run Test"}).json()["id"]
    monkeypatch.setattr(adapter_mod, "run_strategy", lambda sid, cfg: _mock_result(sid))
    r = client.post(f"/strategies/{sid}/run", json={})
    assert r.status_code == 202
    assert r.json()["state"] == "completed"


def test_run_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    assert client.post("/strategies/bad-id/run", json={}).status_code == 404


def test_status_returns_200(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    sid = client.post("/strategies", json={"name": "Status Test"}).json()["id"]
    monkeypatch.setattr(adapter_mod, "get_status", lambda sid: _mock_result(sid))
    r = client.get(f"/strategies/{sid}/status")
    assert r.status_code == 200


def test_status_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    assert client.get("/strategies/bad-id/status").status_code == 404
