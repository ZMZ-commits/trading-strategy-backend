from __future__ import annotations
import yfinance as yf

# (yfinance period, yfinance interval, tail_bars)
# tail_bars: keep only the last N bars (for intraday windows shorter than a day).
RANGE_MAP: dict[str, tuple[str, str, int | None]] = {
    "30M": ("1d", "1m", 30),     # last 30 one-minute bars
    "1H": ("1d", "1m", 60),      # last hour
    "5H": ("1d", "1m", 300),     # last 5 hours
    "1D": ("1d", "1m", None),
    "1W": ("5d", "15m", None),
    "1M": ("1mo", "1d", None),
    "1Y": ("1y", "1d", None),
    "5Y": ("5y", "1wk", None),
    "MAX": ("max", "1mo", None),
}

INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^DJI", "^VIX"]
INDEX_NAMES = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "DOW", "^VIX": "VIX"}


def get_history(ticker: str, range_: str) -> dict:
    period, interval, tail = RANGE_MAP.get(range_.upper(), ("1mo", "1d", None))
    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    bars = [
        {
            "timestamp": ts.isoformat(),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        }
        for ts, row in hist.iterrows()
    ]
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
