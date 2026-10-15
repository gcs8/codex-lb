## MODIFIED Requirements

### Requirement: Usage capacity recognizes upstream ChatGPT plan types

The system MUST recognize account plan types returned by upstream ChatGPT auth and usage payloads when calculating absolute usage capacity. Weekly (secondary) capacity MUST be derived from the published monthly subscription quota as `7560 x tier multiplier x 7 / 30`, with tier multipliers `plus`, `business`, `team`, `edu` = 1, `prolite` = 5 and `pro`, `enterprise` = 10. `prolite` MUST keep its `1125.0` primary capacity and contribute `8820.0` secondary capacity, while the stored plan type value is preserved for display and request-log context.

#### Scenario: Pro Lite account contributes aggregate remaining credits

- **GIVEN** an active account whose stored `plan_type` is `prolite`
- **AND** its latest primary and secondary usage rows report `used_percent` below 100
- **WHEN** the system builds usage window summaries or per-account remaining credit values
- **THEN** the account contributes `1125.0` primary capacity and `8820.0` secondary capacity
- **AND** the computed remaining credits are non-zero according to the reported usage percent

#### Scenario: Weekly capacity is the monthly quota pro-rated to seven days

- **GIVEN** an account whose stored `plan_type` is `pro`
- **WHEN** the system resolves its secondary capacity
- **THEN** the capacity is `17640.0` (`7560 x 10 x 7 / 30`)
- **AND** the weekly credits pace reports the pool's monthly-quota equivalent as the weekly total `x 30 / 7`

## ADDED Requirements

### Requirement: Per-account subscription tier override

The system MUST let an operator with account write permission set an optional per-account tier override with an optional end time, through `PUT /api/accounts/{account_id}/quota-tier`, either as a multiplier of the Plus monthly quota (between 0.1 and 100) or as a raw monthly credit allowance (between 1 and 7,560,000), which is treated as `credits / 7560` x Plus. Setting both in one request MUST be rejected with HTTP 400. While the override is active the account's weekly capacity MUST be `7560 x override x 7 / 30` and its 5 h capacity MUST scale by `override / plan multiplier`. After the end time, or when the override is cleared with `null`, the plan-derived capacity MUST apply. An override MUST NOT make a window applicable that the plan does not have. Account summaries MUST report the override, its end time, the plan multiplier, the effective multiplier and the effective monthly credits.

#### Scenario: Grandfathered Pro 200 until a date

- **GIVEN** an account whose stored `plan_type` is `pro`
- **WHEN** an operator sets its tier multiplier to `20` ending `2026-10-30T00:00:00Z`
- **THEN** before that time the account contributes `35280.0` weekly capacity
- **AND** from that time it contributes the plan's `17640.0`

#### Scenario: Override end time must be in the future

- **WHEN** an operator sets a tier override whose end time has already passed
- **THEN** the request is rejected with HTTP 400 and the account is unchanged

#### Scenario: Raw monthly credits are equivalent to their multiplier

- **GIVEN** an account whose stored `plan_type` is `prolite`
- **WHEN** an operator sets its monthly credit allowance to `45360`
- **THEN** its effective tier multiplier is `6.0`
- **AND** it contributes `10584.0` weekly capacity (`45360 x 7 / 30`)
