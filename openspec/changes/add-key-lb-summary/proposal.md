## Why
Proxy-key consumers need read-only explanations without dashboard authority (gcs8/codex-lb#1).

## What Changes
Add an explicitly opted-in GET summary with closed aggregates and scoped quota cohorts. No migration, new environment switch, UI, redemption flag, transport instrumentation, or upstream changes.

## Capabilities
### New Capabilities
- `key-lb-summary`: private bounded read-only summary.
### Modified Capabilities
- `account-pool-usage-v1-usage`: allow lb_summary while retaining existing defaults.

## Impact
New API module, existing usage-section validation, router registration, synthetic tests and docs.
