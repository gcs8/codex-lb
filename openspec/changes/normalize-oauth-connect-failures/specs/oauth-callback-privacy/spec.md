## ADDED Requirements

### Requirement: OAuth connection failures have a secret-safe terminal response

Authorization-code exchange and device-code creation using direct or environment-proxy HTTP SHALL translate aiohttp connection errors, interrupted payload errors and timeouts into `OAuthError` with code `transport_error`, status 502 and message `Unable to reach the OAuth provider. Check outbound connectivity and proxy settings, then restart login.` The translation SHALL surround only HTTP I/O. It MUST NOT include exception text, URL, callback query or credential material in responses, persisted errors or emitted diagnostics. It MUST NOT introduce retries or swallow unknown errors, cancellation or process-exit exceptions. Existing provider HTTP errors, proxy denial routing and PKCE/state/expiration validation SHALL remain unchanged.

#### Scenario: Browser exchange cannot connect

- **GIVEN** a valid pending browser flow and synthetic matching state
- **WHEN** the provider connection fails during the callback exchange
- **THEN** `/auth/callback` returns the product Login failed HTML with HTTP 200 and the fixed message
- **AND** the matched flow is durably finalized as error and `/api/oauth/status?flowId=...` reports the same message
- **AND** a concurrent durable success still wins over error finalization
- **AND** listener cleanup does not interrupt another pending browser flow

#### Scenario: Device start cannot connect

- **WHEN** `/api/oauth/start` receives `forceMethod=device` and the provider connection fails
- **THEN** it returns HTTP 502 with exactly `{error:{code:transport_error,message:<fixed message>}}`
- **AND** it creates no flow, account, device slot or poll task
- **AND** an unrelated pending flow remains unchanged

#### Scenario: Existing non-transport outcomes remain distinct

- **WHEN** an OAuth HTTP request succeeds, returns a provider denial or raises an unknown programming exception
- **THEN** its existing outcome remains distinct from `transport_error`
- **AND** cancellation and process-exit exceptions are not converted into ordinary responses
