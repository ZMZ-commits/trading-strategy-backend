"""Technical indicators computed server-side from OHLCV.

Hand-rolled with pandas/numpy (no external TA dependency) so the formulas are
explicit and the install never breaks. Fetches the same yfinance window as the
chart, computes the requested studies, returns each as a time-aligned series.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf

from .yfinance_service import RANGE_MAP


# ── indicator math ──────────────────────────────────────────────
def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()   # Wilder smoothing
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = _ema(close, fast) - _ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def _bbands(close: pd.Series, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid - k * sd, mid, mid + k * sd


def _vwap(high, low, close, volume) -> pd.Series:
    tp = (high + low + close) / 3
    return (tp * volume).cumsum() / volume.cumsum().replace(0, np.nan)


def _stoch(high, low, close, k=14, d=3):
    ll = low.rolling(k).min()
    hh = high.rolling(k).max()
    fast_k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    slow_k = fast_k.rolling(d).mean()
    return slow_k, slow_k.rolling(d).mean()


def _linreg_endpoint(series: pd.Series, n: int) -> pd.Series:
    x = np.arange(n)
    def fit(y):
        if np.isnan(y).any():
            return np.nan
        m, b = np.polyfit(x, y, 1)
        return m * (n - 1) + b
    return series.rolling(n).apply(fit, raw=True)


def _squeeze(high, low, close, n=20):
    # Bollinger Bands inside Keltner Channels => squeeze ON.
    basis = _sma(close, n)
    dev = 2.0 * close.rolling(n).std()
    ub, lb = basis + dev, basis - dev
    rng = _sma(high - low, n)
    ukc, lkc = basis + 1.5 * rng, basis - 1.5 * rng
    on = ((lb > lkc) & (ub < ukc)).astype(float)
    hh, ll = high.rolling(n).max(), low.rolling(n).min()
    mid = ((hh + ll) / 2 + _sma(close, n)) / 2
    mom = _linreg_endpoint(close - mid, n)
    return mom, on


# ── dispatch ────────────────────────────────────────────────────
def _series(timestamps: list[str], values) -> dict:
    return {"time": timestamps, "values": [None if pd.isna(v) else round(float(v), 4) for v in values]}


def compute(ticker: str, range_: str, studies: list[str]) -> dict:
    period, interval, tail = RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))
    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    if tail is not None:
        hist = hist.tail(tail)

    out: dict[str, dict] = {}
    if hist.empty:
        return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}

    df = hist.rename(columns=str.lower)
    ts = [t.isoformat() for t in hist.index]
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    def add(name, vals):
        out[name] = _series(ts, vals)

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
        except Exception:
            continue

    return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}
