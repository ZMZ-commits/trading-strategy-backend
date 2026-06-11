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
    "30M": ("1d", "1m", ("tail", 30)),
    "1H": ("1d", "1m", ("tail", 60)),
    "5H": ("1d", "1m", ("tail", 300)),
    "1D": ("5d", "1m", ("tail", 390)),
    "1W": ("1mo", "15m", ("tail", 130)),
    "1M": ("2y", "1d", ("days", 31)),
    "1Y": ("2y", "1d", ("days", 366)),
    "5Y": ("10y", "1wk", ("days", 1830)),
    "MAX": ("max", "1mo", ("all", 0)),
}


# ── indicator math (computed on the FULL warmup series) ─────────
def _sma(s, n): return s.rolling(n).mean()
def _ema(s, n): return s.ewm(span=n, adjust=False).mean()


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
    if mode == "days":
        cutoff = index[-1] - pd.Timedelta(days=amt)
        for i, t in enumerate(index):
            if t >= cutoff:
                return i
    return 0


INTERVAL_MAP: dict[str, str] = {
    "1s": "1m", "1m": "1m", "1h": "1h", "1d": "1d", "1w": "1wk", "1mo": "1mo",
}


def compute(ticker: str, range_: str, studies: list[str], interval_override: str | None = None) -> dict:
    period, interval, keep = IND_CFG.get(range_.upper(), ("6mo", "1d", ("days", 31)))
    if interval_override:
        interval = INTERVAL_MAP.get(interval_override.lower(), interval)
        keep = ("all", 0)  # return full window when custom interval
    ticker_obj = yf.Ticker(ticker)
    hist = ticker_obj.history(period=period, interval=interval)

    out: dict[str, dict] = {}
    if hist.empty:
        return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}

    # Clamp to the last bar the price chart returns so indicator lines don't
    # float past the rightmost candle into empty space.  The warmup fetch uses
    # a longer period than the price fetch, so it can include extra bars
    # (e.g. today's partial bar) that have no corresponding candle.
    if not interval_override:
        from . import yfinance_service
        price_period, price_interval = yfinance_service.RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))[:2]
        price_hist = ticker_obj.history(period=price_period, interval=price_interval)
        if not price_hist.empty:
            # Drop NaN OHLC rows the same way yfinance_service.get_history does,
            # so the clamp date matches the actual last candle visible on the chart.
            price_hist = price_hist.dropna(subset=["Open", "High", "Low", "Close"])
        if not price_hist.empty:
            hist = hist[hist.index <= price_hist.index[-1]]
    if hist.empty:
        return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}

    df = hist.rename(columns=str.lower)
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
    start = _trim_start(hist.index, keep)
    ts = [t.isoformat() for t in hist.index[start:]]

    def add(name, full_vals):
        vals = [None if pd.isna(x) else round(float(x), 4) for x in full_vals[start:]]
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
        except Exception:
            continue

    return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}
