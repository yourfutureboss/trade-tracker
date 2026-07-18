# BUILD-STATE — trade-tracker
Updated 2026-07-18 · verified against live repo + Supabase (not memory)

## Versions
- tracker: **trade-tracker.html v1.8.0** (forward-rebuild on committed base; NOT the chat-side v1.7 lineage — that file was never committed and is unrecoverable byte-exact)
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

## Review flags (book reconstruction)
NVDA (confirm not stopped at 198) · LLY (stop + opened_on approximate; entry 1183/tg 1255 per 6/30) · DAL (stop + realized_r pending; exit=7/9 close) · QQQ/EWY (still open?)

## Queue
1. ~~G3+G4~~ SHIPPED 2026-07-18: nightly = dynamic universe (STATIC ∪ TradeData actives) + Yahoo-only date-guarded fetch + weekend guard + holiday skip + post-upsert self-check (fail loud); check_triggers = >25% d/d corp-action gate ([data] issue, level alerts suppressed); both workflows publish failure logs as issues. 11/11 stubbed acceptance tests.
2. G5: deep backfill (start 2026-04-17) + SQL 60d Pearson-vs-SMH view (n_obs-gated) + tracker corr overlay
3. G6: live_watch.py recommit + 30-min cron   4. G7: scan_universe.py (needs ANTHROPIC_API_KEY secret + spend OK)   5. Handbook re-upload → wire A–K detector stubs
