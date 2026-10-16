## MODIFIED Requirements

### Requirement: API key usage_sections controls which /v1/usage detail sections are returned

The system SHALL store an API key's visible usage sections in a `usage_sections` TEXT field as a comma-separated list. The supported values SHALL be `upstream_limits`, `account_pool_usage`, and opt-in `lb_summary`. The system SHALL parse this field when building the `/v1/usage` response and conditionally include the corresponding sections, subject to global quota privacy settings. `lb_summary` SHALL authorize only the read-only summary capability and SHALL NOT be added to default or legacy-null sections.

#### Scenario: Default usage_sections includes all sections

- **WHEN** an API key is created without specifying `usage_sections`
- **THEN** the key's `usage_sections` SHALL be `"upstream_limits,account_pool_usage"`
- **AND** `/v1/usage` response includes both `upstream_limits` and `account_pool_usage`

#### Scenario: upstream_limits excluded

- **WHEN** an API key has `usage_sections` set to `"account_pool_usage"`
- **AND** a client calls `GET /v1/usage`
- **THEN** the response includes `account_pool_usage` but `upstream_limits` is an empty list

#### Scenario: account_pool_usage excluded

- **WHEN** an API key has `usage_sections` set to `"upstream_limits"`
- **AND** a client calls `GET /v1/usage`
- **THEN** the response includes `upstream_limits` and `account_pool_usage` is `null`

#### Scenario: Empty usage_sections excludes both

- **WHEN** an API key has `usage_sections` set to `""`
- **AND** a client calls `GET /v1/usage`
- **THEN** `upstream_limits` is an empty list AND `account_pool_usage` is `null`
