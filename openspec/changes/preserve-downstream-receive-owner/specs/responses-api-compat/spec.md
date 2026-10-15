## ADDED Requirements

### Requirement: Downstream receive ownership survives upstream retirement

The native and `/v1/responses` public WebSocket routes MUST retain one connection-owned downstream receive task across polling deadlines, idle rechecks and clean upstream generation retirement. They MUST transfer each received frame exactly once into the existing validation and request ownership path before starting another receive. Only final downstream connection cleanup MAY cancel and join the receive owner, within the existing bounded cleanup deadline.

Retaining ingress MUST NOT change account ownership, explicit caller, file, MCP or opaque continuity pins, inject a fabricated upstream anchor, broaden replay eligibility, penalize a healthy idle account, or allow a retired owner to settle the next turn's API-key reservation.

#### Scenario: Queued next turn overlaps clean upstream close

- **GIVEN** the first turn has completed on an upstream connection
- **AND** the next valid create has left the downstream transport but has not entered request preparation
- **WHEN** a poll deadline and upstream clean close occur in either coordinated order
- **THEN** the same receive owner retains the queued frame
- **AND** the next turn is dispatched once through its correct fresh owner and connection or receives the existing documented terminal error
- **AND** no frame is lost and no old owner settles the new turn

#### Scenario: Cancellation while a receive is blocked

- **WHEN** the downstream scope is cancelled with a blocked receive owner
- **THEN** final connection cleanup cancels and joins that owner within its existing bound
- **AND** request, reservation and lease cleanup retains its existing single-owner behavior

#### Scenario: Retiring generation has observed an eligible next turn

- **GIVEN** a poll deadline has elapsed without cancelling the receive that consumed the next create
- **AND** the retiring generation subsequently observes that exact create before a clean close and before visible output
- **WHEN** existing replay policy admits its replacement attempt
- **THEN** the replacement receives exactly one eligible replay with the same request state and reservation
- **AND** the original request start and one-shot replay budget are preserved
- **AND** terminal settlement and request-log attribution belong to the successful dispatch owner exactly once

#### Scenario: Connection teardown owns the final receive

- **WHEN** a client disconnects, the downstream scope is cancelled, the server drains or the connection reaches its ordinary idle deadline
- **THEN** connection teardown joins the remaining receive owner, including a frame suspended after ASGI dequeue
- **AND** a raw frame not admitted before teardown creates no request reservation or upstream dispatch
- **AND** ordinary idle closure does not penalize an otherwise healthy account

#### Scenario: Queued pinned continuation retains its owner

- **WHEN** an explicit caller anchor, file-owned input, anchored MCP approval or anchored opaque item crosses a clean-close ingress handoff
- **THEN** normal preparation and account selection preserve its original hard owner and exact input
- **AND** retaining that frame grants neither cross-account fallback nor new replay eligibility
