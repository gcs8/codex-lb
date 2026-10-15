## Scope and authority

The parent transferred only the shared session's downstream receive/poll/handoff lifetime and minimal cleanup to ISSUE1304. C2398's blocked source is not imported. Full-resend projection, replay eligibility, account selection, native transport and the separate issue2388 refusal path remain unchanged.

## Connection-owned ingress

Store at most one downstream `websocket.receive()` task in `proxy_responses_websocket`. Both the ordinary poll and final idle recheck await that same task through `Scheduler.wait`, whose deadline does not cancel its inputs. A completed result is retrieved and the task slot is cleared synchronously, before the existing frame processing path admits it. Do not prefetch another frame while dispatching a received result or processing an older reader-owned replay.

Upstream retirement and account-lease release never cancel, replace or clear this task. An unprepared raw frame therefore cannot be claimed or settled by the retiring reader, and an already consumed ASGI frame survives either ordering of poll deadline and clean upstream close. Prepared and sent requests continue through the existing ownership and guarded-replay paths without new replay policy.

## Final teardown

The shielded scope finalizer cancels and joins any remaining ingress task using the existing bounded task-cancellation helper and tracked deferred cleanup. Retrieve completed exceptions as well as cancellation. Continue existing upstream/request/reservation/lease cleanup even if the receive itself failed. Drain and normal idle closure remain connection teardown and retain their existing deadlines and codes.

## Verification

Retain the four committed public RED assertions and ASGI-dequeue barriers. Extend the scheduler observer to record deadlines from the non-cancelling wait primitive as well as the old wait-for primitive; this observes the same causal poll boundary without replacing production coordination. Use only the qualified unchanged historical native helper and real loopback sockets. Add independent sent-turn replay, lifecycle and ownership/pin checks without changing existing outcomes. Run complete affected modules, repository static gates and pinned strict OpenSpec checks before branch-only publication; parent full acceptance remains separate.
