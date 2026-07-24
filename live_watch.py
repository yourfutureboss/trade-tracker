#!/usr/bin/env python3
"""live_watch.py - intraday watcher for active setups (30-min cadence).

Quotes every TradeData watch/triggered ticker - Yahoo v8 for equities/ETFs,
CoinGecko for crypto - upserts live_quotes, and files dated [live] issues on
five conditions:
  entry-hit                watch trades through entry (plan is live)
  near-entry               within 1% of entry, heads-up (superseded by a hit)
  stop-breach              triggered position trades through stop
  invalidated-through-stop watch hits stop before entry: stand down
  target-hit               triggered position trades through target
Date in the title = one alert per condition per day; close an issue to
silence it. Corporate-action guard: quote >25% off the last daily mark files
a [data] review and mutes level alerts for that name. Off-hours polls
self-cancel. live_quotes never touches price_marks.
"""
import os, datetime as dt, requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY   = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_REPO  = os.environ["GITHUB_REPOSITORY"]

SB = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
GH = {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}
UA = {"User-Agent": "Mozilla/5.0 trade-tracker/1.0"}
CRYPTO = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
NEAR_PCT, MOVE_GATE = 0.01, 0.25

def now_utc():
    return dt.datetime.now(dt.timezone.utc)

def market_window(t):
    """US regular-trading-hours envelope covering both DST regimes."""
    if t.weekday() >= 5: return False
    mins = t.hour * 60 + t.minute
    return 13 * 60 <= mins <= 21 * 60 + 35

def sb_get(path, **params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB, params=params, timeout=30)
    r.raise_for_status(); return r.json()

def quote_equity(tk):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?range=1d&interval=5m"
    r = requests.get(u, headers=UA, timeout=20); r.raise_for_status()
    meta = r.json()["chart"]["result"][0].get("meta") or {}
    p = meta.get("regularMarketPrice")
    return float(p) if p is not None else None

def quote_crypto(tks):
    ids = ",".join(CRYPTO[t] for t in tks)
    r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                     params={"ids": ids, "vs_currencies": "usd"}, timeout=20)
    r.raise_for_status(); j = r.json()
    return {t: float(j[CRYPTO[t]]["usd"]) for t in tks if CRYPTO[t] in j and "usd" in j[CRYPTO[t]]}

def last_daily(tk):
    rows = sb_get("price_marks", ticker=f"eq.{tk}", select="price",
                  order="mark_date.desc", limit="1")
    return float(rows[0]["price"]) if rows else None

def open_titles():
    r = requests.get(f"https://api.github.com/repos/{GH_REPO}/issues", headers=GH,
                     params={"state": "open", "per_page": 100}, timeout=30)
    r.raise_for_status()
    return {i["title"] for i in r.json() if "pull_request" not in i}

def issue(title, body):
    r = requests.post(f"https://api.github.com/repos/{GH_REPO}/issues", headers=GH,
                      timeout=30, json={"title": title, "body": body, "labels": ["live-alert"]})
    r.raise_for_status()

def conditions(s, px, day):
    """Return [(title, body)] for one setup at price px."""
    t, st = s["ticker"], s["status"]
    lo = 1 if (s.get("direction") or "long").lower() == "long" else -1
    en = float(s["entry"]) if s.get("entry") is not None else None
    sp = float(s["stop"]) if s.get("stop") is not None else None
    tg = float(s["target"]) if s.get("target") is not None else None
    out = []
    def T(kind, lvl): return f"[alert] {t} {kind} {lvl:g}"   # undated: one open issue per condition; close to re-arm
    if st == "watch":
        if sp is not None and lo * (sp - px) > 0:
            out.append((T("invalidated-through-stop", sp),
                        f"{day} live: {t} trading {px:g}, through stop {sp:g} before entry - setup broken, stand down."))
        elif en is not None and lo * (px - en) > 0:
            out.append((T("entry-hit", en),
                        f"{day} live: {t} trading {px:g}, through entry {en:g} "
                        f"(setup {s.get('setup_type')}, {s.get('confluence')}/5). The plan is live."))
        elif en is not None and abs(px - en) / en <= NEAR_PCT:
            out.append((T("near-entry", en),
                        f"{day} live: {t} at {px:g}, within 1% of entry {en:g}. Heads-up only."))
    elif st == "triggered":
        if sp is not None and lo * (sp - px) > 0:
            out.append((T("stop-breach", sp),
                        f"{day} live: {t} trading {px:g}, through stop {sp:g}. Exit signal."))
        if tg is not None and lo * (px - tg) > 0:
            out.append((T("target-hit", tg), f"{day} live: {t} trading {px:g}, beyond target {tg:g}."))
    return out

def main():
    t = now_utc()
    if not market_window(t):
        print(f"{t:%F %H:%M}Z outside market window - nothing to do."); return
    day = t.date().isoformat()
    setups = sb_get('TradeData', status="in.(watch,triggered)", select="*")
    if not setups:
        print("No active setups."); return
    eq = [s["ticker"] for s in setups if s["ticker"] not in CRYPTO]
    cr = [s["ticker"] for s in setups if s["ticker"] in CRYPTO]
    quotes = {}
    for tk in eq:
        try:
            p = quote_equity(tk)
            if p: quotes[tk] = p
            else: print(f"  {tk:5} no quote")
        except Exception as e:
            print(f"  {tk:5} FAILED: {e}")
    if cr:
        try: quotes.update(quote_crypto(cr))
        except Exception as e: print(f"  crypto FAILED: {e}")
    hits, rows = [], []
    for s in setups:
        tk = s["ticker"]
        if tk not in quotes: continue
        px = quotes[tk]
        rows.append({"ticker": tk, "quote_date": day,
                     "quoted_at": t.isoformat(), "price": px})
        base = last_daily(tk)
        if base and abs(px / base - 1) > MOVE_GATE:
            hits.append((f"[data] {tk} live quote off last mark",
                         f"{day}: {tk} daily {base:g} vs live {px:g} ({abs(px/base-1)*100:.0f}%). Verify split/halt/bad print. "
                         f"Level alerts muted for this name this run."))
            continue
        hits += conditions(s, px, day)
    if rows:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/live_quotes?on_conflict=ticker",
                          headers={**SB, "Content-Type": "application/json",
                                   "Prefer": "resolution=merge-duplicates"},
                          json=rows, timeout=30)
        r.raise_for_status()
        print(f"live_quotes: {len(rows)} upserted")
    existing, new = open_titles(), 0
    for title, body in hits:
        if title in existing: continue
        issue(title, body); new += 1; print("opened:", title)
    print(f"{len(hits)} condition(s), {new} new issue(s).")

if __name__ == "__main__":
    main()
