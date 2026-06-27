#!/usr/bin/env python3
"""
update_prices.py - fetch daily marks for the watchlist and upsert to Supabase.

Designed to run in GitHub Actions (cron: Mon-Fri 22:00 UTC). The runner has
open internet, so it can reach Stooq + CoinGecko AND Supabase directly - which
is why this pushes automatically even though an interactive sandbox cannot.

Required env (set as GitHub Actions repository secrets):
  SUPABASE_URL          e.g. https://qdbasuabcmhsboficofh.supabase.co
  SUPABASE_SERVICE_KEY  the service_role (secret) key. It bypasses RLS, so it
                        can write regardless of policies. NEVER commit it or put
                        it in any client-side / Pages code - secret only.
"""

import os
import io
import csv
import time
import datetime as dt
import requests

# --- watchlist -------------------------------------------------------------
# Equities/ETFs via Stooq (keyless). ticker -> Stooq symbol (US tickers = ".us")
STOOQ = {
    "MU": "mu.us", "INTC": "intc.us", "NVDA": "nvda.us", "ORCL": "orcl.us",
    "SMH": "smh.us", "QQQ": "qqq.us", "GLD": "gld.us", "EWY": "ewy.us",
    "URA": "ura.us", "XLE": "xle.us", "LLY": "lly.us", "DAL": "dal.us",
    "KO": "ko.us", "WMT": "wmt.us", "JPM": "jpm.us",
}
# Crypto via CoinGecko (keyless). ticker -> CoinGecko id
COINGECKO = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}

# Single mark date for the run. At the 22:00 UTC weekday cron this equals the
# US trading date. (On a US market holiday Stooq returns the prior close but it
# would still be dated today - add a date guard if that matters to you.)
MARK_DATE = dt.datetime.now(dt.timezone.utc).date().isoformat()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def fetch_stooq(symbol):
    """Latest close from Stooq, or None if unavailable."""
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    row = next(csv.DictReader(io.StringIO(r.text)))
    close = (row.get("Close") or "").strip()
    if close in ("", "N/D"):  # Stooq uses N/D for missing data
        return None
    return float(close)


def fetch_crypto():
    """{ticker: usd_price} from CoinGecko (one request for all ids)."""
    ids = ",".join(COINGECKO.values())
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    out = {}
    for ticker, cg_id in COINGECKO.items():
        price = data.get(cg_id, {}).get("usd")
        if price is not None:
            out[ticker] = float(price)
    return out


def collect_rows():
    rows = []
    for ticker, symbol in STOOQ.items():
        try:
            price = fetch_stooq(symbol)
            if price is None:
                print(f"  {ticker:5} no data (skipped)")
            else:
                rows.append({"ticker": ticker, "mark_date": MARK_DATE, "price": price})
                print(f"  {ticker:5} {price}")
        except Exception as e:
            print(f"  {ticker:5} FAILED: {e}")
        time.sleep(0.3)  # be gentle with Stooq
    try:
        for ticker, price in fetch_crypto().items():
            rows.append({"ticker": ticker, "mark_date": MARK_DATE, "price": price})
            print(f"  {ticker:5} {price}")
    except Exception as e:
        print(f"  crypto FAILED: {e}")
    return rows


def upsert(rows):
    if not rows:
        print("Nothing to upsert - aborting.")
        raise SystemExit(1)
    url = f"{SUPABASE_URL}/rest/v1/price_marks?on_conflict=ticker,mark_date"
    r = requests.post(
        url,
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        json=rows,
        timeout=30,
    )
    r.raise_for_status()
    print(f"Upserted {len(rows)} rows for {MARK_DATE}.")


if __name__ == "__main__":
    print(f"Fetching marks for {MARK_DATE} ...")
    upsert(collect_rows())
