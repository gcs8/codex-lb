# Preserve downstream receive ownership across clean close

## Why

Issue #1304 describes a queued `response.create` consumed by a cancelled ASGI receive at upstream generation retirement. The current public handlers delegate to the shared WebSocket mixin, whose polling and idle recheck cancel fresh receives. A prepared request's pending deque cannot recover a raw frame lost before preparation.

## What changes

- Require one downstream receive owner across poll deadlines and upstream retirement.
- Retain existing admission, routing pins, replay eligibility, settlement and bounded teardown contracts.
- Add a barrier-controlled real downstream WebSocket and loopback upstream reproduction on both public routes.

## Impact

Affected capability: responses-api-compat. No client, Rust, queue-capacity, routing-policy or new configuration changes are proposed.

Implementation is blocked pending parent ownership transfer because the receive loop is in PR2398-owned `_service/websocket/mixin.py`, outside this lane's permitted source boundary. The public regression is preserved as RED, not a completed fix.
