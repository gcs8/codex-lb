# Boundary and compatibility notes

## Exception producers and imports

`OauthService` imports `exchange_authorization_code` for browser and manual callbacks and `request_device_code` for device start from `app.core.clients.oauth`. The direct branch leases the shared aiohttp session and enters `ClientSession.post`, which awaits `ClientSession._request`. Connector failures are `aiohttp.ClientConnectorError`, a `ClientConnectionError`. Disconnections and TLS connection failures share that connection hierarchy. Exchange timeouts are built-in `TimeoutError`, also exported as `asyncio.TimeoutError`. Interrupted body reads can raise `aiohttp.ClientPayloadError`. These specific types are translated only while posting or consuming the response, not while leasing the client, resolving policy, validating data or persisting accounts.

The routed branch calls the imported `CodexClient`. That producer handles aiohttp request errors, proxy/native egress errors and response buffering. It emits content-free `CodexTransportError` diagnostics with endpoint identity, phase and exception class. Native failures originate as `NativeEgressError`, normalized inside CodexClient. The OAuth `_codex_post` mapping already supports `CodexTransportError`; its existing code/message and routing are preserved. httpx is used by the test ASGI client, not as a direct OAuth producer. It is not added to the direct aiohttp catch list. Unknown RuntimeError, local configuration exceptions, cancellation and SystemExit remain outside the new catch.

## Preserved contracts

- Browser callback remains HTTP 200 product HTML after a known OAuth error. It durably finalizes only the matching flow and observes durable success-wins semantics.
- Device start remains HTTP 502 dashboard error on OAuthError. No new retry, flow identifier, polling task or partial code is invented on failure.
- Existing manual callback already handles OAuthError and sanitizes unknown Exception separately. The fix is not a new broad manual-route catch.
- The direct helper emits no logs or raw causes. `from None` suppresses exception chaining. Callback access logging remains disabled.
- OAUTH_TIMEOUT_SECONDS=30, URL/payload encoding, camel-case request/query aliases, provider status/code/message behavior, invalid-response errors and proxy-denial routing remain unchanged.
- Device token polling is not redesigned. Its authorization-code continuation inherits the fixed authorization exchange; its initial token-poll HTTP call remains outside this issue.

No real provider, credentials, OAuth login or deployment is used by verification. Callback tests use the actual loopback aiohttp server; device and manual routes use the actual full ASGI application without entering lifespan. Only aiohttp's imported `_request` network boundary is synthetic. Unknown callback failures intentionally remain HTTP 500 and cancellation closes the socket. No successful response is manufactured for those classes.
