import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import strategies, execution, stocks, live, custom, workspace, datasets

# Interactive docs are OFF, in every environment.
#
# FastAPI publishes /docs, /redoc and /openapi.json by default. On an API that
# required credentials that would be a convenience; on this one it is a working
# control panel. There is no authentication on any endpoint, and 18 of them
# write -- create a strategy, delete one, execute code via
# POST /strategies/{id}/run. /docs renders all of that as a form with a
# "Try it out" button, so finding the API and using it are the same step.
#
# This is NOT a fix for the missing auth, and should not be mistaken for one.
# Hiding endpoints is not security: anyone who knows the paths can still call
# them, and the UI's own source lists most of them. It removes casual discovery
# while real authentication is put in front of the API.
#
# openapi_url=None is what actually disables it. /docs and /redoc are rendered
# FROM the spec, so leaving the spec served would keep the surface published
# even with the two UIs turned off.
app = FastAPI(
    title="Trading Strategy Backend",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

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
