# API Key Authentication

API key auth is **disabled by default**. In that mode, only local requests to the protected proxy routes can
proceed without a key; non-local requests are rejected until proxy authentication is configured. Enable it in
**Settings → API Key Auth** on the dashboard when clients connect remotely or through Docker, VM, or container
networking that appears non-local to the service.

When enabled, clients must pass a valid API key as a Bearer token:

```
Authorization: Bearer sk-clb-...
```

## Protected routes

The protected proxy routes covered by this setting are:

- `/v1/*` (except `/v1/usage`, which always requires a valid key)
- `/backend-api/codex/*`
- `/backend-api/transcribe`

## Creating keys

Dashboard → API Keys → Create. The full key is shown **only once** at creation. Keys support optional expiration, model restrictions, and rate limits (tokens / cost per day / week / month).

Keys can also be scoped to specific accounts, so a key draws quota only from the accounts assigned to it:

![API keys with assigned accounts](screenshots/apis-assigned-accounts.jpg)

## Reset-credit redemption permission

New keys cannot redeem reset credits unless an operator enables **Allow reset-credit redemption** in the create or edit dialog. This permission does not change inference access, usage visibility, quota privacy, account assignments, revocation or expiry. A key name such as `monitor` has no authorization meaning.

**Compatibility warning: existing monitoring keys are NOT automatically hardened.** The migration backfills every existing key to `true` to preserve its current behavior. A future rollout must explicitly update monitoring keys to `false`. This source change makes no live permission updates.

`GET /v1/reset-credit` still lists cached credits within the key's eligible account pool. `POST /v1/reset-credit` returns HTTP 403 with OpenAI error code `reset_credit_redeem_forbidden` when the permission is false, before redemption work starts. Both routes require a valid bearer key even when global proxy authentication is disabled.

The dashboard API field is `allowResetCreditRedeem`. Create defaults to `false`; PATCH omission preserves the current value. Only JSON `true` and `false` are valid. Explicit null, strings, numeric values, arrays and objects return the existing 422 dashboard validation response. Unknown fields retain the existing schema's ignore behavior and never grant permission. Key creation, listing and regeneration responses include the persisted boolean; regeneration preserves it. There is no separate API-key import/export endpoint in this source. Raw database inserts that omit the field use the database default `false`.

Downgrading removes the permission. Re-upgrading backfills all then-existing keys to `true` again, so an operator must reapply any hardening after that roundtrip.

## Reasoning effort policies

A key can either enforce one reasoning effort or allow a selected non-empty set of client-requested efforts.
Leave the allowed-efforts selection empty to keep the existing unrestricted behavior. A request that explicitly
sets an effort outside its key's allowlist receives a `403 reasoning_effort_not_allowed` response. Requests that
omit a reasoning effort continue to use the model or upstream default.

The policy evaluates the effort selected by the client, including supported model aliases such as `-xhigh`.
Each configured effort is distinct: allowing `high` does not allow `xhigh`, and allowing `max` does not allow
`ultra`. The proxy still rewrites an allowed `ultra` request to the upstream wire value `max`.

![API key reasoning-effort policy](screenshots/apis-reasoning-efforts.jpg)

For wiring keys into each client, see [Client Setup](client-setup.md).

---

*Spec: [api-keys](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/api-keys)*
