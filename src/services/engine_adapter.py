from trading_strategy_engine import run_strategy as _run, get_status as _get_status
from trading_strategy_engine.models import RunResult


def run_strategy(strategy_id: str, config: dict) -> RunResult:
    from .strategy_store import STORE_ROOT
    return _run(strategy_id=strategy_id, config=config, store_path=STORE_ROOT)


def get_status(strategy_id: str) -> RunResult:
    from .strategy_store import STORE_ROOT
    return _get_status(strategy_id=strategy_id, store_path=STORE_ROOT)
