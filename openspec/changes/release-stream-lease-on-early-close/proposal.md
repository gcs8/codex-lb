# Release stream leases on early close

## Why

PR #2616 pins a missing close propagation between the public Responses normalizer, reasoning normalizer and retry generator. Validate this against the maintained public routes and real account admission before porting only that delta.

## What changes

- Close each inner iterator when a streaming wrapper exits.
- Preserve native transport-failure aborts, public SSE envelopes, cancellation, reservation ownership and settlement ordering.
- Do not change retry policy, account scope, native code, settings or capacity limits.

## Impact

Proxy streaming wrappers and regression coverage. No schema or deployment changes.
