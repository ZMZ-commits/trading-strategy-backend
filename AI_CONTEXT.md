# AI_CONTEXT — trading-strategy-backend

> Per-repo living context for AI assistants. The **overall system** is documented
> in the platform repo: `trading-strategy-platform/docs/ARCHITECTURE.md`. Start a
> session by reading that + this file, then recompute the newest branch
> (`docs/AI_ONBOARDING.md` §2). **Live git state always wins over this snapshot.**
>
> **Last synced:** 2026-06-13 · **Newest branch at sync:** `main` (fully promoted)

---

## 1. What this repo is

The **API hub** — a FastAPI app that the UI talks to. It serves stock data
(via yfinance), computes technical indicators server-side, stores strategies on
the filesystem, runs them through the in-process `trading-strategy-engine`
package, and fans out live ticks from Redis over WebSocket.

- **Run locally:** `pip install -r requirements.txt && python src/main.py` (or `uvicorn src.main:app`)
- **Docs:** FastAPI auto-docs at `/docs`
- **Key env vars:** `CORS_ORIGINS`, `STORE_ROOT`, `REDIS_URL`

---

## 2. Branches & environments

| Env | Branch | URL | Image |
|-----|--------|-----|-------|
| Production | `main` | `api.zemingzhang.com` | `ghcr.io/zmz-commits/trading-strategy-backend:prod` |
| Staging | `staging` | `api-stg.zemingzhang.com` | `…:stg` |
| Dev | `dev` | `api-dev.zemingzhang.com` | `…:dev` |

3 backends run side-by-side on the Hetzner VM behind Caddy, each with its own
`/data/{env}` strategy store, all sharing the one Redis. CI: `deploy-{dev,staging,prod}.yml`.

---

## 3. Functions & modules (what the code does)

### `src/main.py`
- Builds the FastAPI app; CORS from `CORS_ORIGINS` (comma-split). Mounts routers:
  `strategies` + `execution` under `/strategies`, `stocks` and `live` at root.

### `src/routes/stocks.py` — market data endpoints
- `GET /stocks/{ticker}` → `get_snapshot` — price/OHLC/volume/marketCap/52wk.
- `GET /stocks/{ticker}/history?range=&interval=` → `get_history` — OHLCV bars.
- `GET /stocks/{ticker}/indicators?range=&studies=&interval=` → computed studies.
- `GET /market/indices` → `get_indices` — S&P/NASDAQ/DOW/VIX quotes.

### `src/routes/strategies.py` — strategy CRUD
- `GET /strategies` → list · `POST /strategies` → create (409 if name taken) ·
  `DELETE /strategies/{id}` → 204.

### `src/routes/execution.py` — run/status
- `POST /strategies/{id}/run` → 202; 404 if unknown. Calls engine adapter.
- `GET /strategies/{id}/status` → latest `RunResult`.

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
  `_stoch`, `_squeeze` (+ `_linreg_endpoint`). Studies parsed like `sma50`,
  `ema20`, `bbands`, `rsi`, `macd`, `stoch`, `vwap`, `squeeze`.

### `src/services/strategy_store.py` — filesystem persistence
- `STORE_ROOT` (env). Each strategy = a dir (`slugify`d) with `strategy.json` +
  `runs/`. `create_strategy` (409 on dup), `list_strategies`, `get_strategy`,
  `delete_strategy`.

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
- 3-env Dockerized deploy; env-driven CORS/store/Redis. Test suite under `tests/`.

---

## 5. Latest Changes (Living)
> Prepend newest first. Note the branch. Recompute with
> `git log origin/main --no-merges --oneline`.

- **2026-06-13** (`main`) — align indicator series to the price window for custom intervals.
- **2026-06-11** (`main`) — clamp indicator data to last non-NaN price bar (no line overhang).
- **2026-06-10** (`main`) — optional `interval` override on history + indicators; CI renamed to Hetzner; lowercase GHCR owner fix; skip NaN OHLC rows (no 500 on 1M/1Y/5Y/MAX).
- **2026-06-09** (`main`) — VWAP intraday-only; 3-tier branching docs; dev deploy triggers on `dev`.
- **2026-06-08** (`main`) — warmup buffer so indicators span the whole window.
- **2026-06-07** (`main`) — hand-rolled pandas indicators (dropped pandas-ta); `/indicators` endpoint; `/ws/live/{ticker}`; intraday ranges.

## 6. What's next / TODO
- _(add upcoming work here so the next session sees it)_
