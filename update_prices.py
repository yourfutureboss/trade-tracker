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
    "ETN": "etn.us", "RTX": "rtx.us",
}
# Crypto via CoinGecko (keyless). ticker -> CoinGecko id
COINGECKO = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}

# Single mark date for the run. At the 22:00 UTC weekday cron this equals the
# US trading date. (On a US market holiday Stooq returns the prior close but it
# would still be dated today - add a date guard if that matters to you.)
MARK_DATE = dt.datetime.now(dt.timezone.utc).date().isoformat()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def fetch_yahoo_today(ticker):
    """Close for MARK_DATE from Yahoo v8 chart (fallback: Stooq latest is
    returning N/D for every equity from GitHub-runner IPs - 2026-07-18).
    Only accepts a bar dated exactly MARK_DATE, so off-session runs write
    nothing rather than a stale close."""
    import datetime as _dt
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/" + ticker
         + "?range=5d&interval=1d")
    r = requests.get(u, headers={"User-Agent": "Mozilla/5.0 trade-tracker/1.0"},
                     timeout=20)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    for t, c in zip(reversed(ts), reversed(closes)):
        if c is None:
            continue
        d = _dt.datetime.fromtimestamp(t, _dt.timezone.utc).date().isoformat()
        if d == MARK_DATE:
            return float(c)
        if d < MARK_DATE:
            break
    return None


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


def equity_universe():
    """STATIC list (STOOQ keys) ∪ live TradeData watch/triggered tickers, so a
    new watch (GS, VRTX, IBIT, ...) is marked from the night it's added -
    no more silent coverage gaps."""
    tks = set(STOOQ)
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/TradeData?select=ticker,status",
                         headers={"apikey": SERVICE_KEY,
                                  "Authorization": f"Bearer {SERVICE_KEY}"},
                         timeout=30)
        r.raise_for_status()
        tks |= {row["ticker"].upper() for row in r.json()
                if row.get("status") in ("watch", "triggered")}
    except Exception as e:
        print(f"  TradeData read failed ({e}) - static universe only")
    return sorted(tks - set(COINGECKO))


def collect_rows():
    rows = []
    for ticker in equity_universe():
        try:
            # Yahoo only: Stooq history 404s and its quote endpoint N/Ds every
            # equity from runner IPs (issue #2), and it has no date guard.
            price = fetch_yahoo_today(ticker)
            if price is None:
                print(f"  {ticker:5} no bar for {MARK_DATE} (skipped)")
            else:
                rows.append({"ticker": ticker, "mark_date": MARK_DATE, "price": price})
                print(f"  {ticker:5} {price}")
        except Exception as e:
            print(f"  {ticker:5} FAILED: {e}")
        time.sleep(0.4)  # pace Yahoo politely
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


def self_check(rows):
    """Loud-failure gate: after the upsert, verify every ticker we fetched a
    bar for actually has a row for MARK_DATE in Supabase. A run must never be
    green while writing nothing (2026-07-18 lesson)."""
    expected = {r["ticker"] for r in rows}
    got = requests.get(
        f"{SUPABASE_URL}/rest/v1/price_marks",
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"},
        params={"select": "ticker", "mark_date": f"eq.{MARK_DATE}"}, timeout=30)
    got.raise_for_status()
    present = {row["ticker"] for row in got.json()}
    missing = sorted(expected - present)
    if missing:
        print(f"SELF-CHECK FAILED - upsert verified missing: {', '.join(missing)}")
        raise SystemExit(1)
    print(f"Self-check OK - {len(expected)} ticker(s) verified for {MARK_DATE}.")


def main():
    if dt.datetime.now(dt.timezone.utc).weekday() >= 5:
        print(f"{MARK_DATE} is a weekend (UTC) - weekday cadence rule, no marks written.")
        return
    print(f"Fetching marks for {MARK_DATE} ...")
    rows = collect_rows()
    equities = [r for r in rows if r["ticker"] not in COINGECKO]
    if not equities:
        # Every equity lacked a MARK_DATE bar -> almost certainly a US market
        # holiday. Not a failure; skip the day entirely to keep session cadence.
        print(f"No equity bars dated {MARK_DATE} - treating as market holiday, nothing written.")
        return
    upsert(rows)
    self_check(rows)


if __name__ == "__main__":
    main()
