## ADDED Requirements

### Requirement: Settings event handlers own save refusals
Settings save event handlers SHALL observe rejected shared settings mutation promises without an unhandled rejection. Existing mutation error feedback SHALL remain visible for validation, authorization, conflict, network and unexpected backend errors. A refusal SHALL NOT be presented as a successful save or update persisted settings in the client cache.

#### Scenario: Refused save can be retried
- **WHEN** a Settings control submits a valid draft and PUT /api/settings refuses or fails
- **THEN** existing error feedback remains visible and pending controls become usable again
- **AND** a later successful retry uses the existing payload and expectedVersion rules and success invalidation

#### Scenario: Conflict refresh remains authoritative
- **WHEN** PUT /api/settings refuses with settings_conflict
- **THEN** the existing settings-detail invalidation refreshes the version for a later retry
- **AND** neither the refusal nor observing its promise invents persisted state

#### Scenario: Equivalent shared settings events
- **WHEN** the Automations pause toggle or its inheritance reset receives a shared settings refusal
- **THEN** the owned promise is observed and existing mutation error feedback remains visible

#### Scenario: Validation and access restrictions remain intact
- **WHEN** a draft is invalid, a mutation is pending, or a principal has read-only access
- **THEN** existing disabled-save and control restrictions remain unchanged
