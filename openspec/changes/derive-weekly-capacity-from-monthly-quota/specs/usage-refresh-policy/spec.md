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
