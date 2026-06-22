"""Thin client to the sandbox worker that runs published custom indicators.

The backend never executes user code itself — it fetches the bars and delegates
to the isolated sandbox container (see engine repo tsp/worker.py). Uses stdlib
urllib so this adds no dependency and can't break backend startup.
"""
from __future__ import annotations

import json
import os
import urllib.request

SANDBOX_URL = os.getenv("SANDBOX_URL", "http://sandbox:9000")


def run_custom(slug: str, bars: list[dict], params: dict | None = None, timeout: float = 15.0) -> dict:
    """POST {slug, bars, params} to the sandbox worker; return its JSON result."""
    payload = json.dumps({"slug": slug, "bars": bars, "params": params or {}}).encode()
    req = urllib.request.Request(
        f"{SANDBOX_URL}/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())
