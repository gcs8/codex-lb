# Design

Normalize weekly-primary rows before projecting expiration. Use the accepted `expire_elapsed_window_rows` contract: reset deadlines at or before now become zero usage with no reset, retaining duration and capacity; absent reset deadlines remain unchanged. An aggregate without a reset is omitted by the existing serializer. Use `naive_utc_to_epoch(utcnow())` instead of adding a raw clock.

Only primary and monthly projections change. `_compute_pooled_credits` explicitly preserves raw secondary values to avoid turning an exhausted weekly pool free during refresh. Although native rate-limit headers expire secondary rows, that display precedent does not authorize changing availability or credit policy. Keep secondary aggregate values and admission untouched pending an owner decision. Weekly-only rows remain secondary and cannot fabricate a primary.

The current `/v1/usage` aggregate is a visible global upstream section, whereas `account_pool_usage` is assignment scoped and request statistics and configured limits are key scoped. Preserve these distinct existing contracts, including explicit empty assignments and hide-upstream-quota. Do not repair route aliases or permissions in this lane.
