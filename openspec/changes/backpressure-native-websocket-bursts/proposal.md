## Why

A native upstream WebSocket can abort a healthy burst at the Python adapter's 65th undrained data message. A local item-count boundary must apply backpressure, not discard valid frames. Shared command acknowledgements and cancellation must continue while data admission waits.

## What Changes

- Preserve the 64-message decoded queue and existing byte limits; move admission control to the native socket owner through a negotiated receive-credit contract.
- Bound native pending data and retained payload bytes, including data forwarded across IPC but not yet consumed.
- Preserve ordered data, explicit byte-budget failures, command correlation, request isolation and owned-task shutdown.
- Qualify actual compiled helper traffic against loopback upstreams and the public Responses routes, without changing replay, billing, account-health or proxy-service ownership.

## Impact

Affected capability: outbound-http-clients. Native helper and its Python client require coordinated source qualification. No settings, migrations, provider traffic, packaging or deployment changes.
