#!/usr/bin/env python3
"""
check_triggers.py - runs after update_prices.py in the nightly Action.
Compares latest close in price_marks to entry/stop/target on active
"TradeData" rows; opens one GitHub issue per condition. Dedupe = open
issue with identical title. Close the issue to re-arm that alert.
"""
import os, datetime as dt, requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY   = os.environ["SUPABASE_SERVICE_KEY"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_REPO  = os.environ["GITHUB_REPOSITORY"]   # owner/repo, auto-set

ACTIVE     = ("watch", "triggered")
WARN_DAYS  = 5   # flag binary events this many days out
STALE_DAYS = 4   # latest mark older than this -> pipeline alert

SB = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
GH = {"Authorization": f"Bearer {GH_TOKEN}",
      "Accept": "application/vnd.github+json"}

def sb(path, **params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}",
                     headers=SB, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def latest_mark(ticker):
    rows = sb("price_marks", ticker=f"eq.{ticker}",
              select="mark_date,price", order="mark_date.desc", limit=1)
    return rows[0] if rows else None

def open_titles():
    r = requests.get(f"https://api.github.com/repos/{GH_REPO}/issues",
                     headers=GH, params={"state": "open", "per_page": 100},
                     timeout=30)
    r.raise_for_status()
    return {i["title"] for i in r.json() if "pull_request" not in i}

def issue(title, body):
    r = requests.post(f"https://api.github.com/repos/{GH_REPO}/issues",
                      headers=GH, timeout=30,
                      json={"title": title, "body": body,
                            "labels": ["trade-alert"]})
    r.raise_for_status()

def main():
    today = dt.date.today()
    setups = sb("TradeData", status=f"in.({','.join(ACTIVE)})", select="*")
    if not setups:
        print("No active setups."); return

    hits = []
    for s in setups:
        t  = s["ticker"]
        st = s["status"]
        lo = 1 if (s.get("direction") or "long").lower() == "long" else -1

        m = latest_mark(t)
        if not m:
            hits.append((f"[alert] {t}: no price data",
                         f"Active {st} row but no price_marks rows."))
            continue
        px   = float(m["price"])
        mark = dt.date.fromisoformat(m["mark_date"])
        if (today - mark).days > STALE_DAYS:
            hits.append((f"[alert] {t}: stale price feed",
                         f"Latest mark {px} is from {mark} - pipeline may be down."))
            continue

        entry, stop, target = s.get("entry"), s.get("stop"), s.get("target")
        if st == "watch" and entry is not None and lo * (px - float(entry)) > 0:
            hits.append((f"[alert] {t} closed through entry {float(entry):g}",
                         f"{t} closed {px} on {mark}, through entry {float(entry):g} "
                         f"(setup {s.get('setup_type')}, {s.get('confluence')}/5). "
                         f"Close-confirmed. Flip status to triggered if taken."))
        if stop is not None and lo * (float(stop) - px) > 0:
            hits.append((f"[alert] {t} closed through stop {float(stop):g}",
                         f"{t} closed {px} on {mark}, through stop {float(stop):g} "
                         f"(status {st}). Close-confirmed - "
                         f"{'invalidation' if st == 'watch' else 'exit'} signal."))
        if st == "triggered" and target is not None and lo * (px - float(target)) > 0:
            hits.append((f"[alert] {t} closed through target {float(target):g}",
                         f"{t} closed {px} on {mark}, beyond target {float(target):g}."))
        ev = s.get("event_date")
        if ev:
            days = (dt.date.fromisoformat(ev) - today).days
            if 0 <= days <= WARN_DAYS:
                hits.append((f"[alert] {t} binary event {ev}",
                             f"{t} event in {days} day(s). Earnings-veto rule: "
                             f"trim/exit before, don't hold through."))

    existing, new = open_titles(), 0
    for title, body in hits:
        if title in existing:
            continue
        issue(title, body); new += 1
        print("opened:", title)
    print(f"{len(hits)} condition(s) met, {new} new issue(s).")

if __name__ == "__main__":
    main()
