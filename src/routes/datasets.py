"""Lab Platform: create/list/inspect stored datasets, and run backtests
(a strategy against a stored dataset) as tracked, cancellable jobs.

NOTE: handlers are `async def` (not plain `def`) so FastAPI runs them directly
on the event loop instead of dispatching to a worker thread -- dataset_service
calls asyncio.create_task() internally to kick off the background pull/
backtest job, which needs a running loop in the calling context.
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
    name: str | None = None


@router.post("/datasets")
async def create_dataset(req: CreateDatasetRequest):
    return dataset_service.create_dataset(req.ticker, req.start, req.end, req.interval, req.name)


@router.get("/datasets")
async def list_datasets():
    return {"datasets": dataset_service.list_datasets()}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    return dataset_service.get_dataset(dataset_id)


@router.get("/datasets/{dataset_id}/bars")
async def get_dataset_bars(dataset_id: str):
    return {"bars": dataset_service.get_dataset_bars(dataset_id)}


@router.post("/datasets/{dataset_id}/cancel")
async def cancel_dataset(dataset_id: str):
    return dataset_service.cancel_dataset(dataset_id)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    dataset_service.delete_dataset(dataset_id)
    return {"deleted": dataset_id}


class CreateBacktestRequest(BaseModel):
    strategy_slug: str


@router.post("/datasets/{dataset_id}/backtests")
async def create_backtest(dataset_id: str, req: CreateBacktestRequest):
    return dataset_service.create_backtest(dataset_id, req.strategy_slug)


@router.get("/datasets/{dataset_id}/backtests")
async def list_backtests(dataset_id: str):
    return {"backtests": dataset_service.list_backtests(dataset_id)}


@router.get("/datasets/{dataset_id}/backtests/{backtest_id}")
async def get_backtest(dataset_id: str, backtest_id: str):
    return dataset_service.get_backtest(dataset_id, backtest_id)


@router.post("/datasets/{dataset_id}/backtests/{backtest_id}/cancel")
async def cancel_backtest(dataset_id: str, backtest_id: str):
    return dataset_service.cancel_backtest(dataset_id, backtest_id)


@router.delete("/datasets/{dataset_id}/backtests/{backtest_id}")
async def delete_backtest(dataset_id: str, backtest_id: str):
    dataset_service.delete_backtest(dataset_id, backtest_id)
    return {"deleted": backtest_id}


# ── Label sets ───────────────────────────────────────────────────────────
# Hand-marked buy/sell points on a dataset. Same shape as backtest signals, so
# the chart renders a labelled set and a strategy's output through one path.

class CreateLabelSetRequest(BaseModel):
    name: str | None = None


class SaveLabelMarksRequest(BaseModel):
    marks: list[dict]
    name: str | None = None


@router.post("/datasets/{dataset_id}/labels")
async def create_label_set(dataset_id: str, req: CreateLabelSetRequest):
    return dataset_service.create_label_set(dataset_id, req.name)


@router.get("/datasets/{dataset_id}/labels")
async def list_label_sets(dataset_id: str):
    return {"labels": dataset_service.list_label_sets(dataset_id)}


@router.get("/datasets/{dataset_id}/labels/{label_id}")
async def get_label_set(dataset_id: str, label_id: str):
    return dataset_service.get_label_set(dataset_id, label_id)


@router.put("/datasets/{dataset_id}/labels/{label_id}")
async def save_label_marks(dataset_id: str, label_id: str, req: SaveLabelMarksRequest):
    return dataset_service.save_label_marks(dataset_id, label_id, req.marks, req.name)


@router.delete("/datasets/{dataset_id}/labels/{label_id}")
async def delete_label_set(dataset_id: str, label_id: str):
    dataset_service.delete_label_set(dataset_id, label_id)
    return {"deleted": label_id}


# ── Drawings ─────────────────────────────────────────────────────────────

class SaveDrawingsRequest(BaseModel):
    drawings: list[dict]


@router.get("/datasets/{dataset_id}/drawings")
async def get_drawings(dataset_id: str):
    return {"drawings": dataset_service.get_drawings(dataset_id)}


@router.put("/datasets/{dataset_id}/drawings")
async def save_drawings(dataset_id: str, req: SaveDrawingsRequest):
    return {"drawings": dataset_service.save_drawings(dataset_id, req.drawings)}
