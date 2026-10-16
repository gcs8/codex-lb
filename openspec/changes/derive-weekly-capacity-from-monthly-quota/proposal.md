## Why

Subscription quotas are published per month (Plus = 7,560 credits; Pro 100 = 5x, Pro 200 = 10x). codex-lb stored those monthly values as the 7-day ("secondary") capacity, so every weekly pool, pace projection and capacity-weighted routing weight was overstated by 30/7 (~4.3x). History calibration on a live deployment measured Pro 100 at ~9k credits/week, which matches 37,800 x 7/30 = 8,820 (gcs8/codex-lb#5, #7).

## What Changes

- Weekly capacity is derived: `Plus monthly quota x plan tier multiplier x 7/30`.
- Pro is Pro 200 at 10x Plus (previously 50,400, a value matching no published multiplier).
- The weekly credits pace response carries the pool's monthly-quota equivalent, and the dashboard shows weekly and monthly together.

## Impact

- Affected spec: `usage-refresh-policy` (plan capacity values).
- Affected code: `app/core/usage`, weekly pace, dashboard pace card. Routing weights scale uniformly per plan, so relative routing changes only where plans differ.
- Per-account tier override (`quota_tier_multiplier`, optional `quota_tier_multiplier_expires_at`) for tiers the plan claim can't distinguish: grandfathered Pro 200 (20x until 2026-10-29), Pro 500 (25x). One nullable-column migration, rolling-safe.
- Accounts page: plan tier control with presets 1/5/10/20/25x and an optional end date.
