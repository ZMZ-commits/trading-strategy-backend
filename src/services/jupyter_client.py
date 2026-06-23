"""Client to JupyterLab's Contents API — seed/list authoring notebooks.

Owner-only authoring runs on the VM's JupyterLab; the backend reaches it
internally (``JUPYTER_URL``) with the shared token (``JUPYTER_TOKEN``). Used by
"+ Add Indicator/Strategy" to drop a templated notebook into the workspace.

stdlib only (no new dependency); callers should treat failures as soft (Jupyter
may be down or unconfigured — the backend must stay up regardless).
"""
from __future__ import annotations

import json
import os
import urllib.request

JUPYTER_URL = os.getenv("JUPYTER_URL", "http://jupyterlab:8888")
JUPYTER_TOKEN = os.getenv("JUPYTER_TOKEN", "")


def _contents(path: str = "", method: str = "GET", body: dict | None = None, timeout: float = 10.0):
    url = f"{JUPYTER_URL}/api/contents/{path}".rstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"token {JUPYTER_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _notebook(cells: list[str]) -> dict:
    return {
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": src, "outputs": [], "execution_count": None}
            for src in cells
        ],
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def create_notebook(path: str, cells: list[str]) -> dict:
    """Create (or overwrite) a notebook at ``path`` seeded with ``cells``."""
    return _contents(path, method="PUT", body={"type": "notebook", "format": "json", "content": _notebook(cells)})


def list_notebooks(folder: str = "") -> list[dict]:
    """List notebooks (drafts) in ``folder`` of the Jupyter workspace."""
    res = _contents(folder)
    content = res.get("content")
    items = content if isinstance(content, list) else []
    return [{"name": i["name"], "path": i["path"]} for i in items if i.get("type") == "notebook"]
