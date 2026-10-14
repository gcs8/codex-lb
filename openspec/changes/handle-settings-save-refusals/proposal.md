# Handle settings save refusals

## Why
Settings child controls discard the page's async save promise. The mutation's onError already renders the existing toast and error state, but mutateAsync also rejects. Browserless reproduced an unhandled ApiError for an intercepted PUT 422 on both baseline and PR 2122.

## What changes
- Observe the owned settings-save promise at the shared page handler and equivalent Automations pause handler.
- Preserve mutation feedback, request validation, payload, expectedVersion, conflict refresh and success invalidation.
- Add full Settings component regressions using real mutation/API rejection and remote browser refusal/retry evidence.

## Impact
Only settings-save event ownership changes. No network-client, auth, policy, locale, persistence or deployment change. Raw mutateAsync continues to reject for callers that await its outcome.
