# BUILD-STATE — trade-tracker
Updated 2026-07-18 · verified against live repo + Supabase (not memory)

## Versions
- tracker: **trade-tracker.html v1.9.1** (inbox shows candidates; pass/veto collapsed under 'gated by rules') (forward-rebuild on committed base; NOT the chat-side v1.7 lineage — that file was never committed and is unrecoverable byte-exact)
- repo HEAD: a6feb08 (main) · workflows: `update-prices.yml` ("Daily prices", cron 22:00 UTC Mon–Fri, ACTIVE), `backfill.yml` (dispatch, inputs start/end, failure→issue harness)
- scripts: update_prices.py (Yahoo-only, date-guarded, dynamic universe, self-check; Stooq removed), backfill_prices.py (Yahoo v8 history, TradeData∪static universe, ignore-duplicates), check_triggers.py (WARN_DAYS=5, statuses watch/triggered, dedupe by open issue title)

## Database (qdbasuabcmhsboficofh) — schema truth
- "TradeData" (24 rows, book restored 2026-07-18 from chat-history reconstruction): + `exit numeric` column added. Status vocab: watch/triggered/target/stopped/invalid/pass/**closed** (closed = discretionary exit, e.g. DAL earnings-veto)
- price_marks: unique(ticker,mark_date) EXISTS; 320 rows, 20 tickers, 2026-06-25→07-17, weekday cadence enforced (Sat rows purged)
- screener_log: aligned to tracker payload {run_at,ticker,setup_type,score,entry,stop,target,corr_semis_flag,pushed} + legacy cols; anon INSERT policy live (intentional, sole anon write path)
- screener_suggestions / live_quotes / settings: schema present, 0 rows (writers not yet recommitted — G6/G7)

## v1.8.0 tracker facts
- Hydrate: TradeData + latest price_marks + screener_suggestions(new) via anon key; DB wins definitions, local-only rows kept; offline → local seed + amber chip
- Persistence: store shim = window.storage (artifact) else localStorage (Pages). The pre-1.8 deployed file had DEAD persistence on Pages
- Screener tab: inbox + Adopt/Dismiss, dismissals persist locally, audit rows POST to screener_log (fire-and-forget)
- Validation gate passed: node --check + 15/15 jsdom acceptance

## Hard-won environment facts
- Stooq is DEAD from GitHub-runner IPs (history 404s all symbols; latest N/Ds equities) — issue #2. Yahoo v8 needs a UA header
- update_prices MARK_DATE = UTC-today → manual dispatch only near 22:00 UTC weekdays (else wrong-dated rows; 07-18 incident cleaned)
- Claude sandbox: api.github.com IP-rate-limited unauth; Actions log storage (results-receiver.…) unreachable — hence the failure→issue harness; codeload tarball works for reads
- Supabase MCP: DDL via apply_migration needs an approval tap in-app; execute_sql DML doesn't

## Measured ρ vs SMH (2026-07-17, 60 obs)
Hot (≥0.6): QQQ .94 · MU .84 · INTC .78 · **ETN .77** · EWY .77 · NVDA .62 — ETN's 'diversifier' label fails measurement (AI-electrification = chip beta). True diversifiers: KO −.44, XLE −.28, RTX −.21, WMT −.19, VRTX −.17, LLY −.07, JPM −.04.

## Review flags (book reconstruction)
NVDA (confirm not stopped at 198) · LLY (stop + opened_on approximate; entry 1183/tg 1255 per 6/30) · DAL (stop + realized_r pending; exit=7/9 close) · QQQ/EWY (still open?)

## Ops learnings (wk of 07-20)
- Alert titles are now UNDATED and unified across nightly+live: one open issue per (ticker, kind, level); closing the issue re-arms it. The dated design produced 52 dupes in 4 days.
- Screener exclusion = unexpired live CANDIDATES only; passes/vetoes never block (14 passes froze the universe Tue-Thu). Audit row on every run incl. universe-0.
- RTX veto case study: held out of earnings; stock +7.3% through the print to 209 - veto cost a winner this time, by design. Setup completed without entry; re-scan for new structure.

## Queue
1. ~~G3+G4~~ SHIPPED 2026-07-18: nightly = dynamic universe (STATIC ∪ TradeData actives) + Yahoo-only date-guarded fetch + weekend guard + holiday skip + post-upsert self-check (fail loud); check_triggers = >25% d/d corp-action gate ([data] issue, level alerts suppressed); both workflows publish failure logs as issues. 11/11 stubbed acceptance tests.
2. ~~G5~~ SHIPPED 2026-07-18: `v_corr_smh` view (60-session Pearson vs SMH, security_invoker, anon-readable; fields ticker/corr_60d/n_obs/calc_date/benchmark) + tracker v1.9.0 ρ chips, measured-corr analytics bars, adopt-warn ≥0.6.
3. ~~G6~~ SHIPPED 2026-07-18: live_watch.py + live-watch.yml (30-min, 13:00–21:30 UTC weekdays; five conditions entry-hit/near-entry/stop-breach/invalidated-through-stop/target-hit; dated [live] titles = one alert/condition/day; corp gate carries over; upserts live_quotes) + tracker live-over-daily overlay, live chip, 5-min visible auto-refresh, seed-ghost cleanup. 12/12 watcher + 8/8 jsdom tests.
4. ~~G7~~ SHIPPED 2026-07-18: scan_universe.py + scan.yml (22:30 UTC weekdays; PRESETS-minus-book universe cap 18; 20d-extreme/compression prefilter; Haiku claude-haiku-4-5 batches, JSON-only, temp 0; deterministic gates: R:R>=1.5 recompute, 7d earnings veto, measured-rho gates 0.60 flag / 0.75 block — python corr certified == SQL view at 0.8447 on MU; suggestions expire +7d; audit row per run; DRY_RUN input; missing ANTHROPIC_API_KEY exits 0 with instructions). BLOCKED until ANTHROPIC_API_KEY secret is added.
5. ~~Detector wiring~~ SHIPPED 2026-07-18: detectors.py = full A-K set wired 1:1 from handbook Ch.6/7/11 (pure-python indicator lib, regime meta-filter, veto doctrine incl. walk-the-band protection; C/F exempt from range veto as transition setups; "no level no trade" enforced by construction). scan_universe.py now detector-grounded: one Yahoo OHLCV fetch feeds prefilter+detectors+corr, detector read injected into the Haiku prompt, model candidates without a live detector need confluence>=4 or downgrade to pass. Suites: 13/13 detectors, 8/8 integration.

## Handbook corpus policy
The 8-file corpus (trading-handbook.md + 7 companions, ~198KB) is NEVER committed to this PUBLIC repo — it is the edge. Canonical copies: ATX's device + Claude Project knowledge (upload there for cross-session persistence). Detector logic in detectors.py encodes the recipes without reproducing the text.
old-was: deep backfill (start 2026-04-17) + SQL 60d Pearson-vs-SMH view (n_obs-gated) + tracker corr overlay
3. G6: live_watch.py recommit + 30-min cron   4. G7: scan_universe.py (needs ANTHROPIC_API_KEY secret + spend OK)   5. Handbook re-upload → wire A–K detector stubs
