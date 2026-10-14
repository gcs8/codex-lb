# Preserve half-open probe cleanup ownership

## Why

An obsolete probe can complete cleanup after its lease has been replaced. Its terminal accounting must not release or clear the replacement's retry state. Reloading elapsed or absent durable cooldowns must not manufacture repeated admissions.

## What changes

- Fence local probes by session identity, request identity, and a monotonic lease generation.
- Capture probe claims before asynchronous terminal accounting and fence successful settlement by the captured episode and generation.
- Return undispatched submit and retry probes through cancellation-deferred cleanup.
- Preserve active local leases and pending returns during durable load/persist reconciliation.

## Scope

This is a focused port of PR #1962 source 3603d07e0878beaad0c9e3b68583fc109c08c471 onto the assigned fork base. It does not import stale ancestors, unrelated spec deletions, reconnect owner-loss retirement, retained account-lease changes, or local-reset policy. Existing retirement and anchor-provenance requirements remain in force. Refs #2272, partial coverage only.

## Capabilities

### New capabilities

None.

### Modified capabilities

- `responses-api-compat`: local half-open probe ownership and cooldown reconciliation.

## Impact

HTTP bridge retry admission and terminal bookkeeping. No migration, setting, deployment, or frontend change.
