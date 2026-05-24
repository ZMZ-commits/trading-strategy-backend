import pytest
from fastapi.testclient import TestClient
from src.main import app
import src.services.strategy_store as store_mod

client = TestClient(app)


def test_list_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    assert client.get("/strategies").json() == []


def test_create(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    r = client.post("/strategies", json={"name": "Test Strategy"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test Strategy"
    assert data["slug"] == "test-strategy"
    assert (tmp_path / "test-strategy" / "strategy.json").exists()
    assert (tmp_path / "test-strategy" / "runs").exists()


def test_create_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    client.post("/strategies", json={"name": "Dupe"})
    assert client.post("/strategies", json={"name": "Dupe"}).status_code == 409


def test_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    sid = client.post("/strategies", json={"name": "To Delete"}).json()["id"]
    assert client.delete(f"/strategies/{sid}").status_code == 204
    assert not (tmp_path / "to-delete").exists()


def test_delete_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    assert client.delete("/strategies/nonexistent").status_code == 404
