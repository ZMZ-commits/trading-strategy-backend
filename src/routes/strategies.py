from fastapi import APIRouter
from ..models.strategy import CreateStrategyRequest, Strategy
from ..services import strategy_store

router = APIRouter()


@router.get("", response_model=list[Strategy])
def get_strategies():
    return strategy_store.list_strategies()


@router.post("", response_model=Strategy, status_code=201)
def create_strategy(body: CreateStrategyRequest):
    return strategy_store.create_strategy(body.name)


@router.delete("/{strategy_id}", status_code=204)
def delete_strategy(strategy_id: str):
    strategy_store.delete_strategy(strategy_id)
