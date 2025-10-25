import os
import time
import math
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

from exchanges import EXCHANGE_FUNCS

DB_PATH = os.environ.get("DB_PATH", "btc_futures_volumes.sqlite")

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def ensure_db(conn: sqlite3.Connection):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS volumes(
        ts INTEGER NOT NULL,
        exchange TEXT NOT NULL,
        base_volume_btc REAL NOT NULL,
        quote_volume_usd REAL NOT NULL
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vol_ts_ex ON volumes(ts, exchange);")
    conn.commit()

def save_row(conn: sqlite3.Connection, ts: int, row: Dict):
    conn.execute(
        "INSERT INTO volumes (ts, exchange, base_volume_btc, quote_volume_usd) VALUES (?, ?, ?, ?)",
        (ts, row["exchange"], row["base_volume_btc"], row["quote_volume_usd"]),
    )
    conn.commit()

def window_change_pct(conn: sqlite3.Connection, exchange: str, minutes: int) -> Optional[float]:
    # Compare last point to average over previous window
    cur = conn.cursor()
    cur.execute("SELECT ts, quote_volume_usd FROM volumes WHERE exchange=? ORDER BY ts DESC LIMIT 1", (exchange,))
    last = cur.fetchone()
    if not last:
        return None
    last_ts, last_q = last
    cutoff = last_ts - minutes*60
    # average of records in [cutoff, last_ts)
    cur.execute(
        "SELECT AVG(quote_volume_usd) FROM volumes WHERE exchange=? AND ts>=? AND ts<?",
        (exchange, cutoff, last_ts)
    )
    avg_prev = cur.fetchone()[0]
    if not avg_prev or avg_prev <= 0:
        return None
    return (last_q - avg_prev) / avg_prev * 100.0

def telegram_notify(token: str, chat_id: str, text: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=12)
    except Exception:
        pass

def fmt_usd(x: float) -> str:
    if x >= 1e12: return f"${x/1e12:.2f}T"
    if x >= 1e9:  return f"${x/1e9:.2f}B"
    if x >= 1e6:  return f"${x/1e6:.2f}M"
    if x >= 1e3:  return f"${x/1e3:.2f}K"
    return f"${x:.2f}"

def monitor_loop():
    load_dotenv()
    poll = int(os.environ.get("POLL_INTERVAL_SEC", "60"))
    alert_pct = float(os.environ.get("ALERT_CHANGE_PCT", "20"))
    window_min = int(os.environ.get("WINDOW_MINUTES", "15"))
    log_to_stdout = os.environ.get("LOG_TO_STDOUT", "true").lower() == "true"
    exchanges = [e.strip() for e in os.environ.get("EXCHANGES", "binance,bybit,okx,deribit").split(",") if e.strip()]
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    conn = sqlite3.connect(DB_PATH)
    ensure_db(conn)

    print(f"Starting BTC futures volume monitor. Poll every {poll}s. Window {window_min}m. Alert if change ≥ {alert_pct}%.")
    print(f"Exchanges: {', '.join(exchanges)}")
    if tg_token and tg_chat:
        print("Telegram alerts enabled.")
    else:
        print("Telegram alerts disabled (set TELEGRAM_* to enable).")

    while True:
        ts = int(now_utc().timestamp())
        totals_usd = 0.0
        rows: List[Dict] = []
        for ex in exchanges:
            fn = EXCHANGE_FUNCS.get(ex)
            if not fn: 
                continue
            try:
                data = fn()
            except Exception as e:
                data = None
            if not data:
                if log_to_stdout:
                    print(f"[{datetime.utcnow().isoformat()}] {ex}: failed to fetch")
                continue
            rows.append(data)
            totals_usd += data["quote_volume_usd"]
            save_row(conn, ts, data)

        if log_to_stdout:
            parts = [f"{r['exchange']}: {fmt_usd(r['quote_volume_usd'])}" for r in rows]
            print(f"[{datetime.utcnow().isoformat()}] 24h futures volume: " + " | ".join(parts) + f" || Total: {fmt_usd(totals_usd)}")

        # Alerts per exchange
        for r in rows:
            pct = window_change_pct(conn, r["exchange"], window_min)
            if pct is None:
                continue
            if abs(pct) >= alert_pct:
                direction = "↑" if pct > 0 else "↓"
                msg = (
                    f"BTC futures volume {direction} {pct:.1f}% over last {window_min}m on {r['exchange'].upper()}.\n"
                    f"Current 24h: {fmt_usd(r['quote_volume_usd'])} | Price ≈ ${r['last_price_usd']:.0f}\n"
                    f"UTC: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                if tg_token and tg_chat:
                    telegram_notify(tg_token, tg_chat, msg)
                if log_to_stdout:
                    print("[ALERT] " + msg)

        time.sleep(max(5, poll))

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("Stopped.")