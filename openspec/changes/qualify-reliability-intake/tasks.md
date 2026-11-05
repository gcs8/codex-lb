## Implementation

- [x] Preserve upstream attribution and fork-specific contracts.
- [x] Observe finite SSE/ASGI, raw-peer identity and stalled-lifespan regression failures on baseline.
- [x] Implement the three narrow runtime fixes without dependency or unrelated account-policy changes.
- [x] Cover successful, error, cancellation, missing-provenance and cleanup cases, preserving the original assertions in adapted clock fixtures.

## Qualification

- [ ] Complete all broad qualification gates on the final candidate. Full unit and focused regressions pass; the integration-core startup-environment failure and pending bridge gate remain explicit in the PR evidence.
- [x] Synchronize canonical requirements/context and strictly validate this change.
- [ ] Obtain exact-candidate independent review and green hosted CI.
- [ ] Integrate serially on the current tip only after all merge gates; no live rollout.
