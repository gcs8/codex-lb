# Expire elapsed primary and monthly aggregate samples

## Why

A silent account's latest historical reset can win the aggregate minimum long after it elapsed. PR #2625 proposes expiring all three projections. Its own full body explicitly leaves weekly expiration open because pooled weekly credits deliberately retain raw exhausted samples during refresh.

## What changes

- Apply the existing elapsed-row projection helper after weekly-only normalization for primary and monthly aggregate rows only.
- Keep historical SQLite rows, secondary aggregate rows, account pool percentages, quota admission, scopes and routes unchanged.
- Prove fixed-time behavior through real ASGI and disposable SQLite, including native usage consumers.

## Impact

Owning capability: api-keys. Production changes are confined to `_build_aggregate_credit_limits` and its clock import. No polling, mutations, settings, migrations or provider data are added. Secondary expiration remains an explicit owner decision, not completed scope.
