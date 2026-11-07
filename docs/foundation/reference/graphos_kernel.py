"""Executable specification of a few GraphOS invariants, not a production runtime."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


class Rejected(ValueError):
    """A transition would violate the reference model's contract."""


def digest(value: Any) -> str:
    """JSON input identity. Production systems must define canonicalization/versioning."""
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Lease:
    task_id: str
    revision: int
    epoch: int
    worker: str
    input_signature: str
    expires_at: int
    reserved_credits: int


@dataclass(frozen=True)
class Evidence:
    artifact_hash: str
    input_signature: str
    test_revision: str
    verifier: str
    passed: bool


@dataclass
class _Task:
    task_id: str
    input_hash: str
    dependencies: tuple[str, ...]
    test_revision: str
    max_attempts: int
    revision: int = 1
    epoch: int = 0
    attempts: int = 0
    state: str = "PENDING"
    lease: Lease | None = None
    artifact_hash: str | None = None
    producer: str | None = None
    input_signature: str | None = None
    evidence: Evidence | None = None


class Kernel:
    """Single-threaded in-memory model; every public mutation is an atomic assumption.

    Credits are integer maximum charges. Expired or invalidated work consumes its
    entire reservation conservatively because its actual spend is unknown.
    """

    def __init__(self, budget: int):
        if type(budget) is not int or budget < 0:
            raise Rejected("budget must be nonnegative integer credits")
        self.budget = budget
        self.spent = 0
        self._tasks: dict[str, _Task] = {}
        self._objects: dict[str, bytes] = {}
        self.events: list[dict[str, Any]] = []

    @property
    def reserved(self) -> int:
        return sum(t.lease.reserved_credits for t in self._tasks.values() if t.lease)

    def _event(self, kind: str, **data: Any) -> None:
        self.events.append({"sequence": len(self.events) + 1, "kind": kind, **data})

    def add_task(self, task_id: str, inputs: Any, *, dependencies: tuple[str, ...] = (),
                 test_revision: str = "tests-v1", max_attempts: int = 2) -> None:
        if not task_id or task_id in self._tasks or not test_revision:
            raise Rejected("task identity and test revision must be valid and unique")
        if type(max_attempts) is not int or max_attempts < 1:
            raise Rejected("max_attempts must be positive")
        if len(set(dependencies)) != len(dependencies):
            raise Rejected("duplicate dependency")
        if any(d not in self._tasks for d in dependencies):
            raise Rejected("dependencies must already exist; this construction guarantees a DAG")
        self._tasks[task_id] = _Task(task_id, digest(inputs), tuple(dependencies),
                                    test_revision, max_attempts)
        self._event("task_added", task_id=task_id)

    def _task(self, task_id: str) -> _Task:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise Rejected("unknown task") from exc

    def _dependencies_ready(self, task: _Task) -> bool:
        return all(self._tasks[d].state == "VERIFIED" for d in task.dependencies)

    def _signature(self, task: _Task) -> str:
        parents = [{"id": d, "revision": self._tasks[d].revision,
                    "artifact": self._tasks[d].artifact_hash,
                    "tests": self._tasks[d].test_revision}
                   for d in task.dependencies]
        return digest({"input": task.input_hash, "revision": task.revision,
                       "dependencies": parents})

    def _forfeit(self, task: _Task) -> None:
        if task.lease:
            self.spent += task.lease.reserved_credits
            task.lease = None

    def claim(self, task_id: str, worker: str, *, now: int, ttl: int,
              max_credits: int) -> Lease:
        task = self._task(task_id)
        if type(now) is not int or now < 0:
            raise Rejected("time must be nonnegative integer ticks")
        if not worker or type(ttl) is not int or ttl <= 0:
            raise Rejected("worker and positive lease duration required")
        if type(max_credits) is not int or max_credits < 0:
            raise Rejected("reservation must be nonnegative integer credits")
        if task.state == "RUNNING" and task.lease and now >= task.lease.expires_at:
            self._forfeit(task)
            task.state = "PENDING"
            self._event("lease_expired", task_id=task_id, epoch=task.epoch)
        if task.state != "PENDING" or not self._dependencies_ready(task):
            raise Rejected("task is not runnable")
        if task.attempts >= task.max_attempts:
            task.state = "EXHAUSTED"
            raise Rejected("attempt limit reached")
        if self.spent + self.reserved + max_credits > self.budget:
            raise Rejected("insufficient unreserved credits")
        task.epoch += 1
        task.attempts += 1
        task.lease = Lease(task_id, task.revision, task.epoch, worker,
                           self._signature(task), now + ttl, max_credits)
        task.state = "RUNNING"
        self._event("task_claimed", task_id=task_id, epoch=task.epoch,
                    worker=worker, reserved=max_credits)
        return task.lease

    def _active(self, lease: Lease, now: int, actual_credits: int) -> _Task:
        task = self._task(lease.task_id)
        if type(now) is not int or now < 0:
            raise Rejected("time must be nonnegative integer ticks")
        if task.state != "RUNNING" or task.lease != lease or now >= lease.expires_at:
            raise Rejected("stale, expired, or superseded lease")
        if lease.input_signature != self._signature(task):
            raise Rejected("input revision changed")
        if type(actual_credits) is not int or not 0 <= actual_credits <= lease.reserved_credits:
            raise Rejected("actual charge exceeds reservation or is invalid")
        return task

    def _settle(self, task: _Task, actual_credits: int) -> None:
        self.spent += actual_credits
        task.lease = None

    def produce(self, lease: Lease, artifact: bytes, *, now: int,
                actual_credits: int) -> str:
        task = self._active(lease, now, actual_credits)
        if not isinstance(artifact, bytes):
            raise Rejected("artifact must be immutable bytes")
        content_hash = sha256(artifact).hexdigest()
        self._objects[content_hash] = artifact
        task.artifact_hash = content_hash
        task.producer = lease.worker
        task.input_signature = lease.input_signature
        task.evidence = None
        self._settle(task, actual_credits)
        task.state = "PRODUCED"
        self._event("artifact_produced", task_id=task.task_id, artifact_hash=content_hash)
        return content_hash

    def fail(self, lease: Lease, *, now: int, actual_credits: int) -> None:
        task = self._active(lease, now, actual_credits)
        self._settle(task, actual_credits)
        task.state = "EXHAUSTED" if task.attempts >= task.max_attempts else "PENDING"
        self._event("attempt_failed", task_id=task.task_id, epoch=task.epoch)

    def verify(self, task_id: str, evidence: Evidence) -> None:
        task = self._task(task_id)
        if type(evidence.passed) is not bool:
            raise Rejected("verification outcome must be a boolean")
        if task.state != "PRODUCED":
            raise Rejected("only a produced artifact can receive evidence")
        if not evidence.verifier or evidence.verifier == task.producer:
            raise Rejected("producer cannot verify its own output")
        if (evidence.artifact_hash != task.artifact_hash or
                evidence.input_signature != task.input_signature or
                evidence.test_revision != task.test_revision):
            raise Rejected("evidence does not match this artifact/input/test revision")
        task.evidence = evidence
        task.state = "VERIFIED" if evidence.passed else "REJECTED"
        self._event("artifact_verified" if evidence.passed else "artifact_rejected",
                    task_id=task_id, verifier=evidence.verifier)

    def retry_rejected(self, task_id: str) -> None:
        """Targeted repair keeps the same attempt counter; no unlimited repair loop."""
        task = self._task(task_id)
        if task.state != "REJECTED":
            raise Rejected("task has not been rejected by verification")
        task.state = "EXHAUSTED" if task.attempts >= task.max_attempts else "PENDING"
        task.artifact_hash = task.producer = task.input_signature = task.evidence = None
        self._event("repair_requested", task_id=task_id)

    def _invalidate(self, root: str, *, keep_root_artifact: bool = False) -> None:
        affected = {root}
        # Tasks are inserted in dependency order, so a single forward pass suffices.
        for task in self._tasks.values():
            if any(d in affected for d in task.dependencies):
                affected.add(task.task_id)
            if task.task_id not in affected:
                continue
            self._forfeit(task)
            task.epoch += 1  # fence off every old completion, including in-flight work
            task.revision += 1
            task.attempts = 0
            task.evidence = None
            if task.task_id == root and keep_root_artifact and task.artifact_hash:
                task.input_signature = self._signature(task)
                task.state = "PRODUCED"
            else:
                task.artifact_hash = task.producer = task.input_signature = None
                task.state = "PENDING"
            self._event("task_invalidated", task_id=task.task_id, revision=task.revision)

    def revise_inputs(self, task_id: str, inputs: Any) -> None:
        task = self._task(task_id)
        next_hash = digest(inputs)  # validate before mutating
        task.input_hash = next_hash
        self._invalidate(task_id)

    def revise_tests(self, task_id: str, test_revision: str) -> None:
        task = self._task(task_id)
        if not test_revision or task.test_revision == test_revision:
            raise Rejected("a distinct nonempty test revision is required")
        task.test_revision = test_revision
        self._invalidate(task_id, keep_root_artifact=True)

    def snapshot(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        state = task.state
        if state == "PENDING" and self._dependencies_ready(task):
            state = "READY"
        return {"task_id": task_id, "state": state, "revision": task.revision,
                "epoch": task.epoch, "attempts": task.attempts,
                "artifact_hash": task.artifact_hash,
                "input_signature": task.input_signature, "test_revision": task.test_revision}


@dataclass
class _Effect:
    payload_hash: str
    receiver_deduplicates: bool
    state: str = "PREPARED"
    attempts: int = 0


@dataclass(frozen=True)
class DispatchToken:
    key: str
    attempt: int
    payload_hash: str


class EffectLedger:
    """Models an external-effect protocol; never calls an external service.

    Receiver deduplication and reconciliation reports are supplied assumptions,
    not capabilities that this local ledger can enforce or independently prove.
    """

    def __init__(self):
        self._effects: dict[str, _Effect] = {}

    def prepare(self, key: str, payload: Any, *, receiver_deduplicates: bool) -> None:
        if not key:
            raise Rejected("operation key required")
        if type(receiver_deduplicates) is not bool:
            raise Rejected("receiver deduplication must be an explicit boolean")
        hashed = digest(payload)
        existing = self._effects.get(key)
        if existing:
            if (existing.payload_hash != hashed or
                    existing.receiver_deduplicates != receiver_deduplicates):
                raise Rejected("operation key reused with different intent")
            return
        self._effects[key] = _Effect(hashed, receiver_deduplicates)

    def begin(self, key: str) -> DispatchToken:
        effect = self._effects[key]
        if effect.state == "UNKNOWN" and not effect.receiver_deduplicates:
            raise Rejected("ambiguous outcome: reconcile before retrying")
        if effect.state not in {"PREPARED", "UNKNOWN"}:
            raise Rejected("operation cannot be sent in this state")
        effect.state = "IN_FLIGHT"
        effect.attempts += 1
        return DispatchToken(key, effect.attempts, effect.payload_hash)

    def _current(self, token: DispatchToken) -> _Effect:
        if not isinstance(token, DispatchToken):
            raise Rejected("a dispatch token is required")
        effect = self._effects.get(token.key)
        if (effect is None or token.attempt != effect.attempts or
                token.payload_hash != effect.payload_hash):
            raise Rejected("stale or mismatched dispatch token")
        return effect

    def timeout(self, token: DispatchToken) -> None:
        effect = self._current(token)
        if effect.state != "IN_FLIGHT":
            raise Rejected("no operation is in flight")
        effect.state = "UNKNOWN"

    def confirm(self, token: DispatchToken) -> None:
        effect = self._current(token)
        if effect.state not in {"IN_FLIGHT", "UNKNOWN"}:
            raise Rejected("no outstanding operation to confirm")
        effect.state = "APPLIED"

    def reconcile(self, token: DispatchToken, outcome: str) -> None:
        """NOT_APPLIED requires authoritative reconciliation, not an absent receipt."""
        effect = self._current(token)
        if effect.state != "UNKNOWN" or outcome not in {"APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            raise Rejected("invalid reconciliation")
        effect.state = "PREPARED" if outcome == "NOT_APPLIED" else outcome

    def snapshot(self, key: str) -> dict[str, Any]:
        effect = self._effects[key]
        return {"key": key, "state": effect.state, "attempts": effect.attempts,
                "payload_hash": effect.payload_hash}


def demo() -> None:
    kernel = Kernel(100)
    kernel.add_task("api", {"requirement": "versioned API contract"})
    kernel.add_task("ui", {"requirement": "consume the API"}, dependencies=("api",))
    first = kernel.claim("api", "builder-a", now=0, ttl=5, max_credits=10)
    replacement = kernel.claim("api", "builder-b", now=5, ttl=5, max_credits=10)
    try:
        kernel.produce(first, b"stale output", now=6, actual_credits=5)
    except Rejected as exc:
        kernel._event("stale_completion_rejected", reason=str(exc))
    artifact = kernel.produce(replacement, b'{"api_version":1}', now=6, actual_credits=6)
    kernel.verify("api", Evidence(artifact, replacement.input_signature,
                                  "tests-v1", "verifier", True))
    ui = kernel.claim("ui", "ui-builder", now=7, ttl=5, max_credits=10)
    kernel.revise_inputs("api", {"requirement": "versioned API contract", "version": 2})
    try:
        kernel.produce(ui, b"obsolete UI", now=8, actual_credits=4)
    except Rejected as exc:
        kernel._event("dependent_completion_rejected", reason=str(exc))
    effects = EffectLedger()
    effects.prepare("release:example:1", {"artifact": artifact}, receiver_deduplicates=False)
    first_dispatch = effects.begin("release:example:1")
    effects.timeout(first_dispatch)
    try:
        effects.begin("release:example:1")
    except Rejected as exc:
        kernel._event("unsafe_effect_retry_rejected", reason=str(exc))
    effects.reconcile(first_dispatch, "NOT_APPLIED")
    second_dispatch = effects.begin("release:example:1")
    effects.timeout(second_dispatch)
    try:
        effects.reconcile(first_dispatch, "NOT_APPLIED")
    except Rejected as exc:
        kernel._event("stale_reconciliation_rejected", reason=str(exc))
    print(json.dumps({"events": kernel.events, "spent": kernel.spent,
                      "reserved": kernel.reserved, "effect": effects.snapshot("release:example:1"),
                      "tasks": [kernel.snapshot(t) for t in ("api", "ui")]}, indent=2))


if __name__ == "__main__":
    demo()
