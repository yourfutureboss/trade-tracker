#!/usr/bin/env python3
"""backfill_prices.py - fill price_marks gaps from Stooq daily history.

Range via env START/END (YYYY-MM-DD). Existing (ticker, mark_date) rows are
left untouched: Prefer resolution=ignore-duplicates. Run server-side only
(GitHub Actions) - service key required.
"""
import os, io, csv, sys, datetime as dt, requests

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
SB = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
START = os.environ.get("START", "2026-06-25")
END = os.environ.get("END", dt.date.today().isoformat())

CRYPTO = {"BTC": "btcusd", "ETH": "ethusd", "SOL": "solusd"}
# Mirrors the update_prices.py STOOQ keys (incl. ETN/RTX) + crypto trio, so a
# thin post-restore TradeData can never produce an empty backfill.
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

def stooq(tk):
    sym = CRYPTO.get(tk, f"{tk.lower()}.us")
    u = (f"https://stooq.com/q/d/l/?s={sym}"
         f"&d1={START.replace('-','')}&d2={END.replace('-','')}&i=d")
    r = requests.get(u, timeout=30); r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        c = row.get("Close")
        if not c or c == "N/D": continue
        d = dt.date.fromisoformat(row["Date"])
        if tk in CRYPTO and d.weekday() >= 5: continue  # match weekday cron shape
        out.append({"ticker": tk, "mark_date": row["Date"],
                    "price": float(c), "source": "stooq"})
    return out

def main():
    payload = []
    for tk in universe():
        try:
            rows = stooq(tk); print(f"{tk}: {len(rows)}"); payload += rows
        except Exception as e:
            print(f"{tk}: FAIL {e}", file=sys.stderr)
    if not payload: sys.exit("nothing fetched")
    r = requests.post(f"{URL}/rest/v1/price_marks?on_conflict=ticker,mark_date",
                      headers={**SB, "Content-Type": "application/json",
                               "Prefer": "resolution=ignore-duplicates"},
                      json=payload, timeout=60)
    r.raise_for_status()
    print(f"done - sent {len(payload)} rows, existing dates untouched")

if __name__ == "__main__":
    main()
