"""Authoring artifacts — create a seeded JupyterLab notebook + list drafts.

Phase 2 of the custom indicator/strategy IDE: "+ Add Indicator/Strategy" → name →
the backend seeds a templated notebook in the JupyterLab workspace (owner-only,
reached over the internal network). The UI then opens it via the user's SSH tunnel
(http://localhost:8888/lab/tree/<path>). Soft-fails if Jupyter is unreachable.
"""
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import jupyter_client

router = APIRouter()


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    return re.sub(r"[\s_-]+", "-", s).strip("-")


def _indicator_cells(name: str) -> list[str]:
    return [
        f"# Indicator: {name}\nfrom tsp import Ctx, run_indicator, publish",
        (
            "def compute(ctx):\n"
            "    # Edit me — emit one or more series with ctx.plot(name, series, kind).\n"
            f'    ctx.plot("{name}", ctx.ema(ctx.close, ctx.param("length", 21)), kind="overlay")'
        ),
        (
            "# Preview: fetch bars from the platform API, then run it.\n"
            "# import json, urllib.request\n"
            '# bars = json.load(urllib.request.urlopen('
            '"http://backend-dev:8000/stocks/AAPL/history?range=1M"))["bars"]\n'
            "# run_indicator(compute, bars)"
        ),
        (
            "# Publish so it shows up in the app under Indicators > Custom:\n"
            f'# publish("{name}", compute, kind="overlay")'
        ),
    ]


def _strategy_cells(name: str) -> list[str]:
    return [
        f"# Strategy: {name}\nfrom tsp import Ctx",
        (
            "def on_bar(ctx):\n"
            "    # Edit me — strategy logic (signals/orders) goes here.\n"
            "    pass"
        ),
    ]


class CreateRequest(BaseModel):
    name: str
    type: str = "indicator"  # "indicator" | "strategy"


@router.post("/custom/create")
def create_artifact(req: CreateRequest):
    slug = _slug(req.name)
    if not slug:
        raise HTTPException(status_code=422, detail="name must contain letters or numbers")
    path = f"{slug}.ipynb"
    cells = _strategy_cells(req.name) if req.type == "strategy" else _indicator_cells(req.name)
    try:
        jupyter_client.create_notebook(path, cells)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"jupyter unavailable: {e}")
    return {"name": req.name, "slug": slug, "type": req.type, "path": path, "labPath": f"/lab/tree/{path}"}


@router.get("/notebooks")
def list_notebooks():
    """List draft notebooks in the JupyterLab workspace."""
    try:
        return {"notebooks": jupyter_client.list_notebooks()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"jupyter unavailable: {e}")
