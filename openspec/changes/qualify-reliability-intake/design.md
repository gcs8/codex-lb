## Scope and preservation

Port selected behavior and regressions from upstream #2681 at9b8d44a452f3c69e31a712d69c0d0e41c9741062, #2632 at4d126e42283155de7cd711c8a7066f48ed726a04 and #2630 at1fdd428c33a261a9d5950f5d22c0469cc02d4d94 onto integration06a129fa728dea2b51c6e84a3b093c8b0ef607a9. Preserve the already-qualified Cargo/uv closure, raw-peer capture order, forwarded attribution, native-helper close order, drained-background-task gate and database clean-stop helper. Do not import upstream historical verification as fork results.

## Threat model

Forwarded client/scheme headers may describe a different address than the actual peer. Identity requires captured transport provenance and the existing configured proxy trust policy. Missing capture fails closed. A trusted proxy must still authenticate and replace identity/group headers; the patch does not make unsanitized ingress safe.

## Async ownership

Local heartbeat expiry must be distinguishable from a source failure, including settlement at the expiry boundary. HTTP close work remains owned after its bounded wait and late errors are consumed. Caller cancellation remains observable. This is neither a total shutdown deadline nor guaranteed immediate transport termination.

## Deployment boundary

Read effective ingress/trust settings without modifying them. Future rollout must preserve authentication behavior for the actual proxy peer and pass separate immutable-image/data/rollback/runtime gates. No deployment approval is inferred.
