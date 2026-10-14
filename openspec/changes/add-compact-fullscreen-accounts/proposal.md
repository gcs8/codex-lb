## Why

Dashboard operators need a denser account summary and an account-only view without changing account permissions or backend settings. PR #2464 supplies the UI but no OpenSpec change or new regression coverage.

## What Changes

- Add a locally persisted compact account view beside cards and the existing full-detail list.
- Add a URL-driven account-only fullscreen layout with internal scrolling and a reachable exit control.
- Keep localized accessible controls, keyboard account inspection, privacy masking, and existing permissions.

## Impact

- Affected specs: frontend-architecture
- Affected code: dashboard account components, dashboard preferences, App layout, locale strings
- No backend API, migration, environment setting, deployment, or navigation-budget changes.
