from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class CreateStrategyRequest(BaseModel):
    name: str


class Strategy(BaseModel):
    id: str
    name: str
    slug: str
    created_at: datetime
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = "idle"
    dir_path: str
