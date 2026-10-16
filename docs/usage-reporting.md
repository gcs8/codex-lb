# Usage Reporting

codex-lb records the token counts reported in the terminal Responses API event. It does not retokenize prompts or responses, and it does not estimate hidden reasoning usage.

For direct Codex traffic over HTTP or WebSocket, the reported buckets have these relationships:

- `input_tokens` includes the full input count; cached input is reported as a subset.
- `output_tokens` includes all generated output, including reasoning tokens.
- `reasoning_tokens` is the reported reasoning subset of `output_tokens`.
- Total tokens are `input_tokens + output_tokens`. Do not add cached input or reasoning tokens again.

## Dashboard

The **Request Logs** token cell shows total tokens, with reported cached-input and reasoning counts underneath. Open **Details** to see the exact reported reasoning count and its relationship to output tokens.

The **Reports** page shows the reported reasoning total for the selected date range and filters. Its coverage count states how many requests supplied a reasoning value. The daily breakdown and CSV export include the same reasoning field.

## Missing Usage

A reported zero remains `0`. A missing value remains unknown and appears as `—` in the daily report or is omitted from request details. codex-lb does not turn missing usage into zero.

Reasoning usage may be missing when the upstream terminal event does not include it, when a stream ends before that event arrives, or for older request-log rows. The dashboard does not backfill those rows. Custom OpenAI-compatible model sources do not currently feed reasoning details into this reporting path.

## Pricing and Missing Costs

codex-lb refreshes OpenAI text-token pricing hourly from models.dev. Compatible LiteLLM data supplies missing tier rates and additional models. Price lookups use the in-memory catalog; an upstream outage falls back to the last successful disk cache and bundled pricing snapshot. These amounts use API-equivalent token prices, not ChatGPT subscription credit multipliers.

When a model's price becomes available, retained subscription requests with missing costs are repaired automatically in small batches. Their dashboard, report, account, and API-key usage aggregates are corrected in the same transaction. Existing costs, including zero, and API-key limit counters are preserved. Requests whose raw logs have already been deleted by retention cannot be reconstructed.

The Codex client-version fallback is also retained across restarts. Bundled prices and the stable Codex version are maintained by a daily update workflow that opens a reviewable PR. Operators do not need an extra API key or configuration setting.

*Spec: [upstream-metadata](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/upstream-metadata)*

---

*Spec: [frontend-architecture](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/frontend-architecture)*

## Plan Capacity and Tier Overrides

Subscription quotas are published per month as multiples of the $20 Plus plan
(7,560 credits). codex-lb derives each account's weekly capacity from that
monthly figure: `monthly × 7 / 30`.

| Plan claim | Default tier | Weekly credits | Monthly credits |
| --- | --- | --- | --- |
| `plus`, `business`, `team`, `edu` | 1× | 1,764 | 7,560 |
| `prolite` (Pro 100, Business Premium) | 5× | 8,820 | 37,800 |
| `pro`, `enterprise` (Pro 200) | 10× | 17,640 | 75,600 |

The plan claim cannot tell every tier apart — a grandfathered Pro 200 (20×
through October 29, 2026) and Pro 500 (25×) both report `pro`. Set the real tier
per account on **Accounts → Plan tier**, either as a multiple of the $20 plan or
as a raw monthly credit allowance, optionally with an end date:

- The end date is **inclusive in US Pacific time** (OpenAI's day boundary):
  "through 2026-10-29" ends at `2026-10-30T07:00:00Z`. The UI shows the exact UTC
  instant before saving; the API (`PUT /api/accounts/{id}/quota-tier`) takes it
  directly.
- After the end date the plan default applies again automatically.
- Overrides change capacity everywhere it is used: routing weights, pooled
  usage, the weekly pace card and `/v1/usage` aggregate limits. Percentages
  reported by upstream are never changed.

Rolling back to a build without overrides keeps the columns but ignores them,
so capacity falls back to that build's constants.
