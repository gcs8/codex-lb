## ADDED Requirements

### Requirement: Dashboard compact account mode

The Dashboard Accounts section SHALL offer a compact mode in addition to cards and the existing full-detail list. Cards SHALL remain the default. Compact mode SHALL persist in the existing local account-view preference and SHALL render every account from the same overview collection with identity, status, plan and numeric quota remaining. Its identity button SHALL open the existing account detail flow by keyboard or pointer. Privacy masking and account permissions SHALL remain unchanged. Full-detail list actions and quota meters SHALL remain available in list mode.

#### Scenario: Compact mode persists and retains all accounts

- **WHEN** an operator selects compact mode and later returns in the same browser profile
- **THEN** compact mode is restored
- **AND** every overview account is present exactly once
- **AND** account identity, status, plan and available quota percentages are rendered

#### Scenario: Keyboard account inspection

- **WHEN** an operator focuses an account identity button in compact mode and presses Enter
- **THEN** the existing account detail action is invoked for that account
- **AND** the control has a localized accessible name describing account inspection

### Requirement: Keyboard dashboard account-view selection

The account view selector SHALL expose a localized radio group with cards, list and compact choices. Arrow keys SHALL move focus and selection between adjacent options with wraparound, and only the selected option SHALL be in the group's tab order. The separate fullscreen toggle SHALL expose its pressed state and a localized name for entering or exiting fullscreen.

#### Scenario: Arrow selection wraps

- **WHEN** the compact radio is focused and the operator presses ArrowRight
- **THEN** card mode is selected and the card radio receives focus
- **AND** Tab reaches the fullscreen toggle without visiting unselected radios

### Requirement: Dashboard account-only fullscreen layout

The dashboard SHALL enable account-only fullscreen when the `accountsFullscreen` query parameter equals `1`. It SHALL preserve other query parameters when toggling fullscreen, retain the application header, hide the overview and request-log surfaces, and provide a keyboard-reachable exit toggle. Account content SHALL scroll internally in both axes when needed without losing accounts or expanding the document horizontally.

#### Scenario: Fullscreen toggles without discarding dashboard context

- **WHEN** an operator enables fullscreen on a dashboard URL containing other query parameters
- **THEN** those parameters remain and `accountsFullscreen=1` is added
- **AND** overview metrics and request logs are hidden while account content remains
- **WHEN** the operator activates the exit toggle
- **THEN** only `accountsFullscreen` is removed and the normal dashboard returns

#### Scenario: Long full-detail list remains reachable

- **WHEN** fullscreen list content exceeds the viewport height or width
- **THEN** the account viewport supports keyboard scrolling to its content
- **AND** the exit toggle remains visible

### Requirement: Dashboard account sort reset

Dashboard full-detail and compact list headers SHALL cycle from ascending to descending to unsorted when repeatedly activated. A selected full-detail-only sort SHALL remain stored but SHALL not sort compact mode where that header is absent. Compact columns SHALL retain account membership across sorts and sort within each column.

#### Scenario: Third activation restores source order

- **WHEN** an operator activates the same account header three times from unsorted state
- **THEN** source overview order is restored
- **AND** the stored list sort becomes null
