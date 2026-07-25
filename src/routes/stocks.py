from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..services import yfinance_service, indicators_service, history_job_service

router = APIRouter()


@router.get("/stocks/{ticker}")
def get_snapshot(ticker: str):
    try:
        return yfinance_service.get_snapshot(ticker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocks/{ticker}/history")
def get_history(ticker: str, range: str = "1M", interval: str | None = None,
                start: str | None = None, end: str | None = None):
    try:
        return yfinance_service.get_history(ticker, range, interval, start, end)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocks/{ticker}/indicators")
def get_indicators(ticker: str, range: str = "1M", studies: str = "", interval: str | None = None,
                   start: str | None = None, end: str | None = None):
    study_list = [s for s in (studies or "").split(",") if s.strip()]
    try:
        return indicators_service.compute(ticker, range, study_list, interval, start, end)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/market/indices")
def get_indices():
    return yfinance_service.get_indices()


class ComputeIndicatorsRequest(BaseModel):
    bars: list[dict]
    studies: list[str]


@router.post("/indicators/compute")
def compute_indicators(req: ComputeIndicatorsRequest):
    """Compute indicators over CALLER-SUPPLIED bars (Lab Platform datasets,
    possibly resampled) instead of a live yfinance fetch -- same math as the
    live /stocks/{ticker}/indicators endpoint, so the two can never disagree."""
    try:
        return indicators_service.compute_from_bars(req.bars, req.studies)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Chunked history jobs ─────────────────────────────────────────────────
# For fine intervals over long ranges, which need several sequential yfinance
# requests and so want a progress indicator instead of one long hang.
#
# NOTE: `async def` (not plain `def`) so FastAPI runs these on the event loop
# rather than a worker thread -- history_job_service calls asyncio.create_task()
# internally, which needs a running loop in the calling context.

class CreateHistoryJobRequest(BaseModel):
    range: str
    interval: str


@router.post("/stocks/{ticker}/history/jobs")
async def create_history_job(ticker: str, req: CreateHistoryJobRequest):
    return history_job_service.create_job(ticker, req.range, req.interval)


@router.get("/stocks/history/jobs/{job_id}")
async def get_history_job(job_id: str):
    return history_job_service.get_job(job_id)


@router.post("/stocks/history/jobs/{job_id}/cancel")
async def cancel_history_job(job_id: str):
    return history_job_service.cancel_job(job_id)
