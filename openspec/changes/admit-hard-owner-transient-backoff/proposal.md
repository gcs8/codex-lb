# Admit a hard continuity owner's transient error backoff

## Why

PR #2486 narrows selection to a resolved hard owner, then admits that owner's bounded transient error backoff instead of treating the one-account pool as unavailable. The upstream change lacks its required OpenSpec artifacts. Its original lint and unit failures are migration-topology failures, not evidence that transient admission may bypass independent gates.

## What changes

- Thread hard-owner pool provenance through sticky, pinned-owner, seed, and unbound selection.
- Admit only an otherwise eligible hard owner serving transient error backoff without resetting its error counters.
- Retain account ownership, actual retry exclusion, authorization, persisted availability, cooldown, concurrency limits, and reservation-before-health settlement.
- Add product-path file-pin regression and admission guard coverage without replacing existing assertions.

## Impact

- Capability: sticky-session-operations.
- Source provenance: bcdd95ec568ea87e1ad08b848b91d419c86685b9, PR #2486.
- No new configuration, migration, frontend, deployment, or upstream write.
