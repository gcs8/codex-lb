## Context and decisions

A WebSocket text message is a complete document, not an SSE field. Decode it
once with JSON semantics, or reuse its trusted native interpretation.
Keep the existing HTTP SSE line parser unchanged. Use the existing safe SSE
formatter when relaying a parsed multiline object.

This preserves ordinary event matching, account ownership, reservation
settlement, and error classification. No retry policy or configuration changes
are needed. Example: an indented `{"type":"error","status":400,"error":...}`
must settle the same request as its compact equivalent.

## Boundaries and risks

Malformed/non-object frames still have no classified response identity and are
dropped before entering the parsed-event relay, rather than forwarded as raw SSE.
For native-interpreted objects, check nested float values for finiteness without
re-parsing the message text. Opaque frames use the existing strict JSON callbacks.
Rejected data does not acquire lifecycle ownership; the existing acknowledgement
timeout remains in effect if no valid frame follows.
Existing tests equating multiline WebSocket JSON with a single SSE data line
must change, but actual SSE tests must retain their semantics.
Tests use synthetic errors and baseline route fixtures, not live payloads.
Lite request normalization and inline-image admission are separate changes.

## Fork overlap disposition

PR #2530 at `047550259124a9fa0a785475626759d43ee67578` supplies the
implementation. PR #2519 at `a4bad7db5c680c3515d9048128d687ed6642b493`
addresses the same multiline-frame bug. Do not merge its alternate parser,
bridge implementation, duplicate OpenSpec change, README, or contributor edits.
The retained implementation also rejects malformed/non-object frames and
non-finite numbers, including nested native values.

Port #2519's distinct regression coverage to the retained parser and bridge:

- Property-based object decoding across ASCII/Unicode and compact/pretty JSON,
  plus the existing unusual-text corpus.
- Real pending-request settlement for LF, CRLF, and CR-only JSON, including a
  null error code and the upstream JSON-mode validation message.
- A bounded, non-streaming `/v1/responses` JSON-mode request that returns the
  upstream 400 without retrying or waiting for the idle timeout.

The lifecycle parser-spy and native parity adaptations overlap and remain the
#2530 versions. Original HTTP SSE tests and their assertions are unchanged.
