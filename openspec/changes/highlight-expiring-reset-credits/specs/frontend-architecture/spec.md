## ADDED Requirements

### Requirement: Accounts list reset-credit expiry warning

The Accounts list SHALL mark an available-reset-credit badge when its nearest known expiry is in the future and at most 72 hours away. The warning SHALL have a localized accessible description, follow both reset-credit count and expiry badge visibility, and disappear when credits are zero, expiry is absent or invalid, or the expiry has passed. While the list remains mounted, the warning SHALL update with the passage of time at least once per minute and when account data changes.

The warning SHALL compare absolute instants, including explicit timezone offsets, using elapsed hours rather than local calendar days. Enabling either visibility control SHALL evaluate the current time without waiting for the next timer tick. Existing exact local expiry timestamps in the usage panel and redemption confirmation SHALL remain unchanged.

#### Scenario: Credit enters the warning window
- **GIVEN** an account has positive available credits and an expiry more than 72 hours away
- **WHEN** its expiry becomes at most 72 hours away
- **THEN** the badge gains the warning within one minute without a page reload

#### Scenario: Expired or hidden credit
- **WHEN** the expiry passes, the count becomes zero, or reset-credit count or expiry badges are disabled
- **THEN** the warning is absent

#### Scenario: Offset timestamp at the exact boundary
- **GIVEN** the current instant is `2026-10-04T12:00:00Z`
- **WHEN** an account with positive credits expires at `2026-10-07T08:00:00-04:00`
- **THEN** the warning is shown at exactly 72 elapsed hours
- **AND** an expiry one millisecond later does not show the warning

#### Scenario: Re-enable visibility after expiry
- **GIVEN** a visibility control is disabled while the account's nearest credit expires
- **WHEN** the operator re-enables the control
- **THEN** the warning remains absent without waiting for a timer tick
