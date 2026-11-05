## ADDED Requirements

### Requirement: Appearance names the pool burn projection

The Appearance settings burn-projection row SHALL name the Pool burn projection and describe projected demand versus pool capacity in English, Korean, and Simplified Chinese. Its switch accessible name SHALL use the same pool terminology. The existing `accountBurnrateEnabled` preference and `codex-lb-account-burnrate-enabled` storage key SHALL remain unchanged.

#### Scenario: Localized pool projection preference

- **WHEN** a user opens Appearance settings in `en`, `ko`, or `zh-CN`
- **THEN** the burn-projection label, description, and switch accessible name refer to the pool rather than account-equivalent demand
- **AND** toggling the switch persists the boolean under `codex-lb-account-burnrate-enabled`
