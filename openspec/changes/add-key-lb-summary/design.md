## Decisions
Use existing usage-key auth and `usage_sections=lb_summary` opt-in, independent of redemption permissions. No identity store exists suitable for per-key public aliases; use finite plan/status cohort labels instead of hashing emails or exposing account aliases. Quota means, known counts, reset ranges and oldest/newest observations retain cohort usefulness without identities. Hide-quota omits accounts altogether.

## Contract
The delta spec defines exact fields. Finite labels are versioned server constants; custom models/errors become unknown. No dynamic model registry (it can contain administrator/client-controlled strings). Request tokens are integer counts, never token strings. Cache measurement validity is row-paired; no NULL-to-zero coalescing before knownness is established. Auto upstream labels remain configured_auto, not actual wire proof. This change does not port upstream #2624.

## Queries
One SQL aggregate for request/token totals, five bounded dimension aggregates (error, requested tier, actual tier, upstream transport, model), and one grouped quota query using indexed correlated latest-snapshot lookups. Key/time bounds reuse existing indexes; no migration. A MATERIALIZED key/time CTE prevents SQLite from choosing a global deleted_at/time index before key filtering (observed in the seeded regression). Materialization remains entirely in SQL and selects only aggregate inputs. No raw request materialization or provider refresh. Retained logs may undercount windows beyond retention, and cohort snapshots are observations, not live guarantees.
