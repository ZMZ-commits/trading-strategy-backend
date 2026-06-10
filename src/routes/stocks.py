from fastapi import APIRouter, HTTPException
from ..services import yfinance_service, indicators_service

router = APIRouter()


@router.get("/stocks/{ticker}")
def get_snapshot(ticker: str):
    try:
        return yfinance_service.get_snapshot(ticker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocks/{ticker}/history")
def get_history(ticker: str, range: str = "1M", interval: str | None = None):
    try:
        return yfinance_service.get_history(ticker, range, interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocks/{ticker}/indicators")
def get_indicators(ticker: str, range: str = "1M", studies: str = "", interval: str | None = None):
    study_list = [s for s in (studies or "").split(",") if s.strip()]
    try:
        return indicators_service.compute(ticker, range, study_list, interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/indices")
def get_indices():
    return yfinance_service.get_indices()
