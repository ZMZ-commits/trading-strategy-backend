import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import strategies, execution, stocks, live, custom, workspace, datasets

app = FastAPI(title="Trading Strategy Backend", version="0.1.0")

_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
origins = [o.strip() for o in _raw.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
app.include_router(execution.router, prefix="/strategies", tags=["execution"])
app.include_router(stocks.router, tags=["stocks"])
app.include_router(live.router, tags=["live"])
app.include_router(custom.router, tags=["custom"])
app.include_router(workspace.router, tags=["workspace"])
app.include_router(datasets.router, tags=["datasets"])
