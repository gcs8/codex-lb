## ADDED Requirements

### Requirement: Hard-owner transient backoff admission preserves independent gates

When selection is constrained to a resolved hard continuity owner, the system MUST admit that otherwise eligible owner while it is serving its own bounded transient error-count backoff, including sticky, pinned-owner, seed-preference, and unbound selection paths. Admission MUST preserve the error count and last-error timestamp while backoff remains active. It MUST NOT select a different account or reinterpret soft locality as hard ownership. Ordinary soft selection MUST retain its existing backoff behavior and healthy sibling preference.

Hard-owner provenance MUST NOT bypass account-assignment or security authorization, persisted account unavailability, known expired reauthentication, active explicit cooldown, actual caller exclusions, concurrency limits, or opportunistic eligibility. File-pinned payloads MUST remain on their owning account. API-key reservation settlement MUST still complete before deferred account-health writes, and a failed settlement MUST NOT authorize those writes. A restricted-owner failure MUST NOT change global routing health.

#### Scenario: File-pinned owner serves transient backoff

- **GIVEN** a live durable input-file pin requires active account A
- **AND** account A is in transient error-count backoff and account B is healthy
- **WHEN** the Responses route selects and dispatches that file-pinned request
- **THEN** the request is dispatched only to account A
- **AND** account A's active backoff counters remain unchanged by selection

#### Scenario: Hard owner remains subject to independent gates

- **GIVEN** a resolved hard owner is in transient error-count backoff
- **AND** it is excluded by the caller, outside assignment or security scope, persisted unavailable, cooling down, known reauthentication-expired, or locally capped
- **WHEN** selection attempts to admit that owner
- **THEN** the independent gate retains its fail-closed result
- **AND** selection does not return a healthy sibling or mutate global health

#### Scenario: Ordinary soft selection does not gain hard-owner authority

- **GIVEN** a soft-only selection has a backed-off account and a healthy sibling
- **WHEN** selection runs without resolved hard-owner provenance
- **THEN** existing healthy sibling preference and backoff rules remain unchanged

#### Scenario: Error settlement retains ordering

- **GIVEN** an admitted owner-bound turn owns an API-key usage reservation
- **WHEN** an upstream error requires a deferred account-health write
- **THEN** reservation settlement completes before the health write
- **AND** unconfirmed settlement leaves the health write deferred
