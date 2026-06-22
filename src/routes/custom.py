"""Custom (user-published) indicators — computed in the sandbox.

GET /stocks/{ticker}/custom/{slug}: fetch the ticker's bars, then delegate to the
sandbox worker which runs the published compute(ctx) and returns the series in the
same shape as the built-in /indicators endpoint.
"""
from fastapi import APIRouter, HTTPException

from ..services import yfinance_service, sandbox_client

router = APIRouter()


@router.get("/stocks/{ticker}/custom/{slug}")
def custom_indicator(ticker: str, slug: str, range: str = "1M", interval: str | None = None):
    try:
        hist = yfinance_service.get_history(ticker, range, interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return sandbox_client.run_custom(slug, hist["bars"])
    except Exception as e:  # sandbox not deployed / unreachable / author error
        raise HTTPException(status_code=502, detail=f"sandbox unavailable or failed: {e}")
