# Restore shared confirmation opener focus

## Why

Controlled triggerless ConfirmDialog closes cancel Radix's previous-element restoration and have no Trigger ref to receive focus. The real reset-credit path leaves BODY focused even when its original opener is connected and enabled. This is an inherited shared defect, not a PR2464-owned regression.

## What changes

- Give ConfirmDialog explicit close-focus ownership using the active opener captured before the dialog's automatic mount focus.
- Restore only the original connected, eligible button, without overriding another open dialog or a newer focus owner.
- Retain Cancel-first autofocus, controlled close callbacks, async busy/refusal behavior and AlertDialog's prevented outside interaction.
- Cover persistent and conditional mounting, nested confirmations, detached/ineligible openers and shared sibling flows with existing test dependencies.

## Impact

Frontend shared confirmation only. No labels, ARIA IDs, privacy, API, authorization, backend, dependency or PR2464 source changes. PR2464 fullscreen acceptance requires a separate exact composed candidate and remains parent-owned.
