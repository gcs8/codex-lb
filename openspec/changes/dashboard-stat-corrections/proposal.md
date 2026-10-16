## Why

A read-only audit of every dashboard, reports, accounts and APIs figure against raw prod tables (gcs8/codex-lb#9) found stats that were technically computed but misleading: conversations are always 0 for Codex/Hermes traffic (it carries `session_id`), the 5 h donut shows weekly-only accounts as exhausted, cost is labelled as if it were what the subscription pays, and failed requests record `auto` as the served tier.

## What Changes

- Dashboard overview metrics and the reports summary also report distinct sessions; the tiles show conversations + sessions.
- The 5 h donut is hidden when no account in scope reports a 5 h window.
- Cost is labelled "API-equivalent cost" (dashboard tile, reports total).
- `auto` is never stored as `actual_service_tier`.
- The account burn projection tile becomes a pool burn projection: projected demand in credits over pool capacity (no clamp to the account count), naming the first account projected to run out before its reset, marked low-confidence early in the window.

## Impact

- Affected specs: `reports`.
- No migration. Allowance-credit accounting (separate from API cost) is a follow-up because it needs new rollup columns.
