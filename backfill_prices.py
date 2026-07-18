#!/usr/bin/env python3
"""backfill_prices.py - fill price_marks gaps with daily closes.

Source: Yahoo v8 chart API (keyless, UA header required). Stooq's history
endpoint (/q/d/l/) now 404s from GitHub-runner IPs for every symbol - see
issue #2 - and its latest-quote endpoint returns N/D there too.

Range via env START/END (YYYY-MM-DD). Existing (ticker, mark_date) rows are
left untouched: Prefer resolution=ignore-duplicates. Server-side only.
"""
import os, sys, time, datetime as dt, requests

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
SB = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
START = os.environ.get("START", "2026-06-25")
END = os.environ.get("END", dt.date.today().isoformat())
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) trade-tracker/1.0"}

YSYM = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
CRYPTO = set(YSYM)
STATIC = {"MU","INTC","NVDA","ORCL","SMH","QQQ","GLD","EWY","URA","XLE",
          "LLY","DAL","KO","WMT","JPM","ETN","RTX","BTC","ETH","SOL"}

def universe():
    tks = set(STATIC)
    try:
        r = requests.get(f"{URL}/rest/v1/TradeData?select=ticker,status",
                         headers=SB, timeout=30)
        r.raise_for_status()
        tks |= {row["ticker"].upper() for row in r.json()
                if row.get("status") in ("open", "watch", "triggered")}
    except Exception as e:
        print(f"TradeData read failed ({e}) - static universe only", file=sys.stderr)
    return sorted(tks)

def yahoo(tk):
    sym = YSYM.get(tk, tk)
    p1 = int(dt.datetime.fromisoformat(START + "T00:00:00+00:00").timestamp())
    p2 = int(dt.datetime.fromisoformat(END + "T00:00:00+00:00").timestamp()) + 86400
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
         f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(u, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
        di = d.isoformat()
        if di < START or di > END:
            continue
        if tk in CRYPTO and d.weekday() >= 5:
            continue  # keep the weekday cron shape
        out.append({"ticker": tk, "mark_date": di,
                    "price": round(float(c), 4), "source": "yahoo"})
    return out

def main():
    payload = []
    for tk in universe():
        try:
            rows = yahoo(tk); print(f"{tk}: {len(rows)}"); payload += rows
        except Exception as e:
            print(f"{tk}: FAIL {e}", file=sys.stderr)
        time.sleep(0.6)
    if not payload: sys.exit("nothing fetched")
    r = requests.post(f"{URL}/rest/v1/price_marks?on_conflict=ticker,mark_date",
                      headers={**SB, "Content-Type": "application/json",
                               "Prefer": "resolution=ignore-duplicates"},
                      json=payload, timeout=60)
    r.raise_for_status()
    print(f"done - sent {len(payload)} rows, existing dates untouched")

if __name__ == "__main__":
    main()
