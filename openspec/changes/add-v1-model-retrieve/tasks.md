## 1. Implementation

- [x] 1.1 Extract the visible-model item building from `_build_models_response_body` into a shared helper.
- [x] 1.2 Add `GET /v1/models/{model_id:path}` on the `/v1` router, releasing the request reservation on every exit.
- [x] 1.3 Preserve the trailing-slash list redirect before the greedy model-ID route.

## 2. Verification

- [x] 2.1 Add integration tests for the list-entry match, unknown slug, allowlist exclusion, source assignment, and slash-containing slugs.
- [x] 2.2 Run the model catalog and route inventory integration tests, `make lint`, `ty check`, and strict OpenSpec validation.
- [x] 2.3 Add trailing-slash list redirect regressions with and without `client_version`.
