# Focused fork port

Source PR #1962 includes a large conflicted cleanup rewrite. This lane isolates local probe ownership, cancellation-safe undispatched handback, and durable cooldown reconciliation. It preserves every current regression body and canonical requirement block. Source reconnect retirement and retained account leases are not included.

For example, request A owns generation 1, enters terminal cleanup, and waits. Request B later claims generation 2. A's late failure, return, or completion must leave B's owner, deadline, cooldown, and durable episode unchanged. B can still settle generation 2.

The lease remains process-local. This does not claim replica-wide exclusive probing. Parent composition suites and owner review remain separate gates.
