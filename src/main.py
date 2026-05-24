from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import strategies, execution, stocks

app = FastAPI(title="Trading Strategy Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
app.include_router(execution.router, prefix="/strategies", tags=["execution"])
app.include_router(stocks.router, tags=["stocks"])
