GraphOS proposed portable contracts, version 0.1.0

These files are a design artifact, not an integration with the existing GraphOS
repository. No live model calls, remote actions, or deployments are performed.

protocol.schema.json uses JSON Schema draft 2020-12. Its root oneOf selects one
of TaskSpec, TaskResult, VerificationRecord, EffectIntent, or MessageEnvelope
through the kind field. Each record rejects unknown properties. Use a validator
that supports draft 2020-12 and enable date-time and URI format checking.

example-task.json and example-result.json illustrate matching bindings. Their
hashes, timestamps, costs and URNs are synthetic fixtures, not actual evidence.
The sorting task is illustrative and was not implemented or run. A submitted
result is not an accepted result. Required capabilities are requests, not grants.
An EffectIntent is a proposal, even when its execution_mode is live.

Hash conventions to implement:
- content_hash: SHA-256 of the exact bytes retrieved from the artifact store.
- input_manifest_hash: SHA-256 of a canonical manifest of immutable inputs.
- spec_hash: SHA-256 of the canonical accepted requirement specification, not
  this whole TaskSpec record (which would contain its own hash).
- policy_hash: SHA-256 of the canonical policy document applied to this task.
- candidate_manifest_hash: SHA-256 of a canonical manifest of candidate output
  artifacts, bound to the result being verified.
- suite_hash and environment_hash: exact suite and environment manifest digests.
- payload_hash: exact payload bytes digest; must match payload.content_hash.
- body_hash: digest of the exact stored message-body bytes, not the envelope.
For JSON manifests choose and enforce one canonicalization, such as RFC 8785;
never assume that ordinary JSON serialization is canonical. Large payloads and
logs stay outside messages and are referenced by immutable artifact identifiers.

JSON Schema CANNOT enforce cross-record invariants, authority, state ordering,
or trustworthy evidence. A runtime must separately enforce at least:
- authenticated identities and scoped capability grants; a sender_id is no proof;
- current lease/fencing epoch and expected state version on every relevant write;
- reference existence, matching project/run/task, and identical version bindings;
- recomputed hashes and immutable content; a valid digest string proves nothing;
- verifier independence from producers and absence of self-acceptance;
- complete criterion coverage and consistency of overall/individual outcomes;
- current evidence for the exact candidate, suite, policy and input revisions;
- revocation/invalidation when requirements, policy or artifacts change;
- stable operation_key across attempts and rejection of payload changes per key;
- atomic budget reservations, cumulative spend, and bounded repair/attempt counts;
- deduplication, causal ordering, legal state transitions and expiry/deadlines;
- receipt reconciliation after ambiguous external outcomes before unsafe retries;
- access control, URI allowlists, size limits, and treating retrieved bytes as data.

MessageEnvelope references a body by immutable record ID and hash. The five main
record types are defined here. Bodies for acknowledgements, status events,
clarifications and plan patches need separate schemas before production use.
No acknowledgement, authorization, release or effect-receipt schema is supplied;
these are additional contracts a complete implementation must define.

Validation performed for this delivery: JSON parsing of all three JSON files;
Draft202012Validator.check_schema; validation of both examples with FormatChecker;
negative checks rejecting unknown top-level properties and a TaskResult with
status "accepted". The existing Python jsonschema package was used; no packages
were installed. No live integration or effect execution was tested.
Do not infer runtime guarantees or production readiness from JSON validation.
