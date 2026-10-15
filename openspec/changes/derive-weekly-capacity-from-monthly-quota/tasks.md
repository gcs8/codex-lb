## 1. Capacity
- [x] 1.1 Derive weekly plan capacity from monthly quota x tier multiplier x 7/30
- [x] 1.2 Expose monthly-equivalent pool capacity on the weekly pace response
## 2. Dashboard
- [x] 2.1 Show weekly and monthly-equivalent pool capacity on the pace card (en, ko, zh-CN)
## 3. Tier override
- [x] 3.1 Nullable account columns + migration (upgrade, downgrade, idempotent)
- [x] 3.2 Capacity resolution honours the override and its expiry
- [x] 3.3 `PUT /api/accounts/{id}/quota-tier` with validation
- [x] 3.4 Accounts page control: x $20 Plus presets or raw credits / month, optional end date (en, ko, zh-CN)
## 4. Verification
- [x] 4.1 Regression tests for derived capacities and the monthly equivalent
- [x] 4.2 Strict OpenSpec validation
