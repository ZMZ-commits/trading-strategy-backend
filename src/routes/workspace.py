"""Scaffold strategy/indicator authoring folders in the shared IDE workspace.

The code-server workspace volume is mounted here (read-write) at $IDE_WORKSPACE.
Creating a strategy/indicator drops a starter file under strategies/ or
indicators/ that the user then edits in the web IDE (VS Code) and publishes via
the tsp SDK. Files are chowned to the coder user (uid 1000) so the IDE can edit
them (the backend runs as root).
"""
import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

WORKSPACE = Path(os.getenv("IDE_WORKSPACE", "/workspace"))
CODER_UID = 1000
CODER_GID = 1000


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    return re.sub(r"[\s_-]+", "-", s).strip("-")


def _chown_coder(path: Path) -> None:
    """Best-effort: make the path editable by the code-server user."""
    try:
        os.chown(path, CODER_UID, CODER_GID)
    except (PermissionError, OSError):
        pass


class ScaffoldRequest(BaseModel):
    kind: str  # "strategy" | "indicator"
    name: str
    content: str | None = None    # optional: full file body (else a starter template)
    filename: str | None = None   # optional: file name (else compute.py / strategy.py)


INDICATOR_TEMPLATE = '''\
"""{name} — custom indicator.

Edit compute(ctx), preview it, then publish so it shows up in the chart's
Indicators menu:

    from tsp import run_indicator, publish
    publish("{name}", compute, kind="overlay")   # or kind="oscillator"
"""
from tsp import Ctx


def compute(ctx: Ctx):
    # Series:    ctx.open, ctx.high, ctx.low, ctx.close, ctx.volume
    # Params:    ctx.param("length", 21)
    # Built-ins: ctx.sma, ctx.ema, ctx.rsi, ctx.macd, ctx.bbands, ctx.vwap, ...
    length = ctx.param("length", 21)
    ctx.plot("{name}", ctx.ema(ctx.close, length), kind="overlay")
'''

STRATEGY_TEMPLATE = '''\
"""{name} — trading strategy (scaffold).

Define your entry/exit logic against a Ctx. Strategy backtesting wiring is in
progress; for now this is the authoring skeleton.
"""
from tsp import Ctx


def run(ctx: Ctx):
    # ctx.close, ctx.ema, ctx.rsi, ... are available.
    # Return your signals / positions here.
    return {{}}
'''


@router.get("/workspace/items")
def list_items():
    """List the strategy/indicator folders currently in the workspace."""
    out: dict[str, list[str]] = {"strategies": [], "indicators": []}
    for folder in out:
        base = WORKSPACE / folder
        if base.is_dir():
            out[folder] = sorted(p.name for p in base.iterdir() if p.is_dir())
    return out


@router.post("/workspace/scaffold")
def scaffold(req: ScaffoldRequest):
    if req.kind not in ("strategy", "indicator"):
        raise HTTPException(status_code=400, detail="kind must be 'strategy' or 'indicator'")
    slug = _slug(req.name)
    if not slug:
        raise HTTPException(status_code=400, detail="name must contain a letter or number")

    folder_name = "strategies" if req.kind == "strategy" else "indicators"
    base = WORKSPACE / folder_name
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"workspace not writable: {e}")

    dest = base / slug
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"{req.kind} '{slug}' already exists")

    default_name = "compute.py" if req.kind == "indicator" else "strategy.py"
    fname = req.filename or default_name
    if "/" in fname or "\\" in fname or fname in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid filename")

    if req.content is not None:
        body = req.content
    elif req.kind == "indicator":
        body = INDICATOR_TEMPLATE.format(name=req.name)
    else:
        body = STRATEGY_TEMPLATE.format(name=req.name)

    dest.mkdir(parents=True)
    file_path = dest / fname
    file_path.write_text(body)

    _chown_coder(dest)
    _chown_coder(file_path)

    return {"kind": req.kind, "name": req.name, "slug": slug, "path": f"{folder_name}/{slug}"}


@router.delete("/workspace/{kind}/{slug}")
def delete_item(kind: str, slug: str):
    """Delete a strategy/indicator folder from the workspace (mirrors the IDE)."""
    if kind not in ("strategy", "indicator"):
        raise HTTPException(status_code=400, detail="kind must be 'strategy' or 'indicator'")
    # Guard against path traversal (folder names may be arbitrary, e.g. created in
    # the IDE, but must be a single path segment that resolves directly under base).
    if not slug or slug in (".", "..") or "/" in slug or "\\" in slug:
        raise HTTPException(status_code=400, detail="invalid slug")

    folder_name = "strategies" if kind == "strategy" else "indicators"
    base = (WORKSPACE / folder_name).resolve()
    dest = (base / slug).resolve()
    if dest.parent != base:
        raise HTTPException(status_code=400, detail="invalid path")
    if not dest.is_dir():
        raise HTTPException(status_code=404, detail=f"{kind} '{slug}' not found")

    shutil.rmtree(dest)
    return {"deleted": slug, "kind": kind}
