## ADDED Requirements

### Requirement: Reset-credit redemption requires explicit key permission

Existing required-capability transport refusal SHALL retain precedence and its HTTP 400 error contract. The system SHALL persist `allow_reset_credit_redeem` independently of usage visibility and inference policy. New keys SHALL default to false. The dashboard create and edit dialogs SHALL expose the permission. Key responses SHALL serialize it as `allowResetCreditRedeem`. Existing keys SHALL be backfilled true to preserve their previous access, regardless of name. Existing monitoring keys are NOT automatically hardened and require an explicit operator permission update in a future rollout.

#### Scenario: Default key cannot spend credits
- **WHEN** a valid key without permission calls `POST /v1/reset-credit`
- **THEN** the response is HTTP 403 in the OpenAI error envelope
- **AND** no account lookup, claim, credential refresh, upstream fetch or consume, ledger, usage refresh or reset-credit cache mutation occurs

#### Scenario: Granted key retains redemption behavior
- **WHEN** a valid key with permission redeems an available credit within its eligible pool
- **THEN** existing redemption, account-scope, error and invalidation contracts apply
- **AND** revoked or expired keys remain refused

#### Scenario: Reading is independent
- **WHEN** a key without redemption permission reads `GET /v1/reset-credit`
- **THEN** the existing eligible-pool listing and quota-privacy policy remain unchanged

#### Scenario: Strict permission updates preserve omitted state
- **WHEN** a create or update includes the permission
- **THEN** only JSON true or false is accepted, and null, strings, numbers, arrays and objects are rejected using the existing dashboard validation status and envelope
- **AND** omission on update preserves current state
- **AND** unknown fields follow the existing dashboard schema contract and are ignored, never interpreted as permission

#### Scenario: Compatibility migration preserves old keys
- **WHEN** an existing database upgrades
- **THEN** all pre-existing keys receive true and future inserts default false
- **AND** original migration files remain unchanged with one new revision on the actual head
