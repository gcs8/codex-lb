# oauth-callback-privacy Specification

## Purpose
The loopback OAuth callback server's default access logger recorded the full request target, exposing temporary authorization codes and anti-CSRF state tokens in log sinks. This capability keeps the callback functional while omitting credential-bearing query text from access logs.
## Requirements
### Requirement: OAuth callback query credentials stay out of logs

The loopback OAuth callback server MUST NOT emit authorization codes, state
tokens, or the raw callback query string through its generic access log. It
MUST preserve callback routing and handler responses when access logging is
suppressed.

#### Scenario: Successful callback omits query credentials

- **GIVEN** the real loopback callback server is running
- **WHEN** a client requests `/auth/callback` with authorization-code and state query values
- **THEN** the callback handler response is returned unchanged
- **AND** neither query value is emitted by the callback access logger under
  text or JSON logging configuration

#### Scenario: Access suppression is callback-local

- **WHEN** the loopback OAuth callback server suppresses its access record
- **THEN** global application and proxy access-logging configuration remains unchanged

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
