from fastapi import APIRouter, HTTPException
from ..models.execution import RunRequest
from ..services import engine_adapter, strategy_store

router = APIRouter()


@router.post("/{strategy_id}/run", status_code=202)
def run_strategy(strategy_id: str, body: RunRequest = RunRequest()):
    if not strategy_store.get_strategy(strategy_id):
        raise HTTPException(status_code=404, detail="Strategy not found")
    result = engine_adapter.run_strategy(strategy_id, body.config)
    return result.model_dump(mode="json")


@router.get("/{strategy_id}/status")
def get_strategy_status(strategy_id: str):
    if not strategy_store.get_strategy(strategy_id):
        raise HTTPException(status_code=404, detail="Strategy not found")
    result = engine_adapter.get_status(strategy_id)
    return result.model_dump(mode="json")
