#!/usr/bin/env python3
"""Integration acceptance for the detector-grounded screener (offline stubs)."""
import sys, types, os, json, random, datetime as dt

os.environ.update(SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_KEY="k",
                  ANTHROPIC_API_KEY="sk-ant-test", DRY_RUN="false")

class R:
    def __init__(s, p, code=200): s.p = p; s.c = code
    def raise_for_status(s):
        if s.c >= 400: raise Exception(f"HTTP {s.c}")
    def json(s): return s.p

ST = {"posts": [], "prompt": None}
TODAY = dt.date.today()

def bar(d, o, h, l, c, v=1e6): return {"d": d, "o": o, "h": h, "l": l, "c": c, "v": v}
def flat_bars(n=260, px=100, noise=0.12, seed=7):
    rnd = random.Random(seed); out = []
    for i in range(n):
        c = px + rnd.uniform(-noise, noise)
        out.append(bar(f"d{i}", c-0.05, c+noise, c-noise, c, 1e6))
    return out
def squeeze_break(seed=11):
    b = flat_bars(seed=seed); base = b[-1]["c"]
    for j in range(30, 1, -1):
        i = len(b)-j
        b[i] = bar(b[i]["d"], base, base+0.05, base-0.05, base+((-1)**j)*0.03, 8e5)
    brk = base*1.035
    b[-1] = bar("dz", base, brk+0.3, base-0.1, brk, 2.5e6)
    return b

FIX = {"VRT": squeeze_break(), "PG": flat_bars(seed=21), "MS": flat_bars(seed=33)}
SMH_MARKS = [{"mark_date": f"d{i}", "price": 600+0.4*i} for i in range(240)]

def get(url, **kw):
    p = kw.get("params", {})
    if "/rest/v1/TradeData" in url: return R([])
    if "/rest/v1/screener_suggestions" in url: return R([])
    if "/rest/v1/price_marks" in url: return R(SMH_MARKS)
    raise AssertionError("GET " + url)
def post(url, **kw):
    if "api.anthropic.com" in url:
        ST["prompt"] = kw["json"]["messages"][0]["content"]
        arr = [{"ticker": "VRT", "verdict": "candidate", "confluence": 4,
                "entry": 103.6, "stop": 100.0, "target": 110.8, "thesis": "squeeze go", "event_date": None},
               {"ticker": "PG", "verdict": "candidate", "setup_type": "G", "confluence": 3,
                "entry": 100.5, "stop": 97.0, "target": 108.0, "thesis": "meh", "event_date": None},
               {"ticker": "MS", "verdict": "candidate", "setup_type": "B", "confluence": 4,
                "entry": 100.4, "stop": 97.2, "target": 107.5, "thesis": "strong anyway", "event_date": None},
               {"ticker": "PG", "verdict": "pass", "setup_type": None, "confluence": 1,
                "entry": None, "stop": None, "target": None, "reason": "detector vetoed - respecting"}]
        return R({"content": [{"type": "text", "text": json.dumps(arr)}]})
    ST["posts"].append((url.split("/rest/v1/")[1].split("?")[0], kw["json"])); return R({}, 201)

fake = types.ModuleType("requests"); fake.get = get; fake.post = post
sys.modules["requests"] = fake
import scan_universe as su
su.detectors.fetch_ohlcv_yahoo = lambda tk, days=400: [dict(b) for b in FIX[tk]]
su.PRESETS = {"Test": "VRT PG MS"}  # note: model returns 2 PG tickets; both should survive gating; su.UNIVERSE_CAP = 10; su.BATCH = 6
su.time.sleep = lambda *_: None

su.main()
rows = next((p for n, p in ST["posts"] if n == "screener_suggestions"), [])
by = {r["ticker"]: r for r in rows}
out = []; T = lambda n, ok: out.append(("PASS " if ok else "FAIL ") + n)

T("prompt carries detector-F grounding for VRT", "detector F fired" in (ST["prompt"] or "") and "VRT" in ST["prompt"])
pg_line = next((l for l in (ST["prompt"] or "").splitlines() if l.startswith("PG ")), "")
T("prompt marks PG as no-live-detector", ("no deterministic detector fired" in pg_line) or ("VETOED" in pg_line))
T("VRT stays candidate + setup_type filled from detector", by.get("VRT", {}).get("verdict") == "candidate" and by["VRT"]["setup_type"] == "F")
T("PG conf3 no-detector downgraded to pass", any(r["ticker"]=="PG" and r["verdict"]=="pass" and "A-K detector" in (r["reason"] or "") for r in rows))
T("MS conf4 no-detector survives (exceptional-confluence path)", by.get("MS", {}).get("verdict") == "candidate")
T("rr recompute intact on VRT", by.get("VRT", {}).get("rr") == 2.0)
T("expiry stamped +7d", all(r["expires_on"] == (TODAY+dt.timedelta(days=7)).isoformat() for r in rows))
T("null-level pass ticket survives the gate", sum(1 for r in rows if r["ticker"]=="PG")==2 and any(r["ticker"]=="PG" and r["verdict"]=="pass" and r["entry"] is None for r in rows))
T("audit row logged", any(n == "screener_log" for n, _ in ST["posts"]))
print("\n".join(out)); sys.exit(1 if any(x.startswith("FAIL") for x in out) else 0)
