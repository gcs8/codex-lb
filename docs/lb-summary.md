# Read-only LB summary

Owner capabilities: [key-lb-summary](https://github.com/gcs8/codex-lb/tree/ryoko/integration/openspec/specs/key-lb-summary) and
[usage sections](https://github.com/gcs8/codex-lb/tree/ryoko/integration/openspec/specs/account-pool-usage-v1-usage).

`GET /v1/lb/summary` accepts a normal proxy API key in `Authorization: Bearer …`.
Dashboard sessions do not authorize it. It requires an explicit `lb_summary` entry
in that key's existing `usage_sections`; existing defaults stay unchanged. An operator
can set the field through the existing dashboard key create/update API (`usageSections`
in its camel-case payload). This API-only addition creates no new UI, environment
variable or redemption permission. A summary grant never permits mutations.

Missing, invalid, disabled, expired or revoked keys receive 401. Keys without the
section receive 403. Successes and endpoint denials have `Cache-Control: no-store`.
Unknown/duplicate query fields and GET bodies receive a fixed 400 response, without
reflecting their values. Unexpected failures receive only `summary_unavailable` (500).

## Window and scope

`window=1h`, `window=24h` (default), or `window=7d` are the only choices. Counts
cover retained, nondeleted, normal request-log rows from the window start through
server now, owned by this key. They are not global pool request statistics. With
account-assignment scope enabled, they also require a current assigned account;
an enabled empty scope returns no requests or cohorts, never all accounts. Unscoped
keys still see only their own requests, including requests without account attribution.
Retention may make older windows incomplete; these are retained observations, not
billing history. No upstream calls, quota refreshes, or transport instrumentation occur.

## Closed response

Only these top-level fields are returned:

| Field | Shape / meaning |
|---|---|
| `window` | Selected literal window |
| `requests` | `total`, `success`, `error`, `cancelled`, `unknown`, `errors_by_code` |
| `service_tier` | Separate `requested` and `actual` count maps; no inferred actual tier |
| `cache` | `input_tokens`, `cached_input_tokens`, `hit_ratio`, `measured_requests`, `unknown_requests` |
| `transport` | Upstream `http`, `websocket`, `configured_auto`, `unknown` count map |
| `models` | Finite known model count map plus `unknown` |
| `accounts` | Optional plan/status quota cohorts; entirely omitted when hide-upstream-quota is enabled |

A missing count-map entry means zero rows in that **recorded label**, not evidence that
all transport/tier values were recorded. Unrecorded/unrecognized values count as
`unknown`; `auto` upstream configuration counts as `configured_auto`, never as proof
of the actual wire. Downstream `transport` and legacy merged `service_tier` are not
used as substitutes for upstream transport or actual service tier.

Cache statistics use the paired measured subset: rows with input between 0 and
10^12, cached >= 0 and cached <= input. The token counts are sums over that subset;
`hit_ratio = sum(cached_input_tokens) / sum(input_tokens)`. A measured zero denominator
returns 0.0; no measured rows returns null totals and ratio. Other rows contribute
to `unknown_requests`, not fake zero measurements. No token strings are returned.

Each account cohort contains exactly `plan`, `status`, `count`, `primary`, `secondary`.
There are **no per-account aliases**: plan/status cohorts avoid revealing raw IDs,
emails or reversible/predictably hashed identities. They cover only permitted,
non-pending-deletion accounts. Windows use each account's latest recorded snapshot
(legacy null window means primary), not a live refresh. `primary` is the 5-hour window and
`secondary` the weekly one: weekly-only plans (Pro, Pro Lite) that report their 7-day window
in the primary slot are normalized to `secondary`, and a zero-duration slot with no reset is
treated as absent rather than 0 % used. Plans are `free`, `plus`, `prolite`, `pro`, `team`,
`business`, `enterprise`, `edu`, else `unknown`. Each window contains exactly:

- `known_accounts`: count with valid finite percentages in [0,100].
- `used_percent_mean`: unweighted mean over those accounts, or null.
- `reset_at_earliest`, `reset_at_latest`: observed reset range, integer UTC epoch
  seconds; null when unknown/invalid. Expired resets remain visible as expired observations.
- `recorded_at_oldest`, `recorded_at_newest`: UTC observation timestamps, or null.

Cohort averages are not credit-weighted pool capacity. Known counts and observation
ranges let consumers distinguish partial/stale coverage from a measured zero.

## Bounded labels and SQLite cost

Plans: free, plus, pro, team, business, enterprise, edu; statuses: active,
rate_limited, quota_exceeded, paused, reauth_required, deactivated. Tiers: auto,
default, flex, priority, scale. Errors: stream_incomplete, server_error, overloaded,
rate_limit_exceeded, insufficient_quota, upstream_error, timeout,
invalid_request_error, model_not_found, authentication_error.

Models: gpt-5, gpt-5-mini, gpt-5-nano, gpt-5-codex, gpt-5.1, gpt-5.1-codex,
gpt-5.1-codex-mini, gpt-5.1-codex-max, gpt-5.2, gpt-5.2-codex, gpt-5.3-codex,
gpt-5.4, gpt-5.4-mini, gpt-5.4-nano, gpt-6, gpt-6.1, gpt-6.1-sol. Other model
names (including custom providers) become `unknown`; they are not echoed.
All dimensions are bucketed before SQL grouping, so arbitrary stored strings cannot
grow response cardinality. Extending these export labels is a deliberate source change,
not a dynamic registry side effect. No prompt, payload, headers, email, account/key ID,
account alias, free-form error message or exception text is exported.

Six request aggregate queries use a materialized key/time range backed by the existing
key/time index; one additional cohort query uses indexed latest-window lookups.
The query count does not grow with requests/accounts. Cost scales with this key's
retained seven-day maximum range and permitted cohort size, not the whole logs table.
Seeded SQLite tests assert query plans and query counts rather than wall-clock timing.
