## Why

Our qualified fork lacks three focused reliability/security corrections from upstream #2681, #2632 and #2630. Source timeouts can be misclassified as heartbeats; dashboard identity trusts a projected client rather than the captured peer; managed HTTP cleanup can wait indefinitely during shutdown.

## What Changes

- Propagate source failures without heartbeat substitution, while preserving idle heartbeats and source/task cleanup.
- Use captured transport provenance for trusted-header identity and sanitization, preserving forwarding attribution and existing account policy.
- Bound the managed HTTP-client close wait without cancelling its transport-owned cleanup or skipping database clean-stop bookkeeping.

## Impact

Capabilities: responses-api-compat, admin-auth, graceful-shutdown. No new dependency, setting, migration, provider default, workflow, Rust or frontend changes. No live rollout is part of source qualification.
