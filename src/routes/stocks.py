from fastapi import APIRouter, HTTPException
from ..services import yfinance_service

router = APIRouter()


@router.get("/stocks/{ticker}")
def get_snapshot(ticker: str):
    try:
        return yfinance_service.get_snapshot(ticker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocks/{ticker}/history")
def get_history(ticker: str, range: str = "1M"):
    try:
        return yfinance_service.get_history(ticker, range)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/indices")
def get_indices():
    return yfinance_service.get_indices()
