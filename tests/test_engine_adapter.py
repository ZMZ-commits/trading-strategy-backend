import json
import uuid
import pytest
import src.services.strategy_store as store_mod
from src.services.engine_adapter import run_strategy, get_status


@pytest.fixture
def strategy(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "STORE_ROOT", tmp_path)
    sid = str(uuid.uuid4())
    d = tmp_path / "adapter-test"
    d.mkdir()
    (d / "runs").mkdir()
    (d / "strategy.json").write_text(json.dumps({
        "id": sid, "name": "Adapter Test", "slug": "adapter-test",
        "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
        "lastRunAt": None, "lastRunStatus": "idle",
        "config": {}, "transactions": [], "notifications": [],
    }))
    return {"id": sid}


def test_run_returns_completed(strategy):
    result = run_strategy(strategy["id"], {})
    assert result.state == "completed"


def test_status_idle_before_run(strategy):
    result = get_status(strategy["id"])
    assert result.state == "idle"


def test_status_completed_after_run(strategy):
    run_strategy(strategy["id"], {})
    assert get_status(strategy["id"]).state == "completed"
