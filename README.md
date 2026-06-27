# trade-tracker

Systematic trade tracker with a Supabase backend and an automated daily price feed.

## What's here

| File | Purpose | Where it runs |
|------|---------|---------------|
| `tracker.html` | The tracker UI (rail viz, R math, position sizing) — **YOU ADD THIS** from your build zip | GitHub Pages |
| `tracker-diagnostics.html` | Backend health console: connectivity, RLS reads, price-mark freshness | Browser / Pages |
| `update_prices.py` | Fetches 18 daily marks (Stooq + CoinGecko) and upserts to `price_marks` | GitHub Actions |
| `.github/workflows/update-prices.yml` | Cron that runs the fetcher weekdays 22:00 UTC | GitHub Actions |
| `seed_price_marks_2026-06-26.sql` | One-time manual seed of `price_marks` | Supabase SQL Editor |

> **Add your `tracker.html`** to the repo root before deploying — it's the only file not included here. (Then delete the `ADD_YOUR_tracker.html_HERE.txt` placeholder.)

## Deploy checklist

1. **Pages** — Settings → Pages → Deploy from a branch → `main` / `/ (root)`.
   Tracker lands at `https://<you>.github.io/trade-tracker/tracker.html`.
2. **Secrets** — Settings → Secrets and variables → Actions → New repository secret:
   - `SUPABASE_URL` = `https://qdbasuabcmhsboficofh.supabase.co`
   - `SUPABASE_SERVICE_KEY` = your **service_role (secret)** key
3. **Seed (optional)** — paste `seed_price_marks_2026-06-26.sql` into Supabase → SQL Editor to populate now.
4. **Run the feed** — Actions → update-prices → Run workflow. After that it runs itself every weekday.

## Notes

- `SUPABASE_SERVICE_KEY` bypasses RLS — it belongs **only** in GitHub secrets, never in `tracker.html` or anything served on Pages.
- The tracker UI uses the **anon (publishable)** key and needs RLS `SELECT` policies on `TradeData` and `price_marks`.
- The artifact/preview sandbox blocks outbound calls to Supabase — that's why this is hosted on Pages, not run in a preview.
