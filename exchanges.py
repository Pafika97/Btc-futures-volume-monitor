import time
import requests
from typing import Dict, Optional, Tuple

UserAgent = {"User-Agent": "btc-futures-volume-monitor/1.0 (+https://example.local)"}

def _safe_get(url: str, params: dict | None = None, timeout: int = 12) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, headers=UserAgent, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def binance() -> Optional[Dict]:
    """
    Binance USDT-margined and coin-margined perpetuals.
    Returns dict with base_volume_btc and quote_volume_usd and last_price_usd.
    """
    # USDT perpetual
    data_u = _safe_get("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"})
    # Coin-margined perpetual
    data_c = _safe_get("https://dapi.binance.com/dapi/v1/ticker/24hr", {"symbol": "BTCUSD_PERP"})
    if not data_u and not data_c:
        return None
    quote_usdt = float(data_u.get("quoteVolume", 0)) if data_u else 0.0
    last_price = float(data_u.get("lastPrice", data_u.get("prevClosePrice", 0))) if data_u else None
    # coin-margined volume is in contracts; "baseVolume" often in BTC
    base_btc_coin = float(data_c.get("baseVolume", 0)) if data_c and data_c.get("baseVolume") is not None else 0.0
    # For USDT-margined 24h base volume is in BTC in "volume"
    base_btc_usdt = float(data_u.get("volume", 0)) if data_u and data_u.get("volume") is not None else 0.0
    base_btc_total = base_btc_usdt + base_btc_coin
    if last_price is None or last_price == 0:
        # fall back to derived price
        last_price = quote_usdt / base_btc_usdt if base_btc_usdt > 0 else 0
    quote_total = quote_usdt + base_btc_coin * last_price
    return {
        "exchange": "binance",
        "base_volume_btc": base_btc_total,
        "quote_volume_usd": quote_total,
        "last_price_usd": last_price,
        "raw": {"u": data_u, "c": data_c},
    }

def bybit() -> Optional[Dict]:
    # linear (USDT) perpetual
    u = _safe_get("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})
    # inverse (coin) perpetual
    c = _safe_get("https://api.bybit.com/v5/market/tickers", {"category": "inverse", "symbol": "BTCUSD"})
    if not u and not c:
        return None
    last_price = None
    quote_usd = 0.0
    base_btc = 0.0
    if u and u.get("result") and u["result"].get("list"):
        row = u["result"]["list"][0]
        last_price = float(row.get("lastPrice", 0)) or last_price
        quote_usd += float(row.get("turnover24h", 0.0))
        # base volume (BTC) ~ quote/price if price > 0
        if last_price:
            base_btc += float(row.get("turnover24h", 0.0)) / last_price
    if c and c.get("result") and c["result"].get("list"):
        rowc = c["result"]["list"][0]
        last_price = float(rowc.get("lastPrice", 0)) or last_price
        # Bybit inverse returns "turnover24h" in USD
        quote_usd += float(rowc.get("turnover24h", 0.0))
        if last_price:
            base_btc += float(rowc.get("turnover24h", 0.0)) / last_price
    return {
        "exchange": "bybit",
        "base_volume_btc": base_btc,
        "quote_volume_usd": quote_usd,
        "last_price_usd": last_price or 0.0,
        "raw": {"linear": u, "inverse": c},
    }

def okx() -> Optional[Dict]:
    # USDT swap
    u = _safe_get("https://www.okx.com/api/v5/market/ticker", {"instId": "BTC-USDT-SWAP"})
    # coin swap
    c = _safe_get("https://www.okx.com/api/v5/market/ticker", {"instId": "BTC-USD-SWAP"})
    if not u and not c:
        return None
    last_price = None
    quote_usd = 0.0
    base_btc = 0.0
    if u and u.get("data"):
        row = u["data"][0]
        last_price = float(row.get("last", 0)) or last_price
        # volCcy24h is in quote currency (USDT ~ USD)
        quote_usd += float(row.get("volCcy24h", 0.0))
        if last_price:
            base_btc += quote_usd / last_price
    if c and c.get("data"):
        rowc = c["data"][0]
        last_price = float(rowc.get("last", 0)) or last_price
        # vol24h is number of contracts (1 BTC per contract for USD-SWAP)
        contracts = float(rowc.get("vol24h", 0.0))
        base_btc += contracts  # assume 1 BTC contract size for rough estimate
        quote_usd += contracts * (last_price or 0.0)
    return {
        "exchange": "okx",
        "base_volume_btc": base_btc,
        "quote_volume_usd": quote_usd,
        "last_price_usd": last_price or 0.0,
        "raw": {"usdt": u, "usd": c},
    }

def deribit() -> Optional[Dict]:
    j = _safe_get("https://www.deribit.com/api/v2/public/ticker", {"instrument_name": "BTC-PERPETUAL"})
    if not j or "result" not in j:
        return None
    res = j["result"]
    last_price = float(res.get("last_price") or res.get("index_price") or 0.0)
    stats = res.get("stats") or {}
    # Deribit volume reported in BTC
    base_btc = float(stats.get("volume", 0.0)) if isinstance(stats, dict) else 0.0
    quote_usd = base_btc * last_price
    return {
        "exchange": "deribit",
        "base_volume_btc": base_btc,
        "quote_volume_usd": quote_usd,
        "last_price_usd": last_price,
        "raw": j,
    }

# Mapping
EXCHANGE_FUNCS = {
    "binance": binance,
    "bybit": bybit,
    "okx": okx,
    "deribit": deribit,
}