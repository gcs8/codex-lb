# responses-api-compat delta

## ADDED Requirements

### Requirement: Hard bridge retry-circuit cooldowns use an explicit zero sentinel

For a hard HTTP bridge key, the proxy MUST load an absent or already elapsed
durable `cooldown_until_epoch` as the in-memory `0.0` sentinel. A real future
durable deadline MUST remain an active monotonic cooldown, and durable failure
counts MUST remain available for admission and later recovery decisions.

#### Scenario: Missing durable deadline does not manufacture a probe transition

- **GIVEN** a durable hard-key row whose cooldown deadline is absent, zero, or
  negative
- **WHEN** the row is loaded for retry admission
- **THEN** the local cooldown is `0.0`
- **AND** no half-open lease is created solely because the row was reloaded
- **AND** repeated admissions remain allowed until a real cooldown transition
  occurs

#### Scenario: Elapsed positive durable deadline admits one local probe

- **GIVEN** a durable hard-key row at or above the failure threshold whose
  positive cooldown deadline has elapsed
- **WHEN** concurrent local requests ask for retry admission
- **THEN** the local cooldown remains the `0.0` sentinel
- **AND** exactly one request acquires a process-local half-open lease
- **AND** the other requests are suppressed until that probe settles

### Requirement: Half-open retry probes are exclusive within their owning process

After a real hard-key cooldown expires, the proxy MUST admit exactly one local
  half-open probe and suppress concurrent local admissions until that probe
  settles. The lease MUST record the owning HTTP bridge session. A probe return
  MUST be accepted only from that owner, MUST leave the durable failure count
  unchanged, and MUST represent the returned probe as an elapsed local cooldown
  so the next admission acquires a fresh lease. Each lease MUST also carry a
  process-local generation paired with its owner token and deadline. A release
  whose session, token, deadline, or generation does not match the active lease
  MUST be a no-op.

The durable retry row remains the replica-wide source for failure counts and
future cooldown deadlines. The active half-open owner is intentionally
process-local because the owner is the process holding the upstream socket; a
different replica may admit its own local probe after loading an elapsed row.
If a newer durable reset or lower failure count arrives while a local probe is
active, the process MUST retain that active lease and its local failure fence
until the probe settles. A newer durable reset MUST clear stale local detail
only when no local probe is active.

The active owner MUST remain exclusive while its request is still pending,
has attempted `response.create`, and has not entered terminal settlement, even
when the default half-open lease window elapses. While that request remains
live, the local lease MUST be renewed through the request's
`bridge_request_deadline` when that deadline is later than the default lease
window. A completion or other settlement MUST carry the durable episode and
process-local lease generation captured at admission; a late settlement whose
generation no longer matches the active lease MUST be ignored.

#### Scenario: A returned probe remains exclusive without a clock advance

- **GIVEN** a local probe returns on the same monotonic clock tick as its durable load
- **WHEN** later lookups miss or reload the unchanged durable row
- **THEN** the return MUST remain a pending single-flight transition until one fresh local lease consumes it
- **AND** a durable operation started before that return MUST NOT erase the newer transition
- **AND** any stronger future durable cooldown it observes MUST still suppress admission
- **AND** a fresh authoritative durable reset with no active owner MUST still clear the transition
- **AND** a durable operation started before that reset MUST NOT restore the cleared episode, even on the same clock tick
- **AND** a default zero clock without a return MUST NOT manufacture a transition

#### Scenario: Real expiry admits one local probe

- **GIVEN** a hard-key circuit at or above the failure threshold with a real
  cooldown that has elapsed
- **WHEN** concurrent local requests ask for retry admission
- **THEN** one request is admitted and owns a half-open lease
- **AND** another request for the same key is suppressed

#### Scenario: Continuity loss returns only the owning probe

- **GIVEN** session A owns the active half-open lease for a hard key
- **WHEN** session B reports a proxy-side continuity-ownership failure with
  explicit proxy continuity provenance
- **THEN** the active lease remains intact
- **WHEN** session A reports that same continuity loss
- **THEN** the lease is returned as an elapsed cooldown
- **AND** the failure count, last upstream failure detail, and durable row are
  unchanged
- **AND** the next local admission acquires one fresh half-open lease

#### Scenario: A live probe outlives the default lease window

- **GIVEN** a session owns a half-open probe whose request has attempted
  `response.create` and remains pending
- **AND** the request `bridge_request_deadline` is later than the default
  half-open lease window
- **WHEN** the default lease window elapses
- **THEN** the owning session remains the exclusive local probe owner
- **AND** the lease is renewed through the request deadline
- **AND** a sibling admission remains suppressed

#### Scenario: Late completion cannot clear a replacement probe

- **GIVEN** a half-open probe settles after its local lease was replaced by a
  newer probe for the same hard key
- **WHEN** the old completion carries its captured durable episode and
  process-local lease generation
- **THEN** the settlement is ignored
- **AND** the replacement probe and its failure fence remain active

#### Scenario: Replica-wide durable state and local lease state stay distinct

- **GIVEN** two proxy processes load the same future durable cooldown
- **WHEN** either process asks for admission
- **THEN** both honor the durable cooldown
- **AND** after the durable deadline has elapsed, each process may manage only
  its own process-local half-open lease

### Requirement: Retry-circuit failure accounting distinguishes proxy continuity loss

The proxy MUST NOT increment or persist retry-circuit failures for explicitly
identified proxy continuity-ownership loss, including
`continuity_owner_unavailable`, `previous_response_owner_unavailable`,
`bridge_owner_unreachable`, and `bridge_instance_mismatch`. A
`previous_response_not_found` or `bridge_previous_response_not_found` detail
MUST remain outside retry-circuit failure accounting when it is raw or
client-supplied. When the request state explicitly proves that the rejected
anchor was injected by this proxy, the detail MAY be treated as continuity-
neutral and return the active local probe. The proxy MUST continue to
increment and persist genuine upstream `stream_incomplete`,
`stream_idle_timeout`, and `clean_close` failures when their attempt is
eligible. Anchor replay and error-provenance policy remain governed by their
existing contracts.

#### Scenario: A stale probe failure cannot invalidate its replacement

- **GIVEN** a probe has entered terminal settlement and a replacement probe has
  subsequently claimed a different process-local lease generation
- **WHEN** the old probe reports a genuine upstream failure
- **THEN** the old failure MUST NOT change the retry-circuit count, cooldown,
  durable episode, replacement owner, or replacement lease
- **AND** terminal delivery and account settlement for the old request MUST
  still complete
- **AND** the replacement's successful completion MUST remain eligible to
  settle its captured episode and generation
- **AND** current-generation probe failures and ordinary non-probe failures
  MUST retain their existing eligible attempt-scoped accounting

#### Scenario: Existing circuit eligibility and continuity provenance remain enforced

- **GIVEN** an otherwise eligible eventless upstream attempt
- **WHEN** its terminal carries an explicit `stream_incomplete` response error
- **THEN** the proxy MUST record that detail through the existing attempt-scoped
  retry-circuit failure path
- **AND** accounting MUST require a hard-affinity bridge key, a pending request,
  and no prior response event for that attempt
- **AND** idle, post-response, internal prewarm, request-log-skipped,
  safe-replay-held, disarmed, and already-recorded attempts MUST NOT add another
  retry-circuit failure
- **AND** proxy continuity-loss details and raw or client-supplied
  `previous_response_not_found` or `bridge_previous_response_not_found` details
  MUST neither increment nor persist the retry circuit
- **AND** a rejected anchor MAY return the active local probe as continuity-
  neutral only when the request state explicitly proves that the proxy injected
  that anchor
- **AND** downstream terminal payload and account-health treatment MUST remain
  unchanged

#### Scenario: Proxy continuity loss is neutral

- **GIVEN** an eligible local half-open probe
- **WHEN** the proxy loses continuity ownership and the request carries
  explicit proxy continuity provenance
- **THEN** the circuit count does not increase
- **AND** the owner lease is returned when the reporting session owns it

#### Scenario: Client previous-response rejection does not strike the circuit

- **GIVEN** an eligible local half-open probe
- **WHEN** the upstream rejects a raw or client-supplied
  `previous_response_not_found` anchor without proxy continuity provenance
- **THEN** the retry-circuit failure count is unchanged
- **AND** no retry-circuit failure row is persisted
- **AND** the active half-open lease remains owned by its original probe

#### Scenario: Genuine upstream failure still opens the circuit

- **GIVEN** two eligible eventless upstream failures for one hard key
- **WHEN** each failure is recorded
- **THEN** the circuit reaches its configured threshold and suppresses later
  admissions with a real cooldown
