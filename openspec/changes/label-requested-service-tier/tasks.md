## 1. Implementation
- [x] 1.1 Pick the label tier from requested vs reported in one helper shared by the table and the detail dialog.
- [x] 1.2 Replace the "Requested {tier}" line with "Upstream reported {tier}" when they differ (en, ko, zh-CN).

## 2. Verification
- [x] 2.1 Update the table regression: label `(high, priority)` plus "Upstream reported default", and the same label in the detail dialog.
- [x] 2.2 Add a regression for an entry without a requested tier keeping `(high, default)` and showing no upstream line.
- [x] 2.3 Run frontend lint, typecheck and the affected tests; validate this change with the CI-pinned OpenSpec.
