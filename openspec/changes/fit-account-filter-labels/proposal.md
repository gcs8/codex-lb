## Why

The bounded Accounts sidebar gives each desktop filter only 155px at a 1280x800 viewport. Its 105px selected-value container clips existing and newly added sort labels. Mobile already provides a full-width filter row.

## What Changes

- Keep search, status and sort filters in separate full-width rows in the local Accounts list.
- Require complete selected filter labels at 1280x800 and 390x844, measured in Chromium against their own value containers.
- Preserve all choices, translations, sorting, filtering, keyboard interaction and credential selection.

## Impact

- Affected capability: frontend-architecture.
- No shared Select styles, navigation, settings, dependencies, backend contracts or simplicity budgets change.
