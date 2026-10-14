## Decision

The predicate is inclusive: a reset-confirmed candidate qualifies when the
pre-refresh usage is greater than or equal to the configured percentage. The
setting is therefore a meaningful range rather than an on/off switch:

| Setting | Eligibility |
| --- | --- |
| `0%` | every confirmed reset, including a `15% -> 0%` reset |
| `50%` | only resets whose previous sample was at least `50%` used |
| `99%` | only practically exhausted resets at or above `99%` |
| `100%` | only fully exhausted resets |

The default is intentionally `0%` because the operator's desired behavior is
to warm every confirmed reset. A default of `100%` would mean almost the
opposite: it would skip resets whose previous sample was below full exhaustion.

## Safety boundaries

The threshold is only one eligibility gate. Existing reset confirmation,
post-reset availability, global/account opt-in, account-active, model
eligibility, cooldown, and durable account/window/reset deduplication remain
unchanged. The threshold does not make an unconfirmed or exhausted post-reset
sample eligible.

For a paid-to-Free transition, upstream can replace the paid window with a
fresh monthly row and there may be no comparable pre-refresh monthly sample.
The default zero threshold treats the confirmed transition as eligible. A
positive threshold fails closed until a pre-refresh monthly sample exists and
meets the configured floor.

## Migration behavior

The original threshold migration created
`limit_warmup_exhausted_threshold_percent` with `99.0` as the server default.
That column must remain unchanged while old replicas may still serve traffic.
The activation migration depends on the compatibility PR, initializes every
`NULL` active value to `0.0`, and makes the active column non-null with a `0.0`
server default. The current application exposes only that active column through
the public setting name; it maps the legacy column internally to prevent schema
drift but never dual-writes or synchronizes it. Downgrade returns the active
column to the compatibility revision's nullable, no-default shape and leaves
the legacy column untouched.

## Fork migration composition

The frozen source is `cc5e2478d6c9515d93de6d19209191def5a759b6`.
Its stage revision branched from the OIDC revision while the current target
already contained both September 14 branches and their September 18 merge.
Only the two unmerged additions are re-parented and re-stamped:

| Original revision | Candidate revision | Candidate parent |
| --- | --- | --- |
| `20260909_130000_stage_limit_warmup_zero_compat` | `20260918_010000_stage_limit_warmup_zero_compat` | `20260918_000000_merge_scim_and_overflow_heads` |
| `20260906_000000_restore_limit_warmup_threshold_default` | `20260918_020000_restore_limit_warmup_threshold_default` | `20260918_010000_stage_limit_warmup_zero_compat` |

The first new parent eliminates the observed two-head fork. Both new timestamp
slots are unused and follow their parents, including the original activation's
inverted September 6 timestamp. All 263 target revisions remain byte-identical.
The historical recovery archive retains its original requirements and artifacts;
this active change supersedes only reset-threshold eligibility, not recovery.

The public threshold is a database-only T3 behavior tunable stored in
`dashboard_settings.limit_warmup_reset_threshold_percent`. It introduces no
Settings environment field, environment seed, or budget exception. Existing
inheritable settings retain code default < environment < dashboard precedence.
Global and per-account warm-up remain disabled by default.

