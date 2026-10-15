## 1. Reproduction

- [x] Preserve executed public RED on native and v1 routes with real downstream and loopback upstream sockets.
- [x] Record exact receive cancellation, raw-frame consumption and producer dispatch evidence.

## 2. Ownership transfer

- [ ] Parent transfers the shared WebSocket receive loop from PR2398's separate owner before implementation.
- [ ] Implement one downstream receive owner without changing routing or replay policy.

## 3. Acceptance

- [ ] Cover both orderings, cancellation, ordinary idle close, continuity pins, API-key reservations and bounded cleanup.
- [ ] Run all affected WebSocket, close, routing, bridge and lifecycle modules at original caps.
- [ ] Run lint, format, type, cancellation, timing, architecture and pinned strict OpenSpec gates.
- [ ] Parent full acceptance remains pending.
