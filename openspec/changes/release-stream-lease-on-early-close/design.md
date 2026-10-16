# Design

The consuming wrapper owns closing its inner iterator after iteration has stopped. Use finally blocks so early returns, consumer aclose and failure unwind to the actual retry generator. Active next-event tasks must be cancelled and awaited by their existing owner before any inner aclose. Do not swallow cancellation or schedule an unowned close task.

The maintained startup guard closes the public normalizer but cannot bypass missing finally blocks below it. The raw account lease and API-key reservation remain owned by the retry implementation; wrappers do not independently release or settle them. Existing owner-forwarding guards and receive ownership are unchanged.

The response consumer closes its body iterator after Starlette has stopped its body task, including cancellation or failure inside send. The body chain drains any pending read before closing its sources. One owned cleanup sequence defers repeated caller cancellation through fallback closes and reservation cleanup, then propagates cancellation. Startup retains the original generator across probe/prepend wrappers; the initial heartbeat takes inner ownership only when iteration starts. Both raw bridge forwarding branches own child close. Bridge child cleanup precedes settlement inspection and deferred health writes.

Delivery observation remains after send returns. Cleanup finishes before the exactly-once outcome record, including when cleanup raises. A delivered terminal is immutable. ASGI 2.0 retains Starlette task-group disconnect handling; ASGI 2.4 retains its OSError-to-ClientDisconnect contract. No framework changes, close ledger, retry accounting or new settings are introduced.
