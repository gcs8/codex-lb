# Design

The native HTTP producer emits Head/Chunk/End for HTTP errors instead of SSE
framing them. Python reads the entire body and preserves the original error.
Native WS framing and Lite finalization already compose correctly on this base.
The actual uncovered path is `_handle_stream_error` ->
`_is_account_neutral_request_rejection` -> `record_error` on HTTP 400.

Extend the existing request-neutral predicate with one precise code/message
pair. Its existing status guard continues to exclude non-400 HTTP statuses.
Do not add `unsupported_value` to the global neutral-code set and do not broaden
all invalid-request errors. This avoids suppressing unrelated account failures.
The exact message is deliberately narrow; alternate provider wording remains
under existing classification until independently qualified.

Public-route tests use the pinned Rust Debug helper, synthetic loopback HTTP
and WS peers, and actual service routing. Instrument real health calls with
wrapping spies, never replace native response objects or producer events.
