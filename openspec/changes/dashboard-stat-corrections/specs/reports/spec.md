## ADDED Requirements

### Requirement: Reports count client sessions next to conversations

The reports summary MUST include `total_sessions`, the number of distinct non-blank `session_id` values among the report's filtered, non-warmup requests, alongside `total_conversations`. The dashboard overview metrics MUST include `sessions` computed the same way for the selected timeframe.

#### Scenario: Codex traffic without conversation ids

- **GIVEN** requests in the report range that carry `session_id` values `sess-1`, `sess-1` and `sess-2` and no `conversation_id`
- **WHEN** the reports summary is built
- **THEN** `total_sessions` is `2`
- **AND** `total_conversations` is `0`

### Requirement: Requested tiers are not recorded as served tiers

The system MUST NOT persist `auto` as a request log's `actual_service_tier`; when no served tier is known the field MUST be null.

#### Scenario: Request fails after an early response event

- **WHEN** a request whose only observed tier is `auto` is logged with status `error`
- **THEN** its `actual_service_tier` is null
