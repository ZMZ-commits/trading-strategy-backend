"""Technical indicators computed server-side from OHLCV via pandas-ta.

Fetches the same yfinance window as the chart, runs the requested studies, and
returns each as a time-aligned series the frontend can overlay. Indicators are
computed, not fetched — so any of pandas-ta's 130+ studies can be added here
without touching a data provider.
"""
from __future__ import annotations
import pandas as pd
import pandas_ta as ta
import yfinance as yf

from .yfinance_service import RANGE_MAP


def _series(timestamps: list[str], values) -> dict:
    vals = [None if pd.isna(v) else round(float(v), 4) for v in values]
    return {"time": timestamps, "values": vals}


def compute(ticker: str, range_: str, studies: list[str]) -> dict:
    period, interval, tail = RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))
    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    if tail is not None:
        hist = hist.tail(tail)

    out: dict[str, dict] = {}
    if hist.empty:
        return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}

    df = hist.rename(columns=str.lower)  # open, high, low, close, volume
    ts = [t.isoformat() for t in hist.index]

    def add(name, values):
        if values is not None:
            out[name] = _series(ts, values)

    for raw in studies:
        s = raw.strip().lower()
        try:
            if s.startswith("sma"):
                n = int(s[3:] or 20)
                add(f"sma{n}", ta.sma(df["close"], length=n))
            elif s.startswith("ema"):
                n = int(s[3:] or 20)
                add(f"ema{n}", ta.ema(df["close"], length=n))
            elif s == "bbands":
                bb = ta.bbands(close=df["close"], length=20, std=2)
                if bb is not None:
                    add("bb_lower", bb.iloc[:, 0])
                    add("bb_mid", bb.iloc[:, 1])
                    add("bb_upper", bb.iloc[:, 2])
            elif s == "vwap":
                add("vwap", ta.vwap(high=df["high"], low=df["low"], close=df["close"], volume=df["volume"]))
            elif s == "rsi":
                add("rsi", ta.rsi(df["close"], length=14))
            elif s == "macd":
                macd = ta.macd(close=df["close"])
                if macd is not None:
                    add("macd", macd.iloc[:, 0])
                    add("macd_hist", macd.iloc[:, 1])
                    add("macd_signal", macd.iloc[:, 2])
            elif s == "stoch":
                st = ta.stoch(high=df["high"], low=df["low"], close=df["close"])
                if st is not None:
                    add("stoch_k", st.iloc[:, 0])
                    add("stoch_d", st.iloc[:, 1])
            elif s == "squeeze":
                sq = ta.squeeze(high=df["high"], low=df["low"], close=df["close"])
                if sq is not None:
                    add("squeeze_mom", sq.iloc[:, 0])   # momentum histogram
                    add("squeeze_on", sq.iloc[:, 1])    # 1 when in squeeze
        except Exception:
            # one bad study shouldn't kill the whole response
            continue

    return {"ticker": ticker.upper(), "range": range_.upper(), "indicators": out}
