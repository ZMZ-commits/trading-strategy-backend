"""Chunked, progress-tracked history fetches for the Trading view.

The plain ``/stocks/{ticker}/history`` endpoint is a single yfinance call --
fine when the requested window is one request's worth of data. But fine-grained
intervals over long ranges can't be fetched that way: Yahoo caps how far back
each interval reaches AND how much you can ask for at once, so e.g. a month of
1-minute bars has to be assembled from several ~7-day requests. That takes long
enough that the UI needs a progress indicator rather than a frozen spinner.

So this mirrors dataset_service's job model (background asyncio task, chunked
fetch, cooperative cancel, progress counter) but WITHOUT the persistence: these
are ephemeral view fetches, not stored datasets, so jobs live in memory and are
reaped on a TTL.

Important limits (empirically verified against the live API, not just docs):
``1m`` returns nothing beyond ~30 days back and ``1h`` nothing beyond ~730 days,
no matter how the requests are chunked -- the cap is enforced on Yahoo's side.
Chunking buys throughput, not history depth. Requests reaching past a cap are
clamped and report ``effective_start`` so the caller can say so plainly instead
of silently showing a shorter window than asked for.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from fastapi import HTTPException

from .yfinance_service import INTERVAL_MAP, bars_from_hist

# Max days per single yfinance request, per interval. Smaller than the hard
# caps below so progress moves in visible steps on long pulls.
CHUNK_DAYS: dict[str, int] = {"1m": 7, "1h": 60, "1d": 730, "1wk": 1825, "1mo": 3650}

# How far back each interval can reach AT ALL (Yahoo-side retention).
MAX_LOOKBACK_DAYS: dict[str, int] = {"1m": 30, "1h": 730}

# Roughly how many days each UI range covers, for turning a range into a window.
RANGE_DAYS: dict[str, int] = {
    "30M": 1, "1H": 1, "5H": 1, "1D": 1, "5D": 5,
    "1M": 31, "3M": 92, "6M": 183, "YTD": 365, "1Y": 366, "5Y": 1826, "MAX": 7300,
}

JOB_TTL_SECONDS = 900  # reap finished jobs after 15 minutes

_JOBS: dict[str, dict] = {}
_TASKS: set[asyncio.Task] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reap() -> None:
    """Drop jobs whose results nobody has collected in a while."""
    cutoff = time.time() - JOB_TTL_SECONDS
    for jid in [j for j, m in _JOBS.items() if m["_touched"] < cutoff]:
        _JOBS.pop(jid, None)


def _public(meta: dict) -> dict:
    """Job state minus internal bookkeeping (and minus bars unless ready)."""
    out = {k: v for k, v in meta.items() if not k.startswith("_")}
    if meta["status"] != "ready":
        out.pop("bars", None)
    return out


def _chunk_ranges(start: pd.Timestamp, end: pd.Timestamp, chunk_days: int) -> list[tuple]:
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=chunk_days), end)
        out.append((cur, nxt))
        cur = nxt
    return out or [(start, end)]


async def _run(job_id: str, ticker: str, interval_yf: str) -> None:
    meta = _JOBS.get(job_id)
    if meta is None:
        return
    try:
        start_ts = pd.Timestamp(meta["_start"])
        end_ts = pd.Timestamp(meta["_end"])
        chunks = _chunk_ranges(start_ts, end_ts, CHUNK_DAYS.get(interval_yf, 730))

        meta.update(status="running", progress={"done": 0, "total": len(chunks)}, _touched=time.time())

        all_bars: list[dict] = []
        ticker_obj = yf.Ticker(ticker)
        for i, (c_start, c_end) in enumerate(chunks):
            # Cooperative cancel between chunks (a request in flight can't be
            # interrupted, so this is the granularity we can offer).
            if meta.get("cancel_requested"):
                meta.update(status="cancelled", _touched=time.time())
                return
            hist = await asyncio.to_thread(
                ticker_obj.history,
                start=c_start.strftime("%Y-%m-%d"),
                end=c_end.strftime("%Y-%m-%d"),
                interval=interval_yf,
            )
            if not hist.empty:
                all_bars.extend(bars_from_hist(hist))
            meta.update(progress={"done": i + 1, "total": len(chunks)}, _touched=time.time())

        # Chunk boundaries can overlap; de-dupe and sort.
        seen, deduped = set(), []
        for b in sorted(all_bars, key=lambda b: b["timestamp"]):
            if b["timestamp"] in seen:
                continue
            seen.add(b["timestamp"])
            deduped.append(b)

        meta.update(status="ready", bars=deduped, row_count=len(deduped), _touched=time.time())
    except Exception as e:  # noqa: BLE001 -- surface it on the job, don't kill the worker
        meta.update(status="error", error=str(e), _touched=time.time())


def create_job(ticker: str, range_: str, interval: str) -> dict:
    """Kick off a chunked fetch; returns the job immediately (status pending)."""
    _reap()
    interval_yf = INTERVAL_MAP.get(interval.lower())
    if interval_yf is None:
        raise HTTPException(status_code=400, detail=f"unknown interval '{interval}'")

    days = RANGE_DAYS.get(range_.upper(), 31)
    end_ts = pd.Timestamp.utcnow().tz_localize(None)
    start_ts = end_ts - timedelta(days=days)

    # Clamp to what this interval can actually reach, and say so.
    lookback = MAX_LOOKBACK_DAYS.get(interval_yf)
    effective_start = start_ts
    clamped = False
    if lookback is not None:
        earliest = end_ts - timedelta(days=lookback)
        if start_ts < earliest:
            effective_start, clamped = earliest, True

    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {
        "id": job_id, "ticker": ticker.upper(), "range": range_.upper(), "interval": interval,
        "status": "pending", "created_at": _now(),
        "progress": {"done": 0, "total": 1}, "row_count": 0,
        "error": None, "cancel_requested": False,
        # Present only when the request reached past the interval's hard limit.
        "effective_start": effective_start.isoformat() if clamped else None,
        "requested_start": start_ts.isoformat(),
        "bars": [],
        "_start": effective_start, "_end": end_ts, "_touched": time.time(),
    }

    task = asyncio.create_task(_run(job_id, ticker, interval_yf))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return _public(_JOBS[job_id])


def get_job(job_id: str) -> dict:
    meta = _JOBS.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"history job '{job_id}' not found")
    meta["_touched"] = time.time()
    return _public(meta)


def cancel_job(job_id: str) -> dict:
    meta = _JOBS.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"history job '{job_id}' not found")
    if meta["status"] in ("pending", "running"):
        meta["cancel_requested"] = True
    meta["_touched"] = time.time()
    return _public(meta)
