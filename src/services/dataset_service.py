"""Lab Platform datasets: pull OHLCV once for a ticker+range+interval, store it
on disk, and re-serve it statically (no repeated live yfinance calls). Pulls
run as a background asyncio task, chunked so progress and cancellation are
meaningful for longer pulls; cancellation is a cooperative flag re-read from
disk between chunks (works across the single backend process; a mid-flight
yfinance call itself can't be interrupted).

Also runs backtests (a strategy against a stored dataset's bars) as a similarly
tracked job, delegating the actual strategy execution to the sandbox worker
(same path live strategy runs use), but with no warmup needed since the whole
stored dataset IS the display window.

Storage layout (under DATASET_ROOT):
    <id>/meta.json              dataset metadata + status + progress
    <id>/bars.json              the pulled OHLCV rows (once ready)
    <id>/backtests/<bid>.json   one file per backtest run against this dataset
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from fastapi import HTTPException

from . import sandbox_client

DATASET_ROOT = Path(os.getenv("DATASET_ROOT", str(Path.home() / "trading-datasets")))
DATASET_ROOT.mkdir(parents=True, exist_ok=True)

INTERVAL_MAP: dict[str, str] = {"1m": "1m", "1h": "1h", "1d": "1d", "1w": "1wk", "1mo": "1mo"}

# Chunk size per interval -- purely for meaningful progress/cancel granularity
# on longer pulls (not strictly required by yfinance's own limits, though 1m
# data genuinely can't go back further than ~30 days regardless of chunking).
CHUNK_DAYS: dict[str, int] = {"1m": 5, "1h": 60, "1d": 730, "1wk": 1825, "1mo": 3650}
MAX_LOOKBACK_DAYS: dict[str, int] = {"1m": 30}  # yfinance limit; other intervals are effectively unbounded here


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta_path(dataset_id: str) -> Path:
    return DATASET_ROOT / dataset_id / "meta.json"


def _bars_path(dataset_id: str) -> Path:
    return DATASET_ROOT / dataset_id / "bars.json"


def _backtests_dir(dataset_id: str) -> Path:
    return DATASET_ROOT / dataset_id / "backtests"


def _read_meta(dataset_id: str) -> dict:
    p = _meta_path(dataset_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    return json.loads(p.read_text())


def _write_meta(dataset_id: str, meta: dict) -> None:
    _meta_path(dataset_id).write_text(json.dumps(meta, indent=2))


def _bars_from_hist(hist: pd.DataFrame) -> list[dict]:
    bars = []
    for ts, row in hist.iterrows():
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        if any(math.isnan(v) for v in (o, h, l, c)):
            continue
        vol = row["Volume"]
        bars.append({
            "timestamp": ts.isoformat(),
            "open": round(o, 4), "high": round(h, 4), "low": round(l, 4), "close": round(c, 4),
            "volume": int(vol) if not math.isnan(float(vol)) else 0,
        })
    return bars


def _chunk_ranges(start: pd.Timestamp, end: pd.Timestamp, chunk_days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    out = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=chunk_days), end)
        out.append((cur, nxt))
        cur = nxt
    return out or [(start, end)]


async def _run_pull(dataset_id: str, ticker: str, start: str, end: str, interval: str) -> None:
    interval_yf = INTERVAL_MAP.get(interval, "1d")
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    # Clamp to what the interval can actually retrieve (yfinance 1m limit).
    lookback = MAX_LOOKBACK_DAYS.get(interval)
    effective_start = start_ts
    if lookback is not None:
        earliest = pd.Timestamp.now(tz=start_ts.tz) - timedelta(days=lookback)
        if start_ts < earliest:
            effective_start = earliest

    chunks = _chunk_ranges(effective_start, end_ts, CHUNK_DAYS.get(interval, 730))
    meta = _read_meta(dataset_id)
    meta["status"] = "running"
    meta["progress"] = {"done": 0, "total": len(chunks)}
    if effective_start != start_ts:
        meta["effective_start"] = effective_start.isoformat()
    _write_meta(dataset_id, meta)

    all_bars: list[dict] = []
    try:
        ticker_obj = yf.Ticker(ticker)
        for i, (c_start, c_end) in enumerate(chunks):
            # Cooperative cancellation: re-read from disk so a separate request
            # (POST .../cancel) can stop this loop between chunks.
            meta = _read_meta(dataset_id)
            if meta.get("cancel_requested"):
                meta["status"] = "cancelled"
                _write_meta(dataset_id, meta)
                return
            hist = await asyncio.to_thread(
                ticker_obj.history, start=c_start.strftime("%Y-%m-%d"), end=c_end.strftime("%Y-%m-%d"), interval=interval_yf,
            )
            if not hist.empty:
                all_bars.extend(_bars_from_hist(hist))
            meta["progress"] = {"done": i + 1, "total": len(chunks)}
            _write_meta(dataset_id, meta)

        # De-dupe/sort in case chunk boundaries overlap.
        seen = set()
        deduped = []
        for b in sorted(all_bars, key=lambda b: b["timestamp"]):
            if b["timestamp"] in seen:
                continue
            seen.add(b["timestamp"])
            deduped.append(b)

        _bars_path(dataset_id).write_text(json.dumps(deduped))
        meta = _read_meta(dataset_id)
        meta["status"] = "ready"
        meta["row_count"] = len(deduped)
        _write_meta(dataset_id, meta)
    except Exception as e:  # noqa: BLE001 -- surface the failure, don't crash the process
        meta = _read_meta(dataset_id)
        meta["status"] = "error"
        meta["error"] = str(e)
        _write_meta(dataset_id, meta)


# Keep references so the tasks aren't garbage-collected mid-flight.
_TASKS: set[asyncio.Task] = set()


def create_dataset(ticker: str, start: str, end: str, interval: str, name: str | None = None) -> dict:
    if interval not in INTERVAL_MAP:
        raise HTTPException(status_code=400, detail=f"interval must be one of {list(INTERVAL_MAP)}")
    dataset_id = uuid.uuid4().hex[:12]
    (DATASET_ROOT / dataset_id).mkdir(parents=True)
    meta = {
        "id": dataset_id, "name": (name or "").strip() or f"{ticker.upper()} {start}→{end}",
        "ticker": ticker.upper(), "start": start, "end": end, "interval": interval,
        "status": "pending", "created_at": _now(), "row_count": 0,
        "progress": {"done": 0, "total": 1}, "error": None, "cancel_requested": False,
    }
    _write_meta(dataset_id, meta)
    task = asyncio.create_task(_run_pull(dataset_id, ticker, start, end, interval))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return meta


def list_datasets() -> list[dict]:
    if not DATASET_ROOT.exists():
        return []
    out = []
    for d in sorted(DATASET_ROOT.iterdir(), reverse=True):
        mp = d / "meta.json"
        if d.is_dir() and mp.exists():
            try:
                out.append(json.loads(mp.read_text()))
            except Exception:
                continue
    return out


def get_dataset(dataset_id: str) -> dict:
    return _read_meta(dataset_id)


def get_dataset_bars(dataset_id: str) -> list[dict]:
    meta = _read_meta(dataset_id)
    if meta["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"dataset is '{meta['status']}', not ready")
    return json.loads(_bars_path(dataset_id).read_text())


def cancel_dataset(dataset_id: str) -> dict:
    meta = _read_meta(dataset_id)
    if meta["status"] in ("running", "pending"):
        meta["cancel_requested"] = True
        _write_meta(dataset_id, meta)
    return meta


def delete_dataset(dataset_id: str) -> None:
    import shutil
    d = DATASET_ROOT / dataset_id
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    shutil.rmtree(d)


# ── Backtests (run a strategy against a stored dataset) ──────────────────

async def _run_backtest(dataset_id: str, backtest_id: str, strategy_slug: str) -> None:
    path = _backtests_dir(dataset_id) / f"{backtest_id}.json"

    def _write(meta: dict) -> None:
        path.write_text(json.dumps(meta, indent=2))

    meta = json.loads(path.read_text())
    if meta.get("cancel_requested"):
        meta["status"] = "cancelled"; _write(meta)
        return
    meta["status"] = "running"
    _write(meta)
    try:
        bars = get_dataset_bars(dataset_id)
        result = await asyncio.to_thread(sandbox_client.run_strategy, strategy_slug, bars, None)
        meta["status"] = "completed"
        meta["result"] = result
        _write(meta)
    except Exception as e:  # noqa: BLE001
        meta["status"] = "error"
        meta["error"] = str(e)
        _write(meta)


def create_backtest(dataset_id: str, strategy_slug: str) -> dict:
    _read_meta(dataset_id)  # 404s if the dataset doesn't exist
    _backtests_dir(dataset_id).mkdir(parents=True, exist_ok=True)
    backtest_id = uuid.uuid4().hex[:12]
    meta = {
        "id": backtest_id, "dataset_id": dataset_id, "strategy_slug": strategy_slug,
        "status": "pending", "created_at": _now(), "cancel_requested": False, "result": None, "error": None,
    }
    (_backtests_dir(dataset_id) / f"{backtest_id}.json").write_text(json.dumps(meta, indent=2))
    task = asyncio.create_task(_run_backtest(dataset_id, backtest_id, strategy_slug))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return meta


def list_backtests(dataset_id: str) -> list[dict]:
    d = _backtests_dir(dataset_id)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir(), reverse=True):
        if f.suffix == ".json":
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                continue
    return out


def get_backtest(dataset_id: str, backtest_id: str) -> dict:
    p = _backtests_dir(dataset_id) / f"{backtest_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"backtest '{backtest_id}' not found")
    return json.loads(p.read_text())


def cancel_backtest(dataset_id: str, backtest_id: str) -> dict:
    p = _backtests_dir(dataset_id) / f"{backtest_id}.json"
    meta = get_backtest(dataset_id, backtest_id)
    if meta["status"] in ("pending", "running"):
        meta["cancel_requested"] = True
        p.write_text(json.dumps(meta, indent=2))
    return meta


def delete_backtest(dataset_id: str, backtest_id: str) -> None:
    p = _backtests_dir(dataset_id) / f"{backtest_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"backtest '{backtest_id}' not found")
    p.unlink()


# ── Label sets (hand-marked buy/sell points on a dataset) ────────────────
# Same storage shape as backtests -- one JSON per set under the dataset --
# because they are the same kind of artifact: a named list of buy/sell marks
# scoped to one dataset. Keeping the shapes aligned means the chart can render
# a hand-labelled set and a strategy's signals through the same path.

def _labels_dir(dataset_id: str) -> Path:
    return DATASET_ROOT / dataset_id / "labels"


def _label_path(dataset_id: str, label_id: str) -> Path:
    return _labels_dir(dataset_id) / f"{label_id}.json"


def create_label_set(dataset_id: str, name: str | None = None) -> dict:
    _read_meta(dataset_id)  # 404s if the dataset doesn't exist
    _labels_dir(dataset_id).mkdir(parents=True, exist_ok=True)
    label_id = uuid.uuid4().hex[:12]
    meta = {
        "id": label_id,
        "dataset_id": dataset_id,
        "name": (name or "").strip() or f"Labels {datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
        "created_at": _now(),
        "updated_at": _now(),
        # [{time: ISO, type: 'buy'|'sell', price: float}]
        "marks": [],
    }
    _label_path(dataset_id, label_id).write_text(json.dumps(meta, indent=2))
    return meta


def list_label_sets(dataset_id: str) -> list[dict]:
    d = _labels_dir(dataset_id)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir(), reverse=True):
        if f.suffix == ".json":
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                continue
    return out


def get_label_set(dataset_id: str, label_id: str) -> dict:
    p = _label_path(dataset_id, label_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"label set '{label_id}' not found")
    return json.loads(p.read_text())


def save_label_marks(dataset_id: str, label_id: str, marks: list[dict], name: str | None = None) -> dict:
    """Replace a set's marks wholesale. The editor holds the authoritative list
    while you work, so a full replace avoids merge questions entirely."""
    meta = get_label_set(dataset_id, label_id)
    cleaned = []
    for m in marks:
        side = str(m.get("type", "")).lower()
        if side not in ("buy", "sell"):
            continue
        try:
            cleaned.append({
                "time": str(m["time"]),
                "type": side,
                "price": float(m.get("price") or 0.0),
            })
        except Exception:
            continue
    cleaned.sort(key=lambda m: m["time"])
    meta["marks"] = cleaned
    if name is not None and name.strip():
        meta["name"] = name.strip()
    meta["updated_at"] = _now()
    _label_path(dataset_id, label_id).write_text(json.dumps(meta, indent=2))
    return meta


def delete_label_set(dataset_id: str, label_id: str) -> None:
    p = _label_path(dataset_id, label_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"label set '{label_id}' not found")
    p.unlink()


# ── Drawings (hand-drawn chart annotations) ──────────────────────────────
# One collection per dataset rather than named sets: unlike label sets, you
# don't compare two sets of drawings against each other -- they're markup on
# the chart, so a single canvas per dataset is the honest model.

def _drawings_path(dataset_id: str) -> Path:
    return DATASET_ROOT / dataset_id / "drawings.json"


_DRAWING_KINDS = {
    "trendline", "ray", "hline", "vline", "rect", "fib",
    "long", "short", "text", "arrow-up", "arrow-down", "box",
}


def get_drawings(dataset_id: str) -> list[dict]:
    _read_meta(dataset_id)  # 404s if the dataset doesn't exist
    p = _drawings_path(dataset_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def save_drawings(dataset_id: str, drawings: list[dict]) -> list[dict]:
    """Replace the dataset's drawings wholesale -- the editor holds the
    authoritative list while you draw, so a full replace avoids merge
    questions entirely (same reasoning as label marks).

    Shapes are stored as a list of {t, p} anchor points rather than fixed
    t1/p1/t2/p2 fields, so a two-point trendline, a one-point level and a
    three-level position tool all use one schema."""
    _read_meta(dataset_id)
    cleaned: list[dict] = []
    for d in drawings:
        kind = str(d.get("kind", ""))
        if kind not in _DRAWING_KINDS:
            continue
        pts = []
        for pt in (d.get("points") or []):
            try:
                pts.append({"t": str(pt["t"]), "p": float(pt["p"])})
            except Exception:
                continue
        if not pts:
            continue  # an anchor-less shape can't be drawn
        item: dict = {
            "id": str(d.get("id") or uuid.uuid4().hex[:8]),
            "kind": kind,
            "points": pts,
        }
        for key, cast in (("text", str), ("color", str), ("width", int), ("stop", float), ("target", float)):
            if d.get(key) not in (None, ""):
                try:
                    item[key] = cast(d[key])
                except Exception:
                    pass
        if isinstance(item.get("text"), str):
            item["text"] = item["text"][:200]
        cleaned.append(item)
    _drawings_path(dataset_id).write_text(json.dumps(cleaned, indent=2))
    return cleaned
