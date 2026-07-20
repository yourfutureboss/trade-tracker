#!/usr/bin/env python3
"""Synthetic-fixture acceptance for detectors.py (runs offline)."""
import math, random, sys
import detectors as dx

def bar(d, o, h, l, c, v=1e6): return {"d": d, "o": o, "h": h, "l": l, "c": c, "v": v}
def flat(n=260, px=100, noise=0.15, v=1e6, seed=7):
    rnd = random.Random(seed); out = []
    for i in range(n):
        c = px + rnd.uniform(-noise, noise)
        out.append(bar(f"d{i}", c-0.05, c+noise, c-noise, c, v))
    return out
def trend(n=260, px=100, drift=0.35, seed=3):
    rnd = random.Random(seed); out = []; c = px
    for i in range(n):
        c += drift + rnd.uniform(-0.4, 0.4)
        out.append(bar(f"d{i}", c-0.2, c+0.5, c-0.6, c, 1e6))
    return out

R = []
def T(name, ok): R.append(("PASS " if ok else "FAIL ") + name)
codes = lambda hits: {h["code"] for h in hits if not h["veto"]}

# A/I: deterministic leg -> 55% pullback with engulfing turn
b = flat(n=200, px=100, noise=0.12, seed=3)
lo_p, hi_p = 100.0, 130.0
b.append(bar("legLo", 100.6, 100.9, 99.4, 100.2, 1e6))          # clean fractal low
for i in range(30):                                              # smooth leg up
    c = lo_p + (hi_p-lo_p)*(i+1)/30
    b.append(bar(f"leg{i}", c-0.4, c+0.6, c-0.8, c, 1.1e6))
b.append(bar("legHi", 129.4, 131.2, 128.9, 130.4, 1.2e6))        # fractal high
pull = hi_p - 0.55*(hi_p-lo_p)                                   # 113.5
steps = [128.2, 125.9, 123.4, 120.8, 118.3, 116.1, 114.6]
for j, px in enumerate(steps):
    b.append(bar(f"pb{j}", px+0.9, px+1.2, px-0.6, px, 9e5))
b.append(bar("turn", 113.9, 115.9, 113.1, 115.6, 1.5e6))         # engulfing up in the 50-61.8 zone
hits = dx.detect_all(b)
T("uptrend pullback fires A", "A" in codes(hits))
T("fib zone fires I", "I" in codes(hits))
T("all longs have stop<entry<target", all(h["stop"] < h["entry"] < h["target"] for h in hits if h["direction"] == "long"))

# E vetoed in a strong downtrend (walk-the-band trap)
d = trend(drift=-0.5, seed=5)
p_, c_ = d[-2], d[-1]
d[-1] = bar("dz", c_["c"]+0.2, c_["c"]+0.9, c_["c"]-2.5, c_["c"]+0.6, 1e6)  # bullish candle at lows
hitsd = dx.detect_all(d, long_only=False)
e = [h for h in hitsd if h["code"] == "E"]
T("E in downtrend is vetoed (regime meta-filter)", (not e) or all(h["veto"] for h in e))

# F: squeeze then breakout on volume
f = flat()
base = f[-1]["c"]
for j in range(30, 1, -1):   # tighten range
    i = len(f)-j
    f[i] = bar(f[i]["d"], base, base+0.05, base-0.05, base+((-1)**j)*0.03, 8e5)
brk = base*1.035
f[-1] = bar("dz", base, brk+0.3, base-0.1, brk, 2.5e6)
hf = dx.detect_all(f)
T("squeeze breakout fires F long", "F" in codes(hf))
fh = next((h for h in hf if h["code"] == "F"), None)
T("F rr computed and >0", bool(fh) and fh["rr"] > 0)

# F short mirror
fs = flat(seed=11)
base = fs[-1]["c"]
for j in range(30, 1, -1):
    i = len(fs)-j
    fs[i] = bar(fs[i]["d"], base, base+0.05, base-0.05, base+((-1)**j)*0.03, 8e5)
dnc = base*0.965
fs[-1] = bar("dz", base, base+0.1, dnc-0.3, dnc, 2.6e6)
T("squeeze breakdown fires F short (long_only=False)",
  any(h["code"] == "F" and h["direction"] == "short" for h in dx.detect_all(fs, long_only=False)))
T("long_only filters the short out",
  not any(h["direction"] == "short" for h in dx.detect_all(fs, long_only=True)))

# H(a): fires at established support in a RANGE regime (gentle approach)
h_ = flat(n=240, px=100, noise=0.12, seed=9)
sup = 97.6
for i in (-60, -38):
    h_[i] = bar(h_[i]["d"], sup+0.7, sup+0.9, sup-0.05, sup+0.6, 1e6)
seq = [99.9, 99.6, 99.8, 99.3, 99.5, 99.0, 99.15, 98.7, 98.85, 98.4, 98.5, 98.15, 98.25, 97.95, 98.05, 97.75]
for j, px in enumerate(seq):                                     # wiggly drift, ADX stays quiet
    h_.append(bar(f"dn{j}", px+0.22, px+0.4, px-0.3, px, 1e6))
h_.append(bar("rev", 97.55, 98.45, sup-0.08, 98.05, 1.4e6))          # engulfing off the level
hh = dx.detect_all(h_)
T("level reversal fires H in range regime", "H" in codes(hh))

# H(b): the same reversal into a 14-bar ADX>25 decline is VETOED (walk-the-band trap)
hv = flat(n=240, px=100, noise=0.12, seed=9)
sup = 96.0
for i in (-60, -38):
    hv[i] = bar(hv[i]["d"], sup+0.7, sup+0.9, sup-0.05, sup+0.6, 1e6)
px = 100.4
for j in range(14):
    px -= 0.32
    hv.append(bar(f"dn{j}", px+0.28, px+0.42, px-0.28, px, 1e6))
hv.append(bar("rev", px-0.45, px+0.85, sup-0.08, px+0.55, 1.4e6))
hvh = [x for x in dx.detect_all(hv) if x["code"] == "H"]
T("H into ADX>25 decline is vetoed (doctrine)", bool(hvh) and all(x["veto"] for x in hvh))

# no-signal control: pure noise flat tape should fire little/nothing high-conviction
nn = dx.detect_all(flat(seed=42))
T("flat noise: no confluence>=4 signals", all(h["confluence"] < 4 for h in nn if not h["veto"]))

# regime function sanity
T("regime up-trend detected", dx.regime(trend())["dir"] == "up")
T("regime range band on flat", dx.regime(flat())["band"] in ("range", "unclear"))
print("\n".join(R)); sys.exit(1 if any(x.startswith("FAIL") for x in R) else 0)
