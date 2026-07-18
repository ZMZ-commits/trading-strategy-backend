from __future__ import annotations
import math
import yfinance as yf

# (yfinance period, yfinance interval, tail_bars)
# tail_bars: keep only the last N bars (for intraday windows shorter than a day).
RANGE_MAP: dict[str, tuple[str, str, int | None]] = {
    "30M": ("1d", "1m", 30),     # last 30 one-minute bars
    "1H": ("1d", "1m", 60),      # last hour
    "5H": ("1d", "1m", 300),     # last 5 hours
    "1D": ("1d", "1m", None),
    "5D": ("5d", "15m", None),
    "1M": ("1mo", "1d", None),
    "3M": ("3mo", "1d", None),
    "6M": ("6mo", "1d", None),
    "YTD": ("ytd", "1d", None),    # yfinance supports period="ytd" (since Jan 1)
    "1Y": ("1y", "1d", None),
    "5Y": ("5y", "1wk", None),
    "MAX": ("max", "1mo", None),
}

# Map UI interval labels → yfinance interval strings.
INTERVAL_MAP: dict[str, str] = {
    "1s": "1m",   # yfinance minimum is 1m; 1s falls back to 1m
    "1m": "1m",
    "1h": "1h",
    "1d": "1d",
    "1w": "1wk",
    "1mo": "1mo",
}

INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^DJI", "^VIX"]
INDEX_NAMES = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "DOW", "^VIX": "VIX"}


def bars_from_hist(hist) -> list[dict]:
    """Convert a yfinance history DataFrame into our bar-dict shape, dropping
    rows with NaN OHLC (adjustment/dividend rows with no price data)."""
    bars = []
    for ts, row in hist.iterrows():
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        if any(math.isnan(v) for v in (o, h, l, c)):
            continue
        vol = row["Volume"]
        bars.append({
            "timestamp": ts.isoformat(),
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": int(vol) if not math.isnan(float(vol)) else 0,
        })
    return bars


def get_history(
    ticker: str,
    range_: str,
    interval_override: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    if start and end:
        # Custom window: explicit from/to dates at the requested interval.
        interval = INTERVAL_MAP.get((interval_override or "1d").lower(), "1d")
        tail = None
        hist = yf.Ticker(ticker).history(start=start, end=end, interval=interval)
    else:
        period, interval, tail = RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))
        if interval_override:
            interval = INTERVAL_MAP.get(interval_override.lower(), interval)
            tail = None  # don't trim when a custom interval is requested
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
    bars = bars_from_hist(hist)
    if tail is not None:
        bars = bars[-tail:]
    return {"ticker": ticker.upper(), "range": range_.upper(), "bars": bars}


def get_snapshot(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.fast_info
    name, market_cap, w52h, w52l = ticker.upper(), None, None, None
    try:
        full = t.info
        name = full.get("longName") or full.get("shortName") or ticker.upper()
        market_cap = full.get("marketCap")
        w52h = full.get("fiftyTwoWeekHigh")
        w52l = full.get("fiftyTwoWeekLow")
    except Exception:
        pass
    return {
        "ticker": ticker.upper(), "name": name,
        "price": round(float(info.last_price or 0), 4),
        "open": round(float(info.open or 0), 4),
        "high": round(float(info.day_high or 0), 4),
        "low": round(float(info.day_low or 0), 4),
        "close": round(float(info.last_price or 0), 4),
        "volume": int(info.three_month_average_volume or 0),
        "marketCap": market_cap, "week52High": w52h, "week52Low": w52l,
    }


def get_indices() -> list[dict]:
    result = []
    for symbol in INDEX_SYMBOLS:
        try:
            t = yf.Ticker(symbol)
            price = float(t.fast_info.last_price or 0)
            hist = t.history(period="2d", interval="1d")
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                change = round(price - prev, 2)
                pct = round((change / prev) * 100, 2) if prev else 0.0
            else:
                change, pct = 0.0, 0.0
            result.append({"symbol": symbol, "name": INDEX_NAMES[symbol],
                           "price": round(price, 2), "change": change, "changePct": pct})
        except Exception:
            result.append({"symbol": symbol, "name": INDEX_NAMES.get(symbol, symbol),
                           "price": 0.0, "change": 0.0, "changePct": 0.0})
    return result
