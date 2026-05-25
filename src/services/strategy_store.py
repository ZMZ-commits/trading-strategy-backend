import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from ..models.strategy import Strategy

STORE_ROOT = Path(os.getenv("STORE_ROOT", str(Path.home() / "trading-strategies")))
STORE_ROOT.mkdir(parents=True, exist_ok=True)


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


def create_strategy(name: str) -> Strategy:
    slug = slugify(name)
    strategy_dir = STORE_ROOT / slug
    if strategy_dir.exists():
        raise HTTPException(status_code=409, detail=f"Strategy '{name}' already exists")

    strategy_dir.mkdir(parents=True)
    (strategy_dir / "runs").mkdir()

    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    _write(strategy_dir / "strategy.json", {
        "id": sid, "name": name, "slug": slug,
        "createdAt": now.isoformat(), "updatedAt": now.isoformat(),
        "lastRunAt": None, "lastRunStatus": "idle",
        "config": {}, "transactions": [], "notifications": [],
    })
    return Strategy(id=sid, name=name, slug=slug, created_at=now, last_run_status="idle", dir_path=str(strategy_dir))


def list_strategies() -> list[Strategy]:
    result = []
    if not STORE_ROOT.exists():
        return result
    for d in sorted(STORE_ROOT.iterdir()):
        if not d.is_dir():
            continue
        jf = d / "strategy.json"
        if not jf.exists():
            continue
        data = _read(jf)
        result.append(Strategy(
            id=data["id"], name=data["name"], slug=data["slug"],
            created_at=datetime.fromisoformat(data["createdAt"]),
            last_run_at=datetime.fromisoformat(data["lastRunAt"]) if data.get("lastRunAt") else None,
            last_run_status=data.get("lastRunStatus", "idle"),
            dir_path=str(d),
        ))
    return result


def get_strategy(strategy_id: str) -> Optional[Strategy]:
    for s in list_strategies():
        if s.id == strategy_id:
            return s
    return None


def delete_strategy(strategy_id: str) -> None:
    s = get_strategy(strategy_id)
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    shutil.rmtree(s.dir_path)
