#!/usr/bin/env python3
"""scan_universe.py - proactive screener: universe-minus-book prefilter,
Haiku confluence read, deterministic gates, screener_suggestions upserts.

Pipeline per run (weekday cron 22:30 UTC, after the nightly marks):
  1. universe = PRESETS - active TradeData tickers - live 'new' suggestions
  2. prefilter (cost filter, not signal): near 20d extremes or compressed range
  3. Haiku batch read -> JSON tickets (five-family confluence, A-K setups)
  4. deterministic gates: R:R recompute, 7-day earnings veto,
     measured-correlation downgrade vs SMH (rho >= 0.75 -> pass,
     0.60-0.75 -> corr_semis flag with the measured value)
  5. insert screener_suggestions (status new, 7-day expiry) + audit row

DRY_RUN=true prints instead of writing. Missing ANTHROPIC_API_KEY exits 0
with setup instructions so the cron stays green until the secret lands.
"""
import os, sys, json, math, datetime as dt, statistics, time, requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SECRET_KEY"]
SB = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
UNIVERSE_CAP = int(os.environ.get("UNIVERSE_CAP", "18"))
BATCH = 6
MODEL = "claude-haiku-4-5"
UA = {"User-Agent": "Mozilla/5.0 trade-tracker/1.0"}
MIN_RR, CORR_FLAG, CORR_BLOCK, VETO_DAYS = 1.5, 0.60, 0.75, 7

PRESETS = {
    'Power / Electrification': 'ETN VRT PWR CEG NEE',
    'Healthcare': 'LLY UNH VRTX ISRG MRK',
    'Defense': 'RTX LMT NOC GD',
    'Transports': 'DAL UNP ODFL FDX',
    'Staples': 'KO WMT PG COST',
    'Financials': 'JPM GS MS BLK',
}

def sb_get(path, **params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB, params=params, timeout=30)
    r.raise_for_status(); return r.json()

def sb_post(path, payload):
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{path}",
                      headers={**SB, "Content-Type": "application/json",
                               "Prefer": "return=minimal"},
                      json=payload, timeout=30)
    r.raise_for_status()

def sector_of(tk):
    for sec, names in PRESETS.items():
        if tk in names.split(): return sec
    return None

def build_universe():
    names = []
    for s in PRESETS.values():
        for t in s.split():
            if t not in names: names.append(t)
    active = {r["ticker"] for r in sb_get("TradeData", select="ticker,status")
              if r.get("status") in ("watch", "triggered")}
    live = {r["ticker"] for r in sb_get("screener_suggestions",
                                        select="ticker,status", status="eq.new")}
    return [t for t in names if t not in active and t not in live][:UNIVERSE_CAP]

def closes_from_marks(tk, n=90):
    rows = sb_get("price_marks", ticker=f"eq.{tk}", select="mark_date,price",
                  order="mark_date.asc")
    return [(r["mark_date"], float(r["price"])) for r in rows][-n:]

def closes_from_yahoo(tk, days=130):
    end = dt.date.today(); start = end - dt.timedelta(days=days)
    p1 = int(dt.datetime.fromisoformat(start.isoformat()+"T00:00:00+00:00").timestamp())
    p2 = int(dt.datetime.fromisoformat(end.isoformat()+"T00:00:00+00:00").timestamp())+86400
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}"
         f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(u, headers=UA, timeout=30); r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    cl = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    out = []
    for t, c in zip(ts, cl):
        if c is None: continue
        out.append((dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(),
                    float(c)))
    return out

def closes(tk):
    rows = closes_from_marks(tk)
    return rows if len(rows) >= 40 else closes_from_yahoo(tk)

def precondition(px):
    """Dumb on purpose (cost filter, not signal): keep names within 8% of the
    20d high or low, or with 20d range compressed to <=10% of price."""
    vals = [p for _, p in px][-20:]
    if len(vals) < 20: return False
    last, hi, lo = vals[-1], max(vals), min(vals)
    if last <= 0: return False
    return (hi - last) / last <= 0.08 or (last - lo) / last <= 0.08 or (hi - lo) / last <= 0.10

def log_rets(px):
    return {d: math.log(p / q) for (d, p), (_, q) in
            zip(px[1:], px[:-1]) if q > 0 and p > 0}

def corr_vs_smh(px, smh_rets):
    r = log_rets(px)
    common = sorted(set(r) & set(smh_rets))[-60:]
    if len(common) < 40: return None, len(common)
    a = [r[d] for d in common]; b = [smh_rets[d] for d in common]
    try: return round(statistics.correlation(a, b), 4), len(common)
    except statistics.StatisticsError: return None, len(common)

SCAN_SYSTEM = """You are the screener inside a systematic swing-trading stack. Score long swing setups only, using the five-family confluence framework (trend/MA structure, momentum, level, volume-flow, context), setup types A-K (A trend continuation, B trend turn, E mean reversion, F breakdown/squeeze, G trend stack, H level reversal, I Fib pullback), 0-5 confluence. Frame levels as what traders are watching, never predictions; R:R is arithmetic. Be selective - 'pass' is a first-class verdict.
Given tickers with recent closes, reply with ONLY a JSON array, no prose, no code fences. One object per ticker:
{"ticker","verdict":"candidate"|"pass","setup_type","confluence":0-5,"entry","stop","target","thesis":"<=140 chars","event_date":"YYYY-MM-DD or null if no known binary event","event_label","reason":"required when verdict=pass"}
Numbers for entry/stop/target must be plausible vs the given closes (entry>stop for longs). If you don't know an upcoming earnings date, use null - never guess one."""

def haiku_batch(items):
    lines = []
    for tk, px in items:
        tail = [round(p, 2) for _, p in px][-30:]
        lines.append(f"{tk} ({sector_of(tk)}): last30={tail}")
    r = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 1500, "temperature": 0,
              "system": SCAN_SYSTEM,
              "messages": [{"role": "user", "content": "\n".join(lines)}]},
        timeout=120)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)

def gate(t, corr, n_obs):
    """Deterministic gates over one model ticket. Mutates + returns t or None."""
    try:
        en, sp, tg = float(t["entry"]), float(t["stop"]), float(t["target"])
    except (KeyError, TypeError, ValueError):
        return None
    if t.get("verdict") not in ("candidate", "pass"): return None
    t["corr_measured"] = corr
    t["corr_semis"] = bool(corr is not None and corr >= CORR_FLAG)
    if t["verdict"] == "pass":
        t["rr"] = None; return t
    if not (en > sp and tg > en):
        t["verdict"], t["reason"] = "veto", "level arithmetic fails (need stop<entry<target)"
        t["rr"] = None; return t
    rr = round((tg - en) / (en - sp), 2)
    t["rr"] = rr
    if rr < MIN_RR:
        t["verdict"], t["reason"] = "veto", f"R:R {rr}:1 recomputed below {MIN_RR}:1"
        return t
    ev = t.get("event_date")
    if ev:
        try:
            days = (dt.date.fromisoformat(ev) - dt.date.today()).days
            if 0 <= days <= VETO_DAYS:
                t["verdict"], t["reason"] = "veto", f"binary event {ev} inside {VETO_DAYS}d veto window"
                return t
        except ValueError:
            t["event_date"] = None
    if corr is not None and corr >= CORR_BLOCK:
        t["verdict"] = "pass"
        t["reason"] = f"measured rho {corr:.2f} vs SMH ({n_obs} obs) - adds to concentrated cluster"
    return t

def main():
    if not ANTHROPIC_KEY:
        print("ANTHROPIC_API_KEY not set - skipping scan.")
        print("Add it: repo Settings -> Secrets and variables -> Actions -> "
              "New repository secret -> name ANTHROPIC_API_KEY.")
        return
    uni = build_universe()
    print(f"universe ({len(uni)}): {' '.join(uni)}")
    smh_rets = log_rets(closes_from_marks("SMH"))
    survivors = []
    for tk in uni:
        try:
            px = closes(tk)
            if precondition(px): survivors.append((tk, px))
            time.sleep(0.4)
        except Exception as e:
            print(f"  {tk}: data FAIL {e}")
    print(f"prefilter kept {len(survivors)}: {' '.join(t for t,_ in survivors)}")
    if not survivors:
        print("nothing to scan today."); return
    today = dt.date.today()
    out = []
    for i in range(0, len(survivors), BATCH):
        chunk = survivors[i:i+BATCH]
        try:
            tickets = haiku_batch(chunk)
        except Exception as e:
            print(f"  batch {i//BATCH}: model FAIL {e}"); continue
        cmap = {tk: corr_vs_smh(px, smh_rets) for tk, px in chunk}
        for t in tickets if isinstance(tickets, list) else []:
            tk = str(t.get("ticker", "")).upper()
            if tk not in cmap: continue
            corr, n = cmap[tk]
            g = gate({**t, "ticker": tk}, corr, n)
            if g: out.append(g)
    rows = [{"ticker": t["ticker"], "verdict": t["verdict"],
             "confluence": t.get("confluence"), "entry": t.get("entry"),
             "stop": t.get("stop"), "target": t.get("target"), "rr": t.get("rr"),
             "sector": sector_of(t["ticker"]), "cluster": None,
             "setup_type": t.get("setup_type"), "thesis": t.get("thesis"),
             "reason": t.get("reason"), "event_date": t.get("event_date"),
             "event_label": t.get("event_label"), "corr_semis": t["corr_semis"],
             "corr_measured": t.get("corr_measured"), "source": "auto",
             "status": "new", "expires_on": (today + dt.timedelta(days=7)).isoformat()}
            for t in out]
    summary = (f"universe {len(uni)}, prefiltered {len(survivors)}, tickets {len(rows)} "
               f"({sum(1 for r in rows if r['verdict']=='candidate')} candidate)")
    if DRY_RUN:
        print("DRY_RUN - would insert:"); print(json.dumps(rows, indent=1)); print(summary); return
    if rows: sb_post("screener_suggestions", rows)
    sb_post("screener_log", [{"source": "scan_universe", "verdict": None, "note": summary}])
    print(f"inserted {len(rows)} suggestion(s). {summary}")

if __name__ == "__main__":
    main()
