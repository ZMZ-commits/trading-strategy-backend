"""Live tick WebSocket — fans out Redis pub/sub to browser clients.

The data pipeline publishes normalized ticks to Redis channel `ticks:{SYMBOL}`.
This endpoint subscribes a browser to that channel and forwards every tick.
On connect it also sends the last cached price so the client isn't blank.
"""
from __future__ import annotations
import asyncio
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


@router.websocket("/ws/live/{ticker}")
async def live_ticks(ws: WebSocket, ticker: str) -> None:
    await ws.accept()
    symbol = ticker.upper()
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"ticks:{symbol}")

    # Immediately send the last known price so the chart isn't empty on connect.
    cached = await r.get(f"price:{symbol}")
    if cached:
        await ws.send_text(cached)

    async def forward() -> None:
        async for message in pubsub.listen():
            if message.get("type") == "message":
                await ws.send_text(message["data"])

    async def watch_client() -> None:
        # Resolves when the browser disconnects, so we can tear down cleanly.
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            return

    fwd = asyncio.create_task(forward())
    watch = asyncio.create_task(watch_client())
    try:
        await asyncio.wait({fwd, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        fwd.cancel()
        watch.cancel()
        try:
            await pubsub.unsubscribe(f"ticks:{symbol}")
            await pubsub.aclose()
        except Exception:
            pass
        await r.aclose()
