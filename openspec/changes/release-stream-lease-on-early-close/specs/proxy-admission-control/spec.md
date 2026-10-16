## ADDED Requirements

### Requirement: Responses wrappers close their owned inner streams

When a native or public Responses stream exits normally, returns early, raises, is cancelled or is closed by its consumer, each wrapper MUST close its owned inner stream after any owned active iteration has stopped. Cleanup MUST reach the retry generator and release its account stream lease without relying on garbage collection or restart. Cancellation and unknown failures MUST retain their original behavior. The proxy MUST preserve reservation ownership and settle usage before account-health writes, without replaying work or changing account scope solely for downstream cancellation.

#### Scenario: Native transport give-up releases the lease
- **GIVEN** a native Responses stream that emitted an event and then a synthetic transport failure
- **WHEN** the normalizer raises `stream_incomplete`
- **THEN** cleanup reaches the lease owner before the error leaves the wrapper
- **AND** the next legitimate request can acquire the same account slot

#### Scenario: Consumer closes at a yielded event
- **WHEN** a consumer closes a public or native Responses stream at a yield
- **THEN** all owned inner streams close and account admission is released
- **AND** downstream cancellation alone does not make a healthy account unhealthy

#### Scenario: Active read is cancelled before close
- **WHEN** an owning consumer cancels a pending next-event read
- **THEN** it awaits that read before closing the iterator
- **AND** no concurrent async-generator close or orphan cleanup task is used

#### Scenario: Cancellation or failure during downstream send
- **WHEN** the response exits while its downstream send is blocked or raises
- **THEN** the response closes its body iterator after body iteration stops
- **AND** all owned cleanup completes before its delivery outcome is recorded exactly once
- **AND** only sends that returned count as delivered chunks and an already delivered terminal remains delivered

#### Scenario: Repeated cancellation during cleanup
- **WHEN** the caller is cancelled repeatedly during delayed owned cleanup
- **THEN** cleanup drains the pending read, all fallback closes and reservation cleanup before propagating cancellation
- **AND** a deliberately cancelled startup child does not skip later cleanup

#### Scenario: Bridge child settles before wrapper inspection
- **WHEN** the bridge forwarding consumer exits early
- **THEN** its child closes before the wrapper inspects settlement ownership or writes deferred account health
- **AND** both raw retry forwarding branches close their retained retry child without changing fallback provenance or settlement policy
