## ADDED Requirements

### Requirement: OpenAI-compatible single-model retrieval

The service MUST expose `GET /v1/models/{model_id}` returning the OpenAI `model`
object for one model. The `model_id` path segment MUST accept slashes so that model
slugs such as `org/name` resolve. The response body MUST equal the entry that
`GET /v1/models` returns for the same slug and caller, and the route MUST NOT change
its response shape based on the `client_version` query parameter. A model SHALL be
retrievable only when it would be listed by `GET /v1/models` for the same API key,
including API-key model allowlists and model-source assignment. Unknown or
not-visible models MUST return HTTP 404 with an OpenAI error whose `code` is
`model_not_found` and `type` is `invalid_request_error`. The route MUST release any
request reservation on every exit, including the 404 path.

#### Scenario: Visible model returns its list entry

- **WHEN** a client requests `GET /v1/models/gpt-5.2` and that model is listed by `GET /v1/models`
- **THEN** the response is 200 and the body equals the list entry for `gpt-5.2`

#### Scenario: Unknown model

- **WHEN** a client requests a slug that no registry or enabled model source provides
- **THEN** the response is 404 with `error.code` `model_not_found` and `error.type` `invalid_request_error`

#### Scenario: Allowlist excludes the model

- **WHEN** an API key whose `allowed_models` excludes a model requests that model
- **THEN** the response is 404 `model_not_found`
- **AND** a key without that restriction receives 200

#### Scenario: Unassigned model source

- **WHEN** an API key scoped to one model source requests a model that only another source provides
- **THEN** the response is 404 `model_not_found`
- **AND** a model from the assigned source returns 200

#### Scenario: Slug containing a slash

- **WHEN** a client requests `GET /v1/models/org/name` for a visible model whose slug is `org/name`
- **THEN** the response is 200 with `id` equal to `org/name`

#### Scenario: client_version does not change the shape

- **WHEN** a client requests `GET /v1/models/{model_id}?client_version=0.99.0`
- **THEN** the response is the OpenAI `model` object, not the Codex catalog shape

### Requirement: Trailing-slash list requests retain their redirect

The service MUST continue to redirect `GET /v1/models/` to `GET /v1/models`
with HTTP 307, preserving query parameters. The single-model route MUST NOT
treat an empty model ID as an unknown model.

#### Scenario: Trailing-slash list request retains client_version

- **WHEN** a client requests `GET /v1/models/?client_version=0.99.0`
- **THEN** the response is HTTP 307 with the query parameter preserved
- **AND** following the redirect returns the Codex catalog rather than a model-not-found error
