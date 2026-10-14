## MODIFIED Requirements

### Requirement: Image generation is implemented as a Responses tool adapter

The system SHALL implement `/v1/images/generations` and `/v1/images/edits` by issuing an internal `/v1/responses` request whose `tools` array includes `{"type": "image_generation", ...}` and whose `input` is constructed to deterministically force a single `image_generation` tool call. The system MUST route that internal request through the existing proxy account-selection, sticky session, retry, and authentication pipeline. The system MUST NOT introduce a new `chatgpt-token → openai-api-key` token-exchange path solely to support these endpoints.

The internal request MUST use dedicated ordered Images host selection independent from default account probes. The public `gpt-image-*` model MUST remain in the image tool configuration and MUST NOT be replaced by the internal host model.

#### Scenario: Internal Responses call uses existing routing

- **WHEN** any `/v1/images/*` request is processed
- **THEN** account selection, sticky-session affinity, API-key validation, and request budgeting use the same code paths as `/v1/responses`

#### Scenario: Multipart edits become input_image content

- **WHEN** an edit request includes `image` and optional `mask` multipart parts
- **THEN** each binary part is encoded as a `data:` URL and inserted as `input_image` content in the internal Responses input

#### Scenario: Images routes prefer an image-compatible host

- **GIVEN** `gpt-5.6-sol` is visible and unsuppressed in the model registry
- **WHEN** a client sends a valid generation or edit request
- **THEN** the internal Responses request uses `gpt-5.6-sol` as its host model
- **AND** the image tool retains the publicly requested `gpt-image-*` model

### Requirement: Internal host selection

Images generation and edit routes MUST select the first candidate with nonempty registry plan visibility and no suppression, ordered as `gpt-5.6-sol`, `gpt-6-astra`, `gpt-5.6-luna`, `gpt-5.5`. If none qualifies, they MUST use `gpt-5.6-sol`. Public image model IDs MUST remain unchanged. Registry visibility MUST NOT bypass account entitlement, trusted-access checks, account ownership, or existing downstream errors, and MUST NOT introduce host retries. Default account probes MUST retain their independent Luna-then-5.5 selection.

#### Scenario: Cold registry prefers the current host

- **WHEN** the registry uses the bootstrap catalog
- **THEN** the internal model is `gpt-5.6-sol`

#### Scenario: Preferred model unavailable in registry

- **WHEN** only `gpt-5.5` has registry plan visibility without suppression
- **THEN** the internal model is `gpt-5.5`

#### Scenario: No candidate qualifies

- **WHEN** no candidate has plan visibility without suppression
- **THEN** the selected host is `gpt-5.6-sol` and existing downstream error handling applies

#### Scenario: Suppressed preferred host is not selected

- **WHEN** `gpt-5.6-sol` is suppressed and `gpt-6-astra` has plan visibility without suppression
- **THEN** the internal model is `gpt-6-astra`

#### Scenario: Images host selection does not change account probes

- **WHEN** Images host preference changes
- **THEN** the default account-probe host order remains unchanged
