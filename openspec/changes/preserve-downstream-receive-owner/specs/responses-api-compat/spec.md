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
