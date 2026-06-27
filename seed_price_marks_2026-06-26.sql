-- ============================================================
-- price_marks seed — mark_date 2026-06-26 (Friday)
-- 18-ticker watchlist. Run in Supabase → SQL Editor.
-- The SQL Editor runs as the service role, so this writes
-- regardless of RLS state (no anon policy needed for this).
--
-- Assumes schema: price_marks (ticker text, mark_date date, price numeric)
-- with a UNIQUE constraint on (ticker, mark_date) — required for ON CONFLICT.
-- If your price column has a different name, edit it in both the
-- column list and the DO UPDATE line below.
--
-- Equities/ETFs are Friday's close or latest intraday print (provisional);
-- crypto is live spot (24/7). Let the GitHub Action's Stooq/CoinGecko pull
-- overwrite these with authoritative closes — merge-duplicates handles it.
-- ============================================================

insert into price_marks (ticker, mark_date, price) values
  ('MU',   '2026-06-26', 1132.33),   -- semis  | post-earnings, -6.7% on the day
  ('INTC', '2026-06-26',  128.32),   -- semis  | close
  ('NVDA', '2026-06-26',  192.53),   -- semis  | close
  ('ORCL', '2026-06-26',  148.53),   -- semis  | intraday
  ('SMH',  '2026-06-26',  618.00),   -- semis ETF | intraday
  ('QQQ',  '2026-06-26',  713.65),   -- broad ETF | close
  ('GLD',  '2026-06-26',  371.37),   -- gold ETF  | intraday
  ('EWY',  '2026-06-26',  197.28),   -- Korea ETF | close
  ('URA',  '2026-06-26',   43.53),   -- uranium ETF | intraday
  ('XLE',  '2026-06-26',   53.98),   -- energy ETF  | intraday
  ('LLY',  '2026-06-26', 1197.00),   -- healthcare | +6.1% on the day (derived)
  ('DAL',  '2026-06-26',   92.37),   -- transports | intraday
  ('KO',   '2026-06-26',   81.63),   -- staples | intraday
  ('WMT',  '2026-06-26',  115.33),   -- staples | intraday
  ('JPM',  '2026-06-26',  332.54),   -- financials | intraday
  ('BTC',  '2026-06-26', 59936.01),  -- crypto | live spot (Crypto.com)
  ('ETH',  '2026-06-26',  1574.80),  -- crypto | live spot (Crypto.com)
  ('SOL',  '2026-06-26',    71.65)   -- crypto | live spot (Crypto.com)
on conflict (ticker, mark_date) do update
  set price = excluded.price;

-- Verify:
-- select ticker, mark_date, price from price_marks
-- where mark_date = '2026-06-26' order by ticker;
