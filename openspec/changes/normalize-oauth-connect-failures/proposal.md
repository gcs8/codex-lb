# Normalize direct OAuth connection failures

## Why

Refs #2601. The aiohttp authorization-code exchange and device-code start allow connector and timeout exceptions to bypass the existing OAuthError route contracts. Public regression reproduces default callback errors and dashboard catch-all errors with synthetic state only.

## What changes

Normalize expected direct HTTP connection, timeout and interrupted-payload failures at the OAuth HTTP I/O boundary. Use one fixed actionable message without exception text. Preserve provider errors, route policy, callback state validation, cancellation and request replay policy.

## Impact

Only authorization-code exchange and device-code creation use the new direct boundary. Device polling remains unchanged. No retries, settings, routing changes or new logging.
