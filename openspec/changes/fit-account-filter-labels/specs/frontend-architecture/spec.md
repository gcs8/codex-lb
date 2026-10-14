## ADDED Requirements

### Requirement: Accounts selected filter label capacity

The Accounts list SHALL give search, status and sort controls separate full-width rows within its bounded list column. At 1280x800 and 390x844, every selected English sort and status label SHALL fit completely inside its own selected-value container without clipping, truncation, hidden text or horizontal document overflow. All existing translated choices, sorting and filtering behavior, keyboard operation and account identity SHALL remain unchanged.

#### Scenario: Desktop sidebar shows long selected labels
- **WHEN** an operator selects any sort or status option at 1280x800
- **THEN** every rendered selected-label text-range rectangle lies inside its selected-value container
- **AND** the complete filter trigger remains inside the Accounts list column

#### Scenario: Mobile retains full filter labels
- **WHEN** an operator selects any sort or status option at 390x844
- **THEN** every rendered selected-label text-range rectangle lies inside its selected-value container
- **AND** the page has no horizontal document overflow

#### Scenario: Keyboard and filtering retain selection
- **WHEN** an operator selects a sort option with the keyboard and searches or filters accounts
- **THEN** the selected sort remains visible and active
- **AND** every matching credential slot remains independently selectable by its original account identifier
