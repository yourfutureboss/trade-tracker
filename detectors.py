#!/usr/bin/env python3
"""detectors.py - deterministic A-K setup detectors + five-family confluence.

Wired 1:1 from the trading handbook (Ch.6 four roles, Ch.7 recipes A-K,
Ch.11 regime meta-filter & veto). Pure python, daily OHLCV bars:
bars = [{"d","o","h","l","c","v"}, ...] oldest -> newest.

Every detector answers the four roles - Direction, Timing, Conviction,
Risk - and only emits when it can place a structural stop ("no level, no
trade"). Confluence 0-5 = four roles + regime-fit context point. Veto per
the regime meta-filter: a setup family fighting the read regime scores 0.
"""
import math, datetime as dt, requests

UA = {"User-Agent": "Mozilla/5.0 trade-tracker/1.0"}
TREND_FAMILY = set("ABCDGIJK"); MEANREV_FAMILY = set("EH"); BREAKOUT = set("F")

# ---------------------------------------------------------------- data
def fetch_ohlcv_yahoo(tk, days=400):
    end = dt.date.today(); start = end - dt.timedelta(days=days)
    p1 = int(dt.datetime.fromisoformat(start.isoformat()+"T00:00:00+00:00").timestamp())
    p2 = int(dt.datetime.fromisoformat(end.isoformat()+"T00:00:00+00:00").timestamp())+86400
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}"
         f"?period1={p1}&period2={p2}&interval=1d")
    r = requests.get(u, headers=UA, timeout=30); r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        c = (q.get("close") or [None]*len(ts))[i]
        if c is None: continue
        g = lambda k: (q.get(k) or [None]*len(ts))[i]
        bars.append({"d": dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(),
                     "o": float(g("open") or c), "h": float(g("high") or c),
                     "l": float(g("low") or c), "c": float(c),
                     "v": float(g("volume") or 0)})
    return bars

# ---------------------------------------------------------------- indicators
def sma(xs, n): return [None]*(n-1)+[sum(xs[i-n+1:i+1])/n for i in range(n-1, len(xs))]
def ema(xs, n):
    out, k, prev = [], 2/(n+1), None
    for i, x in enumerate(xs):
        if i < n-1: out.append(None); continue
        prev = sum(xs[:n])/n if prev is None else x*k + prev*(1-k)
        out.append(prev)
    return out
def _wilder(vals, n):
    out, prev = [], None
    for i, v in enumerate(vals):
        if i < n-1: out.append(None); continue
        prev = sum(vals[:n])/n if prev is None else (prev*(n-1)+v)/n
        out.append(prev)
    return out
def rsi(cs, n=14):
    ups = [0.0]+[max(cs[i]-cs[i-1], 0) for i in range(1, len(cs))]
    dns = [0.0]+[max(cs[i-1]-cs[i], 0) for i in range(1, len(cs))]
    au, ad = _wilder(ups, n), _wilder(dns, n)
    return [None if (u is None or d is None) else (100.0 if d == 0 else 100-100/(1+u/d))
            for u, d in zip(au, ad)]
def macd(cs, f=12, s=26, sig=9):
    ef, es = ema(cs, f), ema(cs, s)
    line = [None if (a is None or b is None) else a-b for a, b in zip(ef, es)]
    vals = [x for x in line if x is not None]
    sg_t = ema(vals, sig); sg = [None]*(len(line)-len(sg_t))+sg_t
    hist = [None if (l is None or g is None) else l-g for l, g in zip(line, sg)]
    return line, sg, hist
def atr(bars, n=14):
    trs = [bars[0]["h"]-bars[0]["l"]]+[max(b["h"]-b["l"], abs(b["h"]-p["c"]), abs(b["l"]-p["c"]))
                                       for p, b in zip(bars, bars[1:])]
    return _wilder(trs, n)
def adx(bars, n=14):
    pdm, ndm, trs = [0.0], [0.0], [bars[0]["h"]-bars[0]["l"]]
    for p, b in zip(bars, bars[1:]):
        up, dn = b["h"]-p["h"], p["l"]-b["l"]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(b["h"]-b["l"], abs(b["h"]-p["c"]), abs(b["l"]-p["c"])))
    atr_, ap, an = _wilder(trs, n), _wilder(pdm, n), _wilder(ndm, n)
    pdi = [None if (a is None or t in (None, 0)) else 100*a/t for a, t in zip(ap, atr_)]
    ndi = [None if (a is None or t in (None, 0)) else 100*a/t for a, t in zip(an, atr_)]
    dx = [None if (p is None or q is None or p+q == 0) else 100*abs(p-q)/(p+q)
          for p, q in zip(pdi, ndi)]
    return _wilder([x for x in dx if x is not None] and
                   [x if x is not None else 0 for x in dx], n), pdi, ndi
def bollinger(cs, n=20, k=2):
    mid = sma(cs, n); up, lo, bw = [], [], []
    for i, m in enumerate(mid):
        if m is None: up.append(None); lo.append(None); bw.append(None); continue
        sd = (sum((x-m)**2 for x in cs[i-n+1:i+1])/n) ** 0.5
        up.append(m+k*sd); lo.append(m-k*sd); bw.append((up[-1]-lo[-1])/m if m else None)
    return mid, up, lo, bw
def stoch(bars, n=14, d=3):
    ks = []
    for i in range(len(bars)):
        if i < n-1: ks.append(None); continue
        w = bars[i-n+1:i+1]; hi = max(b["h"] for b in w); lo = min(b["l"] for b in w)
        ks.append(50.0 if hi == lo else 100*(bars[i]["c"]-lo)/(hi-lo))
    kk = [k for k in ks if k is not None]
    ds = [None]*(len(ks)-max(len(kk)-d+1, 0))+[sum(kk[i-d+1:i+1])/d for i in range(d-1, len(kk))]
    return ks, ds[:len(ks)] if len(ds) >= len(ks) else ds+[None]*(len(ks)-len(ds))
def rel_vol(bars, n=20):
    vs = [b["v"] for b in bars]; base = sma(vs, n)
    return [None if (m in (None, 0)) else v/m for v, m in zip(vs, base)]
def swings(bars, k=2):
    his, los = [], []
    for i in range(k, len(bars)-k):
        if all(bars[i]["h"] >= bars[j]["h"] for j in range(i-k, i+k+1)): his.append(i)
        if all(bars[i]["l"] <= bars[j]["l"] for j in range(i-k, i+k+1)): los.append(i)
    return his, los
def anchored_vwap(bars, start):
    num = den = 0.0; out = [None]*len(bars)
    for i in range(start, len(bars)):
        tp = (bars[i]["h"]+bars[i]["l"]+bars[i]["c"])/3
        num += tp*max(bars[i]["v"], 1); den += max(bars[i]["v"], 1)
        out[i] = num/den
    return out
def bull_candle(p, b):
    body = abs(b["c"]-b["o"]); rng = b["h"]-b["l"] or 1e-9
    hammer = b["c"] > b["o"] and (min(b["o"], b["c"])-b["l"]) >= 2*body and body/rng < 0.4
    engulf = b["c"] > b["o"] and p["c"] < p["o"] and b["c"] >= p["o"] and b["o"] <= p["c"]
    return hammer or engulf
def bear_candle(p, b):
    body = abs(b["c"]-b["o"]); rng = b["h"]-b["l"] or 1e-9
    star = b["c"] < b["o"] and (b["h"]-max(b["o"], b["c"])) >= 2*body and body/rng < 0.4
    engulf = b["c"] < b["o"] and p["c"] > p["o"] and b["o"] >= p["c"] and b["c"] <= p["o"]
    return star or engulf

# ---------------------------------------------------------------- regime (Ch.11)
def regime(bars):
    cs = [b["c"] for b in bars]
    s200 = sma(cs, 200); a, _, _ = adx(bars)
    adx_now = next((x for x in reversed(a) if x is not None), None)
    band = "trend" if (adx_now or 0) > 25 else ("range" if (adx_now or 99) < 20 else "unclear")
    if s200[-1] is not None and s200[-10] is not None:
        dirn = "up" if cs[-1] > s200[-1] and s200[-1] > s200[-10] else \
               "down" if cs[-1] < s200[-1] and s200[-1] < s200[-10] else "flat"
    else:
        dirn = "flat"
    return {"adx": adx_now, "band": band, "dir": dirn}

def _fam(code): return "trend" if code in TREND_FAMILY | BREAKOUT else "meanrev"

def veto_for(code, direction, rg):
    """Ch.11: the regime decides which family works; fighting it = stand aside."""
    fam = _fam(code)
    if fam == "trend" and rg["band"] == "range" and code not in ("C", "F"):
        return "trend setup in a <20-ADX range regime"
    if fam == "meanrev" and rg["band"] == "trend" and \
       ((direction == "long" and rg["dir"] == "down") or (direction == "short" and rg["dir"] == "up")):
        return "fading a strong trend (ADX>25) - the walk-the-band trap"
    if direction == "long" and rg["dir"] == "down" and rg["band"] == "trend" and fam == "trend":
        return "long trend setup against a confirmed downtrend"
    return None

# ---------------------------------------------------------------- detectors
def _mk(code, name, direction, entry, stop, target, note, roles, rg):
    if entry is None or stop is None or target is None: return None
    if direction == "long" and not (stop < entry < target): return None
    if direction == "short" and not (target < entry < stop): return None
    v = veto_for(code, direction, rg)
    conf = min(5, len(roles) + (1 if (_fam(code) == ("trend" if rg["band"] == "trend" else
                                       "meanrev" if rg["band"] == "range" else "-")) else 0))
    return {"code": code, "name": name, "direction": direction,
            "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
            "confluence": 0 if v else conf, "veto": v, "note": note,
            "rr": round((target-entry)/(entry-stop), 2) if direction == "long"
                  else round((entry-target)/(stop-entry), 2)}

def detect_all(bars, long_only=True):
    if len(bars) < 210: return []
    cs = [b["c"] for b in bars]
    rg = regime(bars)
    s20, s50, s200 = sma(cs, 20), sma(cs, 50), sma(cs, 200)
    e3, e30, e50 = ema(cs, 3), ema(cs, 30), ema(cs, 50)
    r = rsi(cs); ml, ms, mh = macd(cs); at = atr(bars)
    a, pdi, ndi = adx(bars); mid, ub, lb, bw = bollinger(cs)
    ks, ds = stoch(bars); rv = rel_vol(bars)
    his, los = swings(bars)
    i = len(bars)-1; c, p = bars[i], bars[i-1]
    A = at[i] or (c["h"]-c["l"]) or c["c"]*0.02
    last_hi = max((bars[j]["h"] for j in his[-3:]), default=None) if his else None
    last_lo = min((bars[j]["l"] for j in los[-3:]), default=None) if los else None
    out = []
    def add(x):
        if x and (not long_only or x["direction"] == "long"): out.append(x)

    up200 = s200[i] and cs[i] > s200[i] and s200[i] > (s200[i-10] or s200[i])
    # A - trend filter + momentum pullback
    if up200 and r[i] and any((r[j] or 99) < 40 for j in range(i-5, i)) and r[i] > (r[i-1] or 0) and last_lo:
        add(_mk("A", "Trend continuation pullback", "long", cs[i], last_lo-0.3*A,
                (last_hi or cs[i]+3*A), "200-MA up, RSI turned up from <40",
                {"dir", "time", "risk"} | ({"vol"} if (rv[i] or 0) > 1 else set()), rg))
    # B - MACD + RSI
    if ml[i] and ms[i] and ml[i] > ms[i] and (ml[i-1] or 0) <= (ms[i-1] or 0) and r[i] and \
       (r[i] > 50 or ((r[i-3] or 99) < 30 and r[i] > r[i-3])) and last_lo:
        add(_mk("B", "MACD+RSI turn", "long", cs[i], last_lo-0.3*A, cs[i]+2*(cs[i]-(last_lo-0.3*A)),
                "MACD crossed up, RSI confirming", {"dir", "time", "risk"}, rg))
    # C - MACD + Stochastic
    if ml[i] and ms[i] and ml[i] > ms[i] and ks[i] and ds[i] and ks[i] > ds[i] and \
       (ks[i-1] or 99) <= (ds[i-1] or 0) and (ks[i-2] or 99) < 20 and last_lo:
        add(_mk("C", "MACD+Stoch confluence", "long", cs[i], last_lo-0.3*A,
                (last_hi or cs[i]+2.5*A), "Stoch cross out of <20 with MACD up",
                {"dir", "time", "risk"}, rg))
    # D - DMI/ADX trend gate
    if pdi[i] and ndi[i] and pdi[i] > ndi[i] and (a[i] or 0) > 25 and (a[i] or 0) >= (a[i-3] or 0) and \
       (mh[i] or 0) > 0 and last_lo:
        add(_mk("D", "ADX trend gate", "long", cs[i], last_lo-0.3*A,
                cs[i]+2.2*(cs[i]-(last_lo-0.3*A)), f"+DI>-DI, ADX {round(a[i],1)} rising, hist>0",
                {"dir", "time", "risk"}, rg))
    # E - Bollinger + RSI + candle mean reversion
    if lb[i-1] and c["l"] <= (lb[i] or lb[i-1]) * 1.002 and (r[i] or 99) < 32 and bull_candle(p, c):
        add(_mk("E", "Band reversion", "long", cs[i], min(c["l"], p["l"])-0.5*A, mid[i],
                "lower-band tag, RSI<32, bullish candle", {"time", "risk", "dir"}, rg))
    # F - squeeze breakout (both directions)
    sq = bw[i-1] and bw[i-1] <= min(x for x in bw[i-90:i] if x is not None)*1.05
    if sq and ub[i-1] and cs[i] > ub[i-1] and (rv[i] or 0) > 1.3 and (r[i] or 0) > 50:
        add(_mk("F", "Squeeze breakout", "long", cs[i], mid[i], cs[i]+2*(cs[i]-mid[i]),
                "squeeze -> close above band on volume", {"dir", "time", "vol", "risk"}, rg))
    if sq and lb[i-1] and cs[i] < lb[i-1] and (rv[i] or 0) > 1.3 and (r[i] or 99) < 50:
        add(_mk("F", "Squeeze breakdown", "short", cs[i], mid[i], cs[i]-2*(mid[i]-cs[i]),
                "squeeze -> close below band on volume", {"dir", "time", "vol", "risk"}, rg))
    # G - triple stack
    if e3[i] and e30[i] and e3[i] > e30[i] and (e3[i-1] or 0) <= (e30[i-1] or 0) and \
       e50[i] and cs[i] > e50[i] and (r[i] or 99) < 70 and (mh[i] or 0) > 0:
        add(_mk("G", "Triple-stack trend", "long", cs[i], e30[i]-0.5*A,
                cs[i]+2.5*(cs[i]-(e30[i]-0.5*A)), "3/30 EMA cross, >50-EMA, hist>0, RSI ok",
                {"dir", "time", "risk"}, rg))
    # H - level reversal at established support
    lvl = None
    if len(los) >= 2:
        cands = [bars[j]["l"] for j in los if j >= i-120]
        near = [x for x in cands if abs(cs[i]-x) <= 3*A]
        for x in near:
            if sum(1 for y in near if abs(y-x) <= 0.8*A) >= 2 and abs(cs[i]-x) <= 1.5*A:
                lvl = x; break
    osold = (r[i] or 99) < 35 or (ks[i-1] or 99) < 20
    if lvl and osold and bull_candle(p, c) and last_hi:
        add(_mk("H", "Level reversal", "long", cs[i], lvl-0.5*A, last_hi,
                f"2-touch support ~{round(lvl,2)}, RSI<35, bullish candle",
                {"time", "risk", "dir"} | ({"vol"} if (rv[i] or 0) > 1 else set()), rg))
    # I - Fib pullback in an up-leg
    if his and los:
        lo_j = los[-1] if los[-1] < (his[-1] if his else 0) else (los[-2] if len(los) > 1 else None)
        hi_j = his[-1] if his else None
        if lo_j is not None and hi_j is not None and hi_j > lo_j:
            lo_p, hi_p = bars[lo_j]["l"], bars[hi_j]["h"]
            if hi_p > lo_p:
                f50, f618, f786 = hi_p-0.5*(hi_p-lo_p), hi_p-0.618*(hi_p-lo_p), hi_p-0.786*(hi_p-lo_p)
                in_zone = min(f618, f50) <= cs[i] <= max(f618, f50)*1.01
                if up200 and in_zone and bull_candle(p, c) and (r[i] or 0) > (r[i-1] or 0):
                    add(_mk("I", "Fib pullback", "long", cs[i], f786-0.2*A, hi_p+0.272*(hi_p-lo_p),
                            "50-61.8% retrace, bullish candle, RSI turning",
                            {"dir", "time", "risk"}, rg))
    # J - anchored VWAP reclaim
    if los:
        av = anchored_vwap(bars, los[-1])
        if av[i] and av[i-1] and p["c"] < av[i-1] and cs[i] > av[i] and (r[i] or 0) > 50 and (rv[i] or 0) > 1.2 and last_hi:
            add(_mk("J", "Anchored-VWAP reclaim", "long", cs[i], av[i]-0.5*A, last_hi,
                    "reclaimed anchored VWAP on volume, RSI>50", {"dir", "time", "vol", "risk"}, rg))
    # K - MA cross + volume
    if s20[i] and s50[i] and s20[i] > s50[i] and (s20[i-3] or 0) <= (s50[i-3] or 0) and (rv[i] or 0) > 1.2 and last_lo:
        add(_mk("K", "MA cross on volume", "long", cs[i], min(s50[i], last_lo)-0.3*A,
                cs[i]+2*(cs[i]-min(s50[i], last_lo)), "20/50 cross confirmed by volume",
                {"dir", "vol", "risk"}, rg))
    live = [x for x in out if not x["veto"]]
    vetoed = [x for x in out if x["veto"]]
    live.sort(key=lambda x: (-x["confluence"], -x["rr"]))
    return live + vetoed
