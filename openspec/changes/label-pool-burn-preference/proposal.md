# Label the pool burn preference

## Why

Fork issue #23 reports that Appearance still names the old account-equivalent card even though the dashboard now compares projected demand with pool capacity.

## What changes

- Rename the label, description and accessible switch name in en, ko and zh-CN.
- Preserve the existing preference, storage key, default and projection behavior.
- Regress rendered translations and persisted switch interactions.

## Impact

Only Appearance copy changes. No backend, database, quota, routing or runtime configuration changes.
