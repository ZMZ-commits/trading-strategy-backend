# AI_CONTEXT — trading-strategy-backend

> Per-repo living context for AI assistants. The **overall system** is documented
> in the platform repo: `trading-strategy-platform/docs/ARCHITECTURE.md`. Start a
> session by reading that + this file, then recompute the newest branch
> (`docs/AI_ONBOARDING.md` §2). **Live git state always wins over this snapshot.**
>
> **Last synced:** 2026-10-24 · **Newest branch at sync:** `main` (fully
> promoted — `dev`/`staging` are content-identical, behind only by merge commits)

---

## 1. What this repo is

The **API hub** — a FastAPI app that the UI talks to. It serves stock data
(via yfinance), computes technical indicators server-side, stores strategies on
the filesystem, runs them through the `trading-strategy-engine` package and the
sandbox worker, hosts the **Lab Platform** (stored datasets, backtests, label
sets, chart drawings), and fans out live ticks from Redis over WebSocket.

- **Run locally:** `pip install -r requirements.txt && python src/main.py` (or `uvicorn src.main:app`)
- **Key env vars:** `CORS_ORIGINS`, `STORE_ROOT`, `REDIS_URL`, `DATASET_ROOT`,
  `IDE_WORKSPACE`, `SANDBOX_URL`

### ⚠️ Two things to know before you touch this API

**1. `/docs`, `/redoc` and `/openapi.json` are OFF, in every environment**
(since 2026-10-07). Not env-gated — off. The app is constructed with
`openapi_url=None`, which is what actually disables it; `/docs` and `/redoc` are
rendered *from* the spec, so turning off only those two would keep the surface
published. If you are looking for the endpoint list, it is §3 of this file and
the route decorators — not a browser.

**2. That is not security, and must not be mistaken for it.** There is **no
authentication on any endpoint**, and 18 of them write — create a strategy,
delete one, execute code via `POST /strategies/{id}/run`. Hiding the docs
removes casual discovery; anyone who knows the paths can still call them, and
the UI's own JavaScript lists most of them. An API key does not fix this either,
because the browser makes those calls and a key in browser JS is public. The
intended fix is **Cloudflare Access** in front of the API. Until that exists,
treat every endpoint here as world-writable.

---

## 2. Branches & environments

| Env | Branch | URL | Image |
|-----|--------|-----|-------|
| Production | `main` | `api.zemingzhang.com` | `ghcr.io/zmz-commits/trading-strategy-backend:prod` |
| Staging | `staging` | `api-stg.zemingzhang.com` | `…:stg` |
| Dev | `dev` | `api-dev.zemingzhang.com` | `…:dev` |

3 backends run side-by-side on the Hetzner VM behind Caddy, each with its own
`/data/{env}` strategy store, all sharing the one Redis. CI: `deploy-{dev,staging,prod}.yml`.

**They are also running in the k3s cluster** as of 2026-10 (namespace `tsp`,
Phase 3–4 of the platform's `docs/K8S_MIGRATION.md`) — same images, reached by
`kubectl port-forward`, no ingress yet. The VM still serves the real hostnames.
In the cluster all three pods and the sandbox are **pinned to one node**,
because they share a `ReadWriteOnce` `workspace` volume; see `storage.tf` there
for what that costs.

---

## 3. Functions & modules (what the code does)

### `src/main.py`
- Builds the FastAPI app; CORS from `CORS_ORIGINS` (comma-split). Mounts routers:
  `strategies` + `execution` under `/strategies`, `stocks` and `live` at root.

### `src/routes/stocks.py` — market data endpoints
- `GET /stocks/{ticker}` → `get_snapshot` — price/OHLC/volume/marketCap/52wk.
- `GET /stocks/{ticker}/history?range=&interval=&start=&end=` → `get_history`.
- `GET /stocks/{ticker}/indicators?range=&studies=&interval=` → computed studies.
- `GET /market/indices` → `get_indices` — S&P/NASDAQ/DOW/VIX quotes.
- `POST /indicators/compute` — indicators from **arbitrary bars** in the request
  body rather than a ticker fetch. This is what lets the Lab compute studies on
  a stored dataset.
- `POST /stocks/{ticker}/history/jobs` · `GET /stocks/history/jobs/{job_id}` ·
  `POST /stocks/history/jobs/{job_id}/cancel` — chunked, progress-tracked
  fetches (see `history_job_service`).

### `src/routes/strategies.py` — strategy CRUD
- `GET /strategies` → list · `POST /strategies` → create (409 if name taken) ·
  `DELETE /strategies/{id}` → 204.

### `src/routes/execution.py` — run/status
- `POST /strategies/{id}/run` → 202; 404 if unknown. Calls engine adapter.
- `GET /strategies/{id}/status` → latest `RunResult`.

### `src/routes/custom.py` — published (user-authored) code
- `GET /custom` — list published indicators (via the sandbox).
- `GET /stocks/{ticker}/custom/{slug}` — fetch bars, then delegate to the
  sandbox worker to run a published indicator.
- `GET /stocks/{ticker}/strategy/{slug}` — same, for a published strategy.

### `src/routes/workspace.py` — the IDE workspace
- `GET /workspace/items` · `POST /workspace/scaffold` (accepts explicit file
  content + filename) · `DELETE /workspace/{kind}/{slug}`.
- Writes under `IDE_WORKSPACE` (`/workspace`), the volume shared with
  code-server and read-only-mounted by the sandbox. **This is the volume that
  forces the node pinning in the cluster.**

### `src/routes/datasets.py` — the Lab Platform
Four groups under `/datasets`:
- **Datasets** — `POST` (start a pull) · `GET` list · `GET {id}` ·
  `GET {id}/bars` · `POST {id}/cancel` · `DELETE {id}`.
- **Backtests** — `POST|GET /datasets/{id}/backtests` ·
  `GET|DELETE …/{bid}` · `POST …/{bid}/cancel`.
- **Label sets** — hand-marked buy/sell points, full CRUD per dataset.
- **Drawings** — `GET|PUT /datasets/{id}/drawings`, hand-drawn chart
  annotations stored as **anchor points** (not pixels), so they survive a
  zoom or a range change.

### `src/routes/live.py` — live tick WebSocket
- `WS /ws/live/{ticker}` — subscribes Redis `ticks:{SYMBOL}`, forwards each tick
  to the browser; sends cached `price:{SYMBOL}` on connect; tears down cleanly on
  disconnect. `REDIS_URL` env.

### `src/services/yfinance_service.py`
- `get_history` — maps UI ranges (`30M`…`MAX`) → yfinance (period, interval,
  tail); optional `interval` override; skips NaN OHLC rows; rounds; tails
  intraday windows.
- `get_snapshot` — fast_info + best-effort full info (name, marketCap, 52wk).
- `get_indices` — index quotes with day change/%.
- `RANGE_MAP`, `INTERVAL_MAP`, `INDEX_SYMBOLS`/`INDEX_NAMES`.

### `src/services/indicators_service.py`
- `compute(ticker, range, studies, interval?)` — hand-rolled TA in pandas/numpy
  (no external TA lib). Fetches a **warmup** buffer larger than the visible
  window so long-lookback studies (e.g. SMA200) resolve, computes over the full
  series, then trims to the price window so lines align 1:1 with candles.
- Indicators: `_sma`, `_ema`, `_rsi`, `_macd`, `_bbands`, `_vwap` (intraday only),
  `_stoch`, `_squeeze` (+ `_linreg_endpoint`), `_donchian`. Studies parsed like
  `sma50`, `ema20`, `bbands`, `rsi`, `macd`, `stoch`, `vwap`, `squeeze`,
  `donchian`.

### `src/services/strategy_store.py` — filesystem persistence
- `STORE_ROOT` (env). Each strategy = a dir (`slugify`d) with `strategy.json` +
  `runs/`. `create_strategy` (409 on dup), `list_strategies`, `get_strategy`,
  `delete_strategy`.

### `src/services/dataset_service.py` — Lab datasets + backtests
- Pull OHLCV **once** for ticker+range+interval, store on disk, re-serve
  statically — no repeated live yfinance calls.
- Pulls and backtests run as background asyncio tasks, **chunked** so progress
  and cancellation mean something. Cancellation is a cooperative flag re-read
  from disk between chunks; a yfinance call already in flight cannot be
  interrupted.
- Backtests delegate execution to the sandbox worker — the same path live runs
  use — but need **no warmup**, because the stored dataset *is* the display
  window.
- Layout under `DATASET_ROOT`: `<id>/meta.json`, `<id>/bars.json`,
  `<id>/backtests/<bid>.json`.

### `src/services/history_job_service.py` — chunked view fetches
- Same job model as `dataset_service` (background task, chunked, cooperative
  cancel, progress) but **without persistence** — these are ephemeral view
  fetches, so jobs live in memory and are reaped on a TTL.
- **Yahoo's caps are enforced server-side and chunking does not beat them:**
  `1m` returns nothing past ~30 days, `1h` nothing past ~730 days, however the
  requests are split. Chunking buys throughput, not depth. Requests reaching
  past a cap are clamped and report `effective_start`, so the UI can say so
  instead of quietly showing a shorter window than asked for.

### `src/services/sandbox_client.py`
- HTTP client for the sandbox worker (`SANDBOX_URL`). Passes the sandbox's HTTP
  status and response body through on error, rather than flattening everything
  to a 500 — the whole point is seeing *why* user code failed.

### `src/services/engine_adapter.py`
- Thin bridge to the `trading_strategy_engine` package: `run_strategy` /
  `get_status`, passing `STORE_ROOT` as the store path.

### `src/models/`
- `strategy.py` — `CreateStrategyRequest`, `Strategy`. `execution.py` — `RunRequest`.

---

## 4. Features
- yfinance-backed history, snapshot, indices; intraday ranges (30M/1H/5H) + custom
  interval override.
- Server-side technical indicators (SMA/EMA/RSI/MACD/Bollinger/VWAP/Stochastic/Squeeze)
  with warmup + window alignment.
- File-based strategy store (no DB); in-process engine execution; run history.
- Live tick fan-out from Redis over WebSocket.
- Custom (user-published) indicators **and strategies** via the sandbox worker.
- **Lab Platform:** stored datasets (pull once, serve statically), backtests as
  tracked jobs, label sets, and anchor-point chart drawings.
- Chunked, cancellable, progress-reporting history jobs for fine intervals over
  long ranges — with Yahoo's hard depth caps surfaced rather than hidden.
- IDE workspace scaffolding (`/workspace/*`) into the volume code-server edits.
- 3-env Dockerized deploy; env-driven CORS/store/Redis. Test suite under `tests/`.
- Interactive API docs **disabled** in all environments — see §1.

---

## 5. Latest Changes (Living)
> Prepend newest first. Note the branch. Recompute with
> `git log origin/main --no-merges --oneline`.

- **2026-10-07** (`main`) — stop publishing the API surface at `/docs`.
  `openapi_url=None` as well as the two UIs. **Not** a fix for the missing auth
  (see §1).
- **2026-08-15** (`main`) — link the live environments from the README.
- **2026-08-08** (`main`) — generalise drawing storage to **anchor points**, so
  annotations survive zoom and range changes.
- **2026-08-07** (`main`) — store hand-drawn chart annotations per dataset;
  Donchian channel as a chartable indicator.
- **2026-08-01** (`main`) — label sets: hand-marked buy/sell points per dataset.
- **2026-07-25** (`main`) — chunked history jobs with progress for fine
  intervals over long ranges; then a fix so the job reports its **real** chunk
  count from the first response rather than an estimate.
- **2026-07-15…18** (`main`) — Lab Platform: dataset store + backtest jobs;
  dataset naming; indicators from arbitrary bars; delete a backtest run.
- **2026-07-02** (`main`) — enough warmup for 30M/1H/5H long-lookback averages;
  strategies fetched with a warmup buffer trimmed to `display_start`.
- **2026-06-28…30** (`main`) — `/workspace/*` scaffold + delete; custom date
  window (`start`/`end`); `GET /stocks/{ticker}/strategy/{slug}`.
- **2026-06-23** (`main`) — remove JupyterLab integration (replaced by the
  code-server web IDE).
- **2026-06-22** (`dev`→prod) — `GET /stocks/{ticker}/custom/{slug}`: fetch bars then delegate to the sandbox worker to run published indicators (`routes/custom.py` + `services/sandbox_client.py`, `SANDBOX_URL`). Phase 1b loop, verified end-to-end.
- **2026-06-21** (`main`) — added 3M/6M/YTD range presets; renamed 1W→5D.
- **2026-06-13** (`main`) — align indicator series to the price window for custom intervals.
- **2026-06-11** (`main`) — clamp indicator data to last non-NaN price bar (no line overhang).
- **2026-06-10** (`main`) — optional `interval` override on history + indicators; CI renamed to Hetzner; lowercase GHCR owner fix; skip NaN OHLC rows (no 500 on 1M/1Y/5Y/MAX).
- **2026-06-09** (`main`) — VWAP intraday-only; 3-tier branching docs; dev deploy triggers on `dev`.
- **2026-06-08** (`main`) — warmup buffer so indicators span the whole window.
- **2026-06-07** (`main`) — hand-rolled pandas indicators (dropped pandas-ta); `/indicators` endpoint; `/ws/live/{ticker}`; intraday ranges.

## 6. What's next / TODO
- **Authentication.** The open item that matters most. Cloudflare Access in
  front of `api{,-stg,-dev}.zemingzhang.com`; an API key cannot work here
  because the browser makes the write calls. See §1.
- **`tests/test_stocks.py::test_history` fails on an unmodified `dev`** — it
  predates the current change and is not caused by it. Worth fixing or
  quarantining so a red suite stops being normal.
- Finish the cluster move (platform `docs/K8S_MIGRATION.md` phases 4–8). The
  pods run there but serve no real traffic yet.
