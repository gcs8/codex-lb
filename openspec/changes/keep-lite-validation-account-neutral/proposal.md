# Keep Lite validation account-neutral

## Why

Issue 2538 composition testing with the real Rust HTTP helper establishes that
pretty HTTP 400 bodies and Lite normalization are already covered, but the exact
reported deterministic Lite validation rejection still increments account health
through the forced-HTTP path. A payload rejection is not account failure.

## What changes

Recognize only `unsupported_value` with the exact reported Responses-Lite
parallel-tool-calls rejection message as account-neutral when status is 400 or
absent. Preserve all route error envelopes, terminal policies, routing, retry,
quarantine, and other error classifications. Add real native producer/public
route composition and narrow negative controls.

## Impact

Only Responses streaming account-health classification. No settings, migrations,
new transport, broad invalid-request exemption, or live-provider operations.
