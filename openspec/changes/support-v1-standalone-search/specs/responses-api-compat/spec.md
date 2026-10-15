## ADDED Requirements

### Requirement: V1 standalone search shares the canonical control handler

The proxy SHALL expose `POST /v1/alpha/search` as an alias of `POST /backend-api/codex/alpha/search` through the same authenticated Codex control handler. Both paths and the existing doubled-prefix canonicalization MUST preserve the standalone search forwarding contract, including opaque body bytes, repeated query parameters, selected account credentials, API-key model/account scopes, session affinity, upstream-route policy and normalized final error status/envelope. This alias MUST NOT add a Responses tool-choice transformation, a local successful-search schema, non-POST search support or trailing-slash search aliases.

#### Scenario: V1 and native search forward the same request

- **GIVEN** a valid proxy API key scoped to an eligible account
- **WHEN** the same standalone search body is posted through the native, doubled-prefix or V1 path
- **THEN** the existing control handler forwards it to `POST /codex/alpha/search`
- **AND** the selected credentials, body bytes and repeated query values retain the canonical contract
- **AND** native HTTP emits exactly one case-insensitive media-type header preserving the inbound media type
- **AND** successful response bytes and status are preserved without local schema rewriting

#### Scenario: Search aliases retain authorization and error handling

- **WHEN** a search request has invalid credentials or no eligible account within its API-key scope
- **THEN** it does not dispatch to an unauthorized upstream account
- **AND** all supported aliases retain the canonical OpenAI error envelope

#### Scenario: Final upstream refusals preserve status and details

- **WHEN** native HTTP delivers a final upstream search refusal through either base URL
- **THEN** the proxy returns the existing normalized OpenAI error envelope and final upstream status
- **AND** no unsupported method or unregistered trailing-slash path enters search forwarding
