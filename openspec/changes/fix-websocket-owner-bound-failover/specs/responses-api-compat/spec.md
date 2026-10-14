## ADDED Requirements

### Requirement: Required-owner WebSocket connection failures preserve the upstream error

For a hard required account, direct Responses WebSocket deterministic failover
MUST surface the original upstream status and error payload without owner
exclusion or reselection. It MUST preserve account classification, stream-lease
cleanup and movable pre-visible failover eligibility. It MUST NOT change
authentication-refresh or confirmed pre-dispatch transport branches.

#### Scenario: Retryable 403 with a required replay owner

- **GIVEN** a WebSocket request requires account A for replay
- **WHEN** opening A returns a 403 carrying a retryable upstream error
- **THEN** the client receives that original 403 error
- **AND** no second account selection or upstream open occurs

#### Scenario: Movable retryable 403

- **GIVEN** a WebSocket request has no hard account requirement
- **WHEN** opening account A returns a retryable 403 and account B is eligible
- **THEN** the proxy retains its existing failover to B

#### Scenario: Plain forbidden 403

- **GIVEN** a WebSocket handshake returns an ordinary forbidden 403
- **WHEN** the proxy classifies the failure as non-retryable
- **THEN** the original 403 remains terminal for both required-owner and movable requests

#### Scenario: Required-owner quota failure

- **GIVEN** a WebSocket request requires its previous-response owner
- **WHEN** that owner returns a classified quota failure before connection
- **THEN** the client receives the original quota status and error payload
- **AND** the account quota classification is retained without selecting another account
