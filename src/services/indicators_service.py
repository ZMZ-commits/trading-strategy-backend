"""Technical indicators computed server-side from OHLCV.

Hand-rolled with pandas/numpy (no external TA dependency). Indicators need
*lookback* — a 50-period SMA needs 50 prior bars — so we fetch a WARMUP buffer
larger than the visible window, compute over the full series, then trim to the
display window. That way indicators span the whole chart instead of only the
right edge.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf


# range -> (fetch_period, interval, (trim_mode, amount))
# trim_mode: "tail" keep last N bars, "days" keep last D calendar days, "all".
IND_CFG: dict[str, tuple[str, str, tuple[str, int]]] = {
    # 30M/1H/5H previously fetched only "1d" of 1-minute bars (~390 total), so a
    # long-lookback average (SMA 200 needs 200 prior bars) ran out of warmup and
    # started partway through the chart instead of from the left edge. "1D"
    # already fetched "5d" for the same reason; match it here too (yfinance's 1m
    # cap is 7 days, so 5d is safely within range).
    "30M": ("5d", "1m", ("tail", 30)),
    "1H": ("5d", "1m", ("tail", 60)),
    "5H": ("5d", "1m", ("tail", 300)),
    "1D": ("5d", "1m", ("tail", 390)),
    "5D": ("1mo", "15m", ("tail", 130)),
    "1M": ("2y", "1d", ("days", 31)),
    "3M": ("2y", "1d", ("days", 92)),
    "6M": ("2y", "1d", ("days", 183)),
    "YTD": ("2y", "1d", ("ytd", 0)),    # warmup 2y, trim to Jan 1 (dynamic)
    "1Y": ("2y", "1d", ("days", 366)),
    "5Y": ("10y", "1wk", ("days", 1830)),
    "MAX": ("max", "1mo", ("all", 0)),
}


# ── indicator math (computed on the FULL warmup series) ─────────
def _sma(s, n): return s.rolling(n).mean()
def _ema(s, n): return s.ewm(span=n, adjust=False).mean()


def _donchian(high, low, entry_n=20, exit_n=10):
    """Donchian channel. Both bands are SHIFTED one bar, so a bar can never
    break out of its own high/low -- the value at bar i reflects only the bars
    before it. Identical to tsp.indicators.donchian (same defaults, same shift)
    so the plotted channel is exactly what a strategy calling ctx.donchian()
    sees; a chart that disagreed with the strategy would be worse than none.
    The bands are deliberately asymmetric (20 up / 10 down): that is the
    breakout convention -- enter on a longer high, exit on a shorter low."""
    return high.rolling(entry_n).max().shift(1), low.rolling(exit_n).min().shift(1)


def _rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close, fast=12, slow=26, signal=9):
    line = _ema(close, fast) - _ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def _bbands(close, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid - k * sd, mid, mid + k * sd


def _vwap(high, low, close, volume):
    tp = (high + low + close) / 3
    return (tp * volume).cumsum() / volume.cumsum().replace(0, np.nan)


def _stoch(high, low, close, k=14, d=3):
    ll, hh = low.rolling(k).min(), high.rolling(k).max()
    fast_k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    slow_k = fast_k.rolling(d).mean()
    return slow_k, slow_k.rolling(d).mean()


def _linreg_endpoint(series, n):
    x = np.arange(n)
    def fit(y):
        if np.isnan(y).any():
            return np.nan
        m, b = np.polyfit(x, y, 1)
        return m * (n - 1) + b
    return series.rolling(n).apply(fit, raw=True)


def _squeeze(high, low, close, n=20):
    basis = _sma(close, n)
    dev = 2.0 * close.rolling(n).std()
    ub, lb = basis + dev, basis - dev
    rng = _sma(high - low, n)
    ukc, lkc = basis + 1.5 * rng, basis - 1.5 * rng
    on = ((lb > lkc) & (ub < ukc)).astype(float)
    hh, ll = high.rolling(n).max(), low.rolling(n).min()
    mid = ((hh + ll) / 2 + _sma(close, n)) / 2
    return _linreg_endpoint(close - mid, n), on


def _trim_start(index: pd.DatetimeIndex, keep: tuple[str, int]) -> int:
    mode, amt = keep
    if mode == "tail":
        return max(0, len(index) - amt)
    if mode == "ytd":
        # Trim to Jan 1 of the most recent bar's year (year-to-date is dynamic).
        cutoff = pd.Timestamp(year=index[-1].year, month=1, day=1, tz=index[-1].tz)
        for i, t in enumerate(index):
            if t >= cutoff:
                return i
    if mode == "days":
        cutoff = index[-1] - pd.Timedelta(days=amt)
        for i, t in enumerate(index):
            if t >= cutoff:
                return i
    return 0


INTERVAL_MAP: dict[str, str] = {
    "1s": "1m", "1m": "1m", "1h": "1h", "1d": "1d", "1w": "1wk", "1mo": "1mo",
}

# When the user overrides the interval we ignore IND_CFG's (range-keyed) period and
# fetch the largest warmup yfinance allows for that interval, so long-lookback
# indicators (SMA200…) can still resolve. yfinance caps: 1m ≤ 7d, 1h ≤ 730d.
OVERRIDE_WARMUP: dict[str, str] = {
    "1m": "7d", "1h": "2y", "1d": "10y", "1wk": "max", "1mo": "max",
}


def compute(ticker: str, range_: str, studies: list[str], interval_override: str | None = None,
            start: str | None = None, end: str | None = None) -> dict:
    ticker_obj = yf.Ticker(ticker)
    out: dict[str, dict] = {}

    if start and end:
        # Custom window: fetch exactly [start, end] at the interval and emit every
        # bar (no extra warmup, so left-edge lookback indicators begin NaN).
        interval = INTERVAL_MAP.get((interval_override or "1d").lower(), "1d")
        hist = ticker_obj.history(start=start, end=end, interval=interval)
        if hist.empty:
            return {"ticker": ticker.upper(), "range": "CUSTOM", "indicators": out}
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
        df = hist.rename(columns=str.lower)
        h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
        start_i = 0
        ts = [t.isoformat() for t in hist.index]
        result_range = "CUSTOM"
    else:
        period, interval, keep = IND_CFG.get(range_.upper(), ("6mo", "1d", ("days", 31)))
        if interval_override:
            interval = INTERVAL_MAP.get(interval_override.lower(), interval)
            # Custom interval: fetch the largest valid warmup for that interval so the
            # indicator math stays warm; the OUTPUT is trimmed to the price window below.
            period = OVERRIDE_WARMUP.get(interval, period)
        hist = ticker_obj.history(period=period, interval=interval)

        if hist.empty:
            return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}

        # Pull the exact window the price chart shows (same ticker + interval) so the
        # indicator lines align 1:1 with the candles instead of floating past them or
        # spanning a far wider range. The warmup fetch above is longer and feeds the
        # indicator math; we then trim the emitted series to this window.
        from . import yfinance_service
        price_period, price_interval = yfinance_service.RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))[:2]
        if interval_override:
            price_interval = INTERVAL_MAP.get(interval_override.lower(), price_interval)
        price_hist = ticker_obj.history(period=price_period, interval=price_interval)
        if not price_hist.empty:
            # Drop NaN OHLC rows the same way yfinance_service.get_history does, so the
            # window matches the actual candles the chart renders.
            price_hist = price_hist.dropna(subset=["Open", "High", "Low", "Close"])
        if not price_hist.empty:
            # Right edge: never emit indicator points past the last candle.
            hist = hist[hist.index <= price_hist.index[-1]]
        if hist.empty:
            return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}

        df = hist.rename(columns=str.lower)
        h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
        if interval_override and not price_hist.empty:
            # Left edge: start at the first candle of the price window. Warmup bars
            # before it fed the math above but are not emitted.
            start_i = int((hist.index < price_hist.index[0]).sum())
        else:
            start_i = _trim_start(hist.index, keep)
        ts = [t.isoformat() for t in hist.index[start_i:]]
        result_range = range_.upper()

    def add(name, full_vals):
        vals = [None if pd.isna(x) else round(float(x), 4) for x in full_vals[start_i:]]
        out[name] = {"time": ts, "values": vals}

    for raw in studies:
        s = raw.strip().lower()
        try:
            if s.startswith("sma"):
                n = int(s[3:] or 20); add(f"sma{n}", _sma(c, n))
            elif s.startswith("ema"):
                n = int(s[3:] or 20); add(f"ema{n}", _ema(c, n))
            elif s == "bbands":
                lo, mid, up = _bbands(c); add("bb_lower", lo); add("bb_mid", mid); add("bb_upper", up)
            elif s == "vwap":
                # VWAP is a session indicator — only meaningful on intraday ranges.
                if range_.upper() in ("30M", "1H", "5H", "1D"):
                    add("vwap", _vwap(h, l, c, v))
            elif s == "rsi":
                add("rsi", _rsi(c))
            elif s == "macd":
                line, sig, hist_ = _macd(c); add("macd", line); add("macd_signal", sig); add("macd_hist", hist_)
            elif s == "stoch":
                k, d = _stoch(h, l, c); add("stoch_k", k); add("stoch_d", d)
            elif s == "squeeze":
                mom, on = _squeeze(h, l, c); add("squeeze_mom", mom); add("squeeze_on", on)
            elif s == "donchian":
                up, lo = _donchian(h, l); add("donchian_upper", up); add("donchian_lower", lo)
        except Exception:
            continue

    return {"ticker": ticker.upper(), "range": result_range, "indicators": out}


def compute_from_bars(bars: list[dict], studies: list[str]) -> dict:
    """Compute indicators over CALLER-SUPPLIED bars (e.g. a Lab Platform stored
    dataset, possibly already resampled to a different interval) instead of
    fetching live from yfinance. Same math as compute() (the exact SMA/EMA/RSI/
    etc functions), so live and dataset indicators can never drift apart.

    No warmup/trim split here -- the caller is expected to pass the FULL series
    it wants indicators computed over (so long-lookback averages like SMA200
    have real history) and do any display-window trimming itself afterward.
    """
    out: dict[str, dict] = {}
    if not bars:
        return {"indicators": out}

    df = pd.DataFrame(bars)
    ts = [pd.Timestamp(t).isoformat() for t in df["timestamp"]]
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]

    def add(name, vals):
        out[name] = {"time": ts, "values": [None if pd.isna(x) else round(float(x), 4) for x in vals]}

    for raw in studies:
        s = raw.strip().lower()
        try:
            if s.startswith("sma"):
                n = int(s[3:] or 20); add(f"sma{n}", _sma(c, n))
            elif s.startswith("ema"):
                n = int(s[3:] or 20); add(f"ema{n}", _ema(c, n))
            elif s == "bbands":
                lo, mid, up = _bbands(c); add("bb_lower", lo); add("bb_mid", mid); add("bb_upper", up)
            elif s == "vwap":
                add("vwap", _vwap(h, l, c, v))
            elif s == "rsi":
                add("rsi", _rsi(c))
            elif s == "macd":
                line, sig, hist_ = _macd(c); add("macd", line); add("macd_signal", sig); add("macd_hist", hist_)
            elif s == "stoch":
                k, d = _stoch(h, l, c); add("stoch_k", k); add("stoch_d", d)
            elif s == "squeeze":
                mom, on = _squeeze(h, l, c); add("squeeze_mom", mom); add("squeeze_on", on)
            elif s == "donchian":
                up, lo = _donchian(h, l); add("donchian_upper", up); add("donchian_lower", lo)
        except Exception:
            continue

    return {"indicators": out}


# Extra calendar days of warmup to fetch before a custom [start,end] window, by
# interval, so a strategy's rolling indicators/trade-tracker state are already
# primed by the time the display window begins (same reasoning as IND_CFG).
CUSTOM_WARMUP_DAYS: dict[str, int] = {"1m": 3, "1h": 40, "1d": 200, "1wk": 700, "1mo": 3650}


def fetch_strategy_bars(ticker: str, range_: str, interval_override: str | None = None,
                         start: str | None = None, end: str | None = None) -> tuple[list[dict], str | None]:
    """Fetch bars for a strategy run WITH a warmup buffer before the display
    window (reusing IND_CFG, the same warmup config built-in indicators use),
    so rolling indicators and a strategy's trade-tracker state (in_position,
    running highs/lows) are already primed by the time the display window
    starts -- instead of resetting to flat on every re-fetch/range switch.

    Returns (bars, display_start_iso): bars includes the warmup portion;
    display_start_iso marks where the display window begins (the sandbox trims
    everything it returns to this boundary). display_start_iso is None when
    there isn't enough data to establish one (caller should skip trimming).
    """
    from . import yfinance_service
    ticker_obj = yf.Ticker(ticker)

    if start and end:
        interval = INTERVAL_MAP.get((interval_override or "1d").lower(), "1d")
        pad_days = CUSTOM_WARMUP_DAYS.get(interval, 200)
        warm_start = (pd.Timestamp(start) - pd.Timedelta(days=pad_days)).strftime("%Y-%m-%d")
        hist = ticker_obj.history(start=warm_start, end=end, interval=interval)
        if hist.empty:
            return [], None
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
        if hist.empty:
            return [], None
        display_start = pd.Timestamp(start, tz=hist.index.tz)
        return yfinance_service.bars_from_hist(hist), display_start.isoformat()

    period, interval, keep = IND_CFG.get(range_.upper(), ("6mo", "1d", ("days", 31)))
    if interval_override:
        interval = INTERVAL_MAP.get(interval_override.lower(), interval)
        period = OVERRIDE_WARMUP.get(interval, period)
    hist = ticker_obj.history(period=period, interval=interval)
    if hist.empty:
        return [], None
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    if hist.empty:
        return [], None

    # Match the exact display window the price chart shows (same alignment
    # compute() uses), so display_start lines up with what's actually rendered.
    price_period, price_interval = yfinance_service.RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))[:2]
    if interval_override:
        price_interval = INTERVAL_MAP.get(interval_override.lower(), price_interval)
    price_hist = ticker_obj.history(period=price_period, interval=price_interval)
    if not price_hist.empty:
        price_hist = price_hist.dropna(subset=["Open", "High", "Low", "Close"])
        hist = hist[hist.index <= price_hist.index[-1]]
    if hist.empty:
        return [], None

    if interval_override and not price_hist.empty:
        start_i = int((hist.index < price_hist.index[0]).sum())
    else:
        start_i = _trim_start(hist.index, keep)

    display_start = hist.index[start_i].isoformat() if start_i < len(hist.index) else None
    return yfinance_service.bars_from_hist(hist), display_start
