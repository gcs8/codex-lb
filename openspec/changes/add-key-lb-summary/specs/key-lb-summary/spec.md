## ADDED Requirements

### Requirement: Explicit key-scoped read-only summary
The system SHALL serve `GET /v1/lb/summary` using normal usage-key authentication, independently of dashboard credentials and proxy auth enablement. Missing, malformed, expired, disabled or revoked keys SHALL receive 401; authenticated keys without explicit `lb_summary` in `usage_sections` SHALL receive 403. Default and legacy-null sections SHALL remain `upstream_limits,account_pool_usage`. Responses including denials SHALL use `Cache-Control: no-store`.

#### Scenario: Opt-in only
- **WHEN** an authenticated key with default sections requests the summary
- **THEN** it receives 403 and no summary
- **AND** explicitly granting `lb_summary` permits the GET without granting any mutation

### Requirement: Closed private aggregate contract
The response SHALL contain only `window`, `requests`, `service_tier`, `cache`, `transport`, `models`, and optionally `accounts`. Requests SHALL contain `total`, `success`, `error`, `cancelled`, `unknown`, and `errors_by_code`. Tier maps SHALL be separate `requested` and `actual`. Cache SHALL contain `input_tokens`, `cached_input_tokens`, `hit_ratio`, `measured_requests`, and `unknown_requests`. Transport and model maps SHALL use finite server-owned allowlists with an `unknown` bucket. Accounts SHALL be plan/status cohorts, not per-person identities: each SHALL contain only `plan`, `status`, `count`, `primary`, and `secondary`. Each quota window SHALL contain only `known_accounts`, `used_percent_mean`, `reset_at_earliest`, `reset_at_latest`, `recorded_at_oldest`, and `recorded_at_newest`. Reset epochs SHALL be integer seconds; observations SHALL be UTC datetimes. Unknown/nonfinite quota values SHALL be null, not zero. Arbitrary query parameters, duplicate window parameters and GET bodies SHALL be rejected with a fixed 400 error without reflecting request-derived values.

#### Scenario: Privacy and hide-quota
- **WHEN** a caller submits arbitrary model, tier, error, account alias or extension strings
- **THEN** none are reflected in response fields or bucket names
- **AND** no raw account/key IDs, emails, secrets, prompts, payloads, headers or error messages are emitted
- **AND** enabling hide-upstream-quota omits the entire accounts field and does not query quotas

### Requirement: Key and cohort isolation
Request aggregates SHALL include only retained, nondeleted normal request logs owned by the caller's key in the selected time window. With account assignment scope enabled, request and quota queries SHALL include only currently assigned accounts, and an empty assignment SHALL yield empty requests and accounts, never the global pool. Unscoped keys SHALL retain key-owned request isolation while quota cohorts cover non-pending-deletion accounts. The summary SHALL perform no refresh or provider calls.

#### Scenario: Shared account, different keys
- **WHEN** two keys issue requests through the same account
- **THEN** each summary counts only its own requests
- **AND** a scoped key cannot observe another account's requests or quotas

### Requirement: Bounded measurement semantics
Window SHALL be exactly `1h`, `24h`, or `7d`, default `24h`, with a hard maximum of seven days and an upper bound of the current server time. SQLite request reads SHALL use existing key/time indexes and SQL aggregation rather than materializing raw logs; grouped cardinality SHALL be bounded before grouping using server-owned allowlists. A summary SHALL use at most seven request-stat queries plus one quota-cohort query, independent of row count. Recorded actual tier SHALL not fall back to requested tier. Transport SHALL use upstream transport, never downstream transport; `auto` SHALL remain `configured_auto` rather than claiming HTTP or WebSocket. Cache totals SHALL sum only rows with input between 0 and 10^12, nonnegative cache measurements and cache <= input; ratio SHALL be cached/input for that measured subset, 0 for measured zero input, and null for no measured rows. Unknown counts SHALL distinguish unrecorded data from measured zero. Quotas SHALL use latest recorded primary (including legacy null window) and secondary snapshots with observation timestamps and reset ranges, never pretending an expired snapshot is a fresh measurement. A seven-day snapshot recorded in the primary slot SHALL be reported as the secondary window when the secondary slot is absent, older, or a placeholder (no positive duration and no reset); placeholders SHALL never count as measurements. The plan allowlist SHALL include `prolite`.

#### Scenario: Seeded SQLite bounded query
- **WHEN** many historical and foreign-key rows exist and a seven-day summary is requested
- **THEN** query plans use key/time range indexes and fixed query counts
- **AND** malformed, negative or oversized windows cannot trigger an unbounded scan
