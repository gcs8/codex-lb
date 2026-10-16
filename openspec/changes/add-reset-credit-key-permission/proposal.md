# Per-key reset-credit permission

## Why
Usage readers can currently spend irreversible reset credits. A persisted opt-in separates redemption from reads without inferring authority from names.

## What changes
Add a default-false boolean, strict API handling, dashboard control, and a single additive migration. Backfill existing keys true for compatibility. Existing monitoring keys are NOT automatically hardened. Operators must explicitly disable their permission in a future rollout. No live updates are authorized.

## Impact
API-key persistence, serialization, public reset-credit POST, dashboard dialogs and docs. GET, inference, usage sections, assignments, privacy, CSRF and step-up are unchanged.
