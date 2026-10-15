## Why

Issue #2128 reports that the `/v1` base URL cannot dispatch standalone Codex search. The current canonical route and case-insensitive control media-type repair already exist, but the V1 alias is absent.

## What changes

- Register `POST /v1/alpha/search` on the existing authenticated standalone control handler.
- Preserve opaque request/response bytes, query multiplicity, API-key and account policies, native media-type cardinality, and existing error normalization.
- Exercise real native HTTP against synthetic loopback upstreams. This proves transport forwarding, not provider search availability or Codex client result-schema acceptance.

## Impact

Only the Python route registration changes. No Rust, native adapter, provider, release, deployment, settings or compression-policy changes. Trailing-slash aliases and non-POST search methods are not added.
