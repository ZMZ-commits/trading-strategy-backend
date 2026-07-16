"""Lab Platform: create/list/inspect stored datasets, and run backtests
(a strategy against a stored dataset) as tracked, cancellable jobs.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from ..services import dataset_service

router = APIRouter()


class CreateDatasetRequest(BaseModel):
    ticker: str
    start: str
    end: str
    interval: str


@router.post("/datasets")
def create_dataset(req: CreateDatasetRequest):
    return dataset_service.create_dataset(req.ticker, req.start, req.end, req.interval)


@router.get("/datasets")
def list_datasets():
    return {"datasets": dataset_service.list_datasets()}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    return dataset_service.get_dataset(dataset_id)


@router.get("/datasets/{dataset_id}/bars")
def get_dataset_bars(dataset_id: str):
    return {"bars": dataset_service.get_dataset_bars(dataset_id)}


@router.post("/datasets/{dataset_id}/cancel")
def cancel_dataset(dataset_id: str):
    return dataset_service.cancel_dataset(dataset_id)


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    dataset_service.delete_dataset(dataset_id)
    return {"deleted": dataset_id}


class CreateBacktestRequest(BaseModel):
    strategy_slug: str


@router.post("/datasets/{dataset_id}/backtests")
def create_backtest(dataset_id: str, req: CreateBacktestRequest):
    return dataset_service.create_backtest(dataset_id, req.strategy_slug)


@router.get("/datasets/{dataset_id}/backtests")
def list_backtests(dataset_id: str):
    return {"backtests": dataset_service.list_backtests(dataset_id)}


@router.get("/datasets/{dataset_id}/backtests/{backtest_id}")
def get_backtest(dataset_id: str, backtest_id: str):
    return dataset_service.get_backtest(dataset_id, backtest_id)


@router.post("/datasets/{dataset_id}/backtests/{backtest_id}/cancel")
def cancel_backtest(dataset_id: str, backtest_id: str):
    return dataset_service.cancel_backtest(dataset_id, backtest_id)
