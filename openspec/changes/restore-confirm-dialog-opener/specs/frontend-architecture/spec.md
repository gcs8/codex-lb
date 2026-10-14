## ADDED Requirements

### Requirement: Controlled confirmation close-focus ownership

The shared controlled ConfirmDialog SHALL retain the actual active opener before automatic dialog focus and SHALL restore focus to that same connected, eligible button when Escape, Cancel or a completed action closes it. Restoration MUST NOT focus BODY, a replacement node, an unavailable opener, or a background opener while another open dialog owns focus. An opener inside a remaining parent dialog SHALL be eligible only within that parent's focus ownership. A newer active control outside the closing confirmation MUST NOT lose focus to restoration.

Mounting SHALL preserve Radix AlertDialog's automatic Cancel-first focus. Outside pointer interaction SHALL remain prevented rather than closing the confirmation. Controlled callbacks and actions SHALL retain exactly-once semantics, including disabled confirmation, async busy close refusal, retry and successful completion. Closed confirmations and read-only controls SHALL NOT move focus or invoke mutations.

#### Scenario: Conditional reset confirmation closes

- **GIVEN** a native activation of a reset-credit button opens a conditionally mounted confirmation
- **WHEN** the operator closes with Escape or Cancel, or redemption completes successfully
- **THEN** the original connected eligible button automatically receives focus before any tester Tab or focus operation
- **AND** Cancel was automatically focused on mount

#### Scenario: Opener is no longer eligible

- **GIVEN** the opener was detached, disabled, hidden or made inert while the confirmation was open
- **WHEN** the confirmation closes
- **THEN** restoration does not focus it, search for a replacement or explicitly focus BODY

#### Scenario: Nested confirmation preserves modal ownership

- **GIVEN** a confirmation opened from a button in another dialog
- **WHEN** the inner confirmation closes and its parent remains open
- **THEN** focus returns to the original eligible button inside the parent
- **AND** a separate newly opened dialog or newer active control is not overridden

#### Scenario: Busy or refused reset remains open

- **GIVEN** redemption is pending or has been refused
- **WHEN** a dismissal is refused by the caller or the action remains open for retry
- **THEN** close-focus restoration does not run and confirmation behavior is unchanged
