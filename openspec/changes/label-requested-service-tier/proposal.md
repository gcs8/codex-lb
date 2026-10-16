# Label request logs with the requested tier when upstream reports a different one

## Why
On the ChatGPT subscription backend, the `service_tier` in a Responses result is `default` whether or not Fast was applied. Measured on 2026-10-16 on a Pro account with `gpt-6.1-sol`: `priority` generated about 32% faster than no tier through codex-lb (61.0 vs 46.1 tok/s median) while every response reported `default` (gcs8/codex-lb#3, #34). The recent-requests Model label shows the reported tier, so it reads `(high, default)` for Fast requests and presents an unverified echo as the served tier.

## What changes
- When a request asked for a tier that differs from the tier upstream reported, the Model label in the table and in the request detail dialog shows the **requested** tier, followed by a secondary "Upstream reported {tier}" line in the table.
- Requests without a requested tier, or whose requested tier matches the reported one, render exactly as before.

## Impact
Dashboard presentation only. `request_logs` columns, `/api/request-logs` fields, billable `service_tier`, cost accounting and the `responses-api-compat` logging scenarios are unchanged: the stored value is still what upstream reported.
