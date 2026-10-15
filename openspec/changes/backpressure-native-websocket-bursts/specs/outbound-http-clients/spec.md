## ADDED Requirements

### Requirement: Native WebSocket bursts use bounded admission instead of item overflow

Native WebSockets using the optional `websocket_receive_window_v1` capability SHALL preserve the 64-message decoded-message queue and the existing 32 MiB per-request queued-payload budget. The adapter SHALL request `receive_backpressure` only when the helper advertises that capability, and SHALL send exactly one `websocket_consumed` receipt per consumed data message while the exchange remains active. Helpers without this optional capability SHALL remain compatible with the existing call contract, without receiving the new request field or receipt command. Requests omitting the field SHALL retain legacy behavior.

Native admission SHALL account for pending native payloads and payloads forwarded to the adapter until application consumption releases their charge. Text SHALL charge UTF-8 bytes; interpreted text SHALL additionally charge its retained JSON and routing metadata; binary SHALL charge its base64 IPC representation and decoded bytes. Exceeding the byte budget SHALL fail explicitly with consumer_backpressure, without replay or affecting sibling exchanges. Native pending data SHALL retain at most 64 events, with at most 64 unconsumed data events forwarded to the adapter, and SHALL stop upstream reads at the pending cap instead of increasing the adapter's 64-message limit. The adapter's separate IPC queue SHALL retain its existing 4096-event and 32 MiB bounds and the upstream message limit SHALL remain 16 MiB.

#### Scenario: Ordinary small burst with temporarily paused consumer

- **WHEN** an actual native upstream emits 64, 65 or 129 valid small messages while the application temporarily pauses consumption
- **THEN** command acknowledgement continues and every data message is eventually delivered in its original order after consumption resumes
- **AND** Responses payloads and routing metadata remain unchanged

#### Scenario: Byte budget exhaustion

- **WHEN** retained payloads would exceed the existing byte budget
- **THEN** only that exchange fails explicitly and sibling WebSocket and HTTP exchanges continue

### Requirement: Native backpressure does not block control ownership

A native data-admission wait SHALL NOT block the shared IPC reader, command dispatch, cancellation or helper source-EOF shutdown. Connection-owned channels and tasks SHALL remain bounded and SHALL be closed or joined on termination. No ambiguous send SHALL be retried. While native pending admission has room, WebSocket protocol control frames SHALL progress independently of Python data consumption. At the pending cap, control frames behind unread data MAY wait for application consumption. Terminal data ordering SHALL be preserved when the producer can finish normally; explicit local cancellation or close MAY retire undelivered data. Peer close SHALL flush its wire acknowledgement and release the closed transport before waiting for application consumption and SHALL disable further keepalive deadlines. A subsequent send SHALL fail only that command through the existing WebSocket error envelope without discarding retained receive data or its ordered terminal event.

#### Scenario: Peer transport closes before buffered application delivery

- **WHEN** the decoded receive window is full, admitted pending data remains, and the peer closes after a protocol-control barrier
- **THEN** the peer's wire close and transport shutdown finish before application consumption resumes
- **AND** a subsequent send fails without blocking credits, and every retained frame and the close event are delivered in order when the application drains

#### Scenario: Cancel while full

- **WHEN** native data admission is blocked and the consumer cancels or closes the exchange
- **THEN** pending sends settle and owned waits terminate without blocking other requests or leaving a helper child behind

#### Scenario: Source EOF while full

- **WHEN** helper stdin closes with blocked data admission
- **THEN** the socket owner terminates and the helper process exits boundedly
