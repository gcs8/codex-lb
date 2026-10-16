## MODIFIED Requirements

### Requirement: Request logs distinguish actual and requested service tiers
When a request log entry includes service-tier data, the dashboard request-log API response MUST expose the billable tier, requested tier, and actual tier separately. When the requested tier is present and differs from the reported tier (`actualServiceTier`, falling back to `serviceTier`), the recent-requests UI MUST render the model label with the requested tier and MUST show the reported tier as a secondary upstream-reported line. Otherwise it MUST render the model label with the reported tier.

#### Scenario: Dashboard shows upstream-selected tier and requested tier
- **WHEN** a request log entry is recorded with `requested_service_tier: "priority"`, `actual_service_tier: "default"`, and billable `service_tier: "default"`
- **THEN** the `GET /api/request-logs` response includes `requestedServiceTier: "priority"`, `actualServiceTier: "default"`, and `serviceTier: "default"`
- **AND** the dashboard renders the model label with `priority`
- **AND** the dashboard also shows that upstream reported `default`

#### Scenario: Request without a requested tier keeps the reported tier
- **WHEN** a request log entry has no requested tier and `actual_service_tier: "default"`
- **THEN** the dashboard renders the model label with `default`
- **AND** no upstream-reported line is shown

#### Scenario: Request detail dialog uses the same label
- **WHEN** the request detail dialog opens for an entry whose requested tier differs from the reported tier
- **THEN** its Model field renders the model label with the requested tier
