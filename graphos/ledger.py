"""PostgreSQL control-plane ledger; workers never own acceptance or effect truth.

Every mutation of an existing run holds its row lock. Lease tokens are stored as
digests, and server time determines expiry. Connections are intentionally short
lived: no correctness depends on one process, connection, or in-memory object.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class Conflict(ValueError):
    """The requested transition, binding, or input is not valid."""


class ReceiptAuthorizationError(Conflict):
    """A narrow receipt capability does not authorize this capture."""


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise Conflict("value must be finite JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _digest(value: Any) -> str:
    if isinstance(value, str) and value.startswith("sha256:"):
        value = value[7:]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise Conflict("expected lowercase SHA-256 digest")
    return value


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = 10**15) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise Conflict(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _text(value: Any, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Conflict(f"invalid {name}")
    if any(ord(char) < 32 for char in value):
        raise Conflict(f"control characters are forbidden in {name}")
    return value


def _safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if key != "token_hash"}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def _receipt_id(value: Any, name: str, pattern: str, maximum: int = 200) -> str:
    value = _text(value, name, maximum)
    if not re.fullmatch(pattern, value):
        raise Conflict(f"invalid {name}")
    return value


def _model_usage(value: Any) -> dict:
    counts = {"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
              "actual_cost_microdollars"}
    if not isinstance(value, dict) or set(value) != counts | {"generation_id", "finish_reason"}:
        raise Conflict("invalid bounded model usage fields")
    result = {key: _integer(value[key], key, 0, 2**53 - 1) for key in counts}
    generation = value["generation_id"]
    if generation is not None:
        _receipt_id(generation, "generation_id", r"gen_[A-Za-z0-9_-]{1,508}", 512)
    reason = value["finish_reason"]
    if reason is not None:
        _receipt_id(reason, "finish_reason", r"[A-Za-z0-9_-]{1,128}", 128)
    return {**result, "generation_id": generation, "finish_reason": reason}


def _failure_usage(value: Any, actual_cost: int, cost_known: bool) -> dict | None:
    if value is None:
        return None
    counts = {"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
              "actual_cost_microdollars", "model_runs"}
    if (not cost_known or not isinstance(value, dict)
            or set(value) != counts | {"cost_source", "generations"}
            or value["cost_source"] != "eve_gateway_usage_events"):
        raise Conflict("failure usage requires bounded known runtime usage")
    result = {key: _integer(value[key], key, 0, 2**53 - 1) for key in counts}
    if result["actual_cost_microdollars"] != actual_cost:
        raise Conflict("failure usage cost does not match charged total")
    generations = value["generations"]
    if not 1 <= result["model_runs"] <= 3 or not isinstance(generations, list) or len(generations) != result["model_runs"]:
        raise Conflict("failure usage requires 1..3 distinct model runs")
    runs, ids, safe = set(), set(), []
    for item in generations:
        if not isinstance(item, dict) or set(item) != {"run_id", "generation_id", "finish_reason"}:
            raise Conflict("invalid failure generation fields")
        run_id = _receipt_id(item["run_id"], "model_run_id", r"[A-Za-z0-9_-]{1,128}", 128)
        checked = _model_usage({**{key: 0 for key in counts - {"model_runs"}},
                                "generation_id": item["generation_id"], "finish_reason": item["finish_reason"]})
        generation = checked["generation_id"]
        if run_id in runs or (generation is not None and generation in ids):
            raise Conflict("duplicate failure usage identity")
        runs.add(run_id)
        if generation is not None:
            ids.add(generation)
        safe.append({"run_id": run_id, "generation_id": generation, "finish_reason": checked["finish_reason"]})
    return {**result, "cost_source": "eve_gateway_usage_events", "generations": safe}


def _receipt_event(value: Any) -> dict:
    if not isinstance(value, dict):
        raise Conflict("receipt event must be an object")
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise Conflict("invalid receipt event kind")
    fields = {"event_id", "kind", "session_id"}
    if kind == "session":
        fields |= {"task_id", "epoch", "revision", "input_hash"}
    if kind in {"model_started", "generation", "usage"}:
        fields |= {"model_run_id", "model_id", "model_attempt"}
    if kind == "generation":
        fields.add("generation_id")
    elif kind == "usage":
        fields.add("usage")
    elif kind == "session_terminal":
        fields.add("outcome")
    if kind not in {"session", "model_started", "generation", "usage", "session_terminal"} or set(value) != fields:
        raise Conflict("invalid receipt event fields")
    result = dict(value)
    _receipt_id(value["event_id"], "event_id", r"[A-Za-z0-9_.:-]{1,200}")
    _receipt_id(value["session_id"], "session_id", r"[A-Za-z0-9_-]{1,200}")
    if kind == "session":
        _receipt_id(value["task_id"], "task_id", r"[A-Za-z0-9_-]{1,128}", 128)
        _integer(value["epoch"], "epoch", 1)
        _integer(value["revision"], "revision", 1)
        result["input_hash"] = _digest(value["input_hash"])
    if "model_run_id" in fields:
        _receipt_id(value["model_run_id"], "model_run_id", r"[A-Za-z0-9_-]{1,128}", 128)
        _receipt_id(value["model_id"], "model_id", r"[A-Za-z0-9_./:-]{1,200}")
        _integer(value["model_attempt"], "model_attempt", 0, 0)
    if kind == "generation":
        _receipt_id(value["generation_id"], "generation_id", r"gen_[A-Za-z0-9_-]{1,508}", 512)
    elif kind == "usage":
        result["usage"] = _model_usage(value["usage"])
    elif kind == "session_terminal" and (not isinstance(value["outcome"], str)
            or value["outcome"] not in {"completed", "failed", "cancelled"}):
        raise Conflict("invalid session outcome")
    return result


def _spec(value: Any) -> dict:
    if not isinstance(value, dict):
        raise Conflict("spec must be an object")
    allowed = {"name", "profile", "requirements", "tasks", "suite_hash", "policy_hash", "max_attempts"}
    if set(value) - allowed or not allowed.difference({"max_attempts"}).issubset(value):
        raise Conflict("spec has missing or unknown fields")
    result = json.loads(_json(value))
    _text(result["name"], "name")
    _text(result["profile"], "profile", 64)
    result["suite_hash"] = _digest(result["suite_hash"])
    result["policy_hash"] = _digest(result["policy_hash"])
    result["max_attempts"] = _integer(result.get("max_attempts", 3), "max_attempts", 1, 10)
    requirements = result["requirements"]
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 256:
        raise Conflict("requirements must contain 1..256 strings")
    for requirement in requirements:
        _text(requirement, "requirement", 8192)
    tasks = result["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 256:
        raise Conflict("tasks must contain 1..256 entries")
    keys: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {"key", "objective", "depends_on"}:
            raise Conflict("each task needs key, objective and depends_on")
        key = _text(task["key"], "task key", 128)
        _text(task["objective"], "objective", 8192)
        if key in keys:
            raise Conflict("duplicate task key")
        keys.add(key)
        dependencies = task["depends_on"]
        if not isinstance(dependencies, list) or len(dependencies) > 256:
            raise Conflict("invalid dependencies")
        for dependency in dependencies:
            _text(dependency, "dependency", 128)
        if len(set(dependencies)) != len(dependencies):
            raise Conflict("duplicate dependency")
    remaining = {task["key"]: set(task["depends_on"]) for task in tasks}
    if any(deps - keys for deps in remaining.values()):
        raise Conflict("unknown dependency")
    visited: set[str] = set()
    while remaining:
        ready = [key for key, deps in remaining.items() if deps <= visited]
        if not ready:
            raise Conflict("cyclic task dependencies")
        for key in ready:
            visited.add(key)
            del remaining[key]
    return result


class Ledger:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def migrate(self) -> None:
        """Serialize migrations across processes and refuse changed applied SQL."""
        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(724836192)")
            conn.execute("CREATE TABLE IF NOT EXISTS graphos_migrations (version text PRIMARY KEY, digest text NOT NULL, applied_at timestamptz NOT NULL DEFAULT clock_timestamp())")
            for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                sql = path.read_text()
                digest = hashlib.sha256(sql.encode()).hexdigest()
                applied = conn.execute("SELECT digest FROM graphos_migrations WHERE version = %s", (path.name,)).fetchone()
                if applied:
                    if applied["digest"] != digest:
                        raise Conflict("an applied migration was changed")
                    continue
                conn.execute(sql)
                conn.execute("INSERT INTO graphos_migrations(version,digest) VALUES (%s,%s)", (path.name, digest))

    @staticmethod
    def _run(conn, run_id: str) -> dict:
        row = conn.execute("SELECT * FROM graphos_runs WHERE id = %s FOR UPDATE", (run_id,)).fetchone()
        if row is None:
            raise Conflict("unknown run")
        return row

    @staticmethod
    def _event(conn, run: dict, kind: str, payload: dict) -> None:
        event = conn.execute("INSERT INTO graphos_events(run_id,revision,kind,payload) VALUES (%s,%s,%s,%s) RETURNING id", (run["id"], run["revision"], kind, Jsonb(payload))).fetchone()
        conn.execute("INSERT INTO graphos_outbox(event_id) VALUES (%s)", (event["id"],))

    @staticmethod
    def _task(conn, run: dict, task_id: str) -> dict:
        task = conn.execute("SELECT * FROM graphos_tasks WHERE id = %s AND run_id = %s AND revision = %s", (task_id, run["id"], run["revision"])).fetchone()
        if task is None:
            raise Conflict("unknown or superseded task")
        return task

    @staticmethod
    def _active_run(run: dict) -> None:
        # EXHAUSTED blocks new dispatch, but current sibling leases must still
        # settle their results and actual spend. Cancellation fences them instead.
        if run["state"] not in {"ACTIVE", "EXHAUSTED", "BUDGET_EXCEEDED", "RECONCILIATION_REQUIRED"}:
            raise Conflict("run cannot settle work")

    @staticmethod
    def _insert_tasks(conn, run_id: str, revision: int, spec: dict) -> None:
        for task in spec["tasks"]:
            conn.execute("INSERT INTO graphos_tasks(id,run_id,revision,task_key,objective,depends_on) VALUES (%s,%s,%s,%s,%s,%s)", (str(uuid.uuid4()), run_id, revision, task["key"], task["objective"], Jsonb(task["depends_on"])))

    def _snapshot(self, conn, run: dict) -> dict:
        result = dict(run)
        result["run_id"] = result["id"]
        result["profile"] = run["spec"]["profile"]
        result["tasks"] = conn.execute("SELECT * FROM graphos_tasks WHERE run_id = %s AND revision = %s ORDER BY task_key", (run["id"], run["revision"])).fetchall()
        result["events"] = conn.execute("SELECT * FROM graphos_events WHERE run_id = %s ORDER BY id", (run["id"],)).fetchall()
        result["effects"] = conn.execute("SELECT * FROM graphos_effects WHERE run_id = %s ORDER BY operation_key", (run["id"],)).fetchall()
        result["uncertain_cost_attempts"] = conn.execute("SELECT a.id AS attempt_id,a.task_id,t.revision,a.state,a.reservation,a.actual_cost AS conservative_charge FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE t.run_id=%s AND a.cost_uncertain ORDER BY a.created_at,a.id", (run["id"],)).fetchall()
        return _safe(result)

    def create_run(self, spec: dict, budget: int, idempotency_key: str) -> dict:
        spec = _spec(spec)
        budget = _integer(budget, "budget", 1)
        idempotency_key = _text(idempotency_key, "idempotency_key")
        admission_hash = _hash({"spec": spec, "budget": budget})
        with self._connect() as conn:
            run_id = str(uuid.uuid4())
            row = conn.execute("INSERT INTO graphos_runs(id,idempotency_key,admission_hash,spec,spec_hash,budget) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING *", (run_id, idempotency_key, admission_hash, Jsonb(spec), _hash(spec), budget)).fetchone()
            if row is None:
                row = conn.execute("SELECT * FROM graphos_runs WHERE idempotency_key = %s FOR UPDATE", (idempotency_key,)).fetchone()
                if row["admission_hash"] != admission_hash:
                    raise Conflict("admission key reused with a different payload")
            else:
                self._insert_tasks(conn, run_id, 1, spec)
                self._event(conn, row, "RUN_ADMITTED", {"spec_hash": row["spec_hash"], "budget": budget})
            return self._snapshot(conn, row)

    def get_run(self, run_id: str) -> dict:
        with self._connect() as conn:
            return self._snapshot(conn, self._run(conn, run_id))

    def list_runs(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id,id AS run_id,spec->>'name' AS name,spec->>'profile' AS profile,state,revision,budget,spent,reserved,created_at,updated_at FROM graphos_runs ORDER BY created_at DESC,id LIMIT 1000").fetchall()
            return _safe(rows)

    def _charge(self, conn, run: dict, reservation: int, actual: int) -> None:
        run["spent"] += actual
        run["reserved"] -= reservation
        if actual > reservation:
            run["state"] = "BUDGET_EXCEEDED"
            self._event(conn, run, "COST_OVERRUN", {"reservation": reservation, "actual_cost": actual, "overrun": actual - reservation, "spent": run["spent"], "budget": run["budget"], "reason": "actual cost exceeded its reserved authorization"})
        conn.execute("UPDATE graphos_runs SET spent=%s,reserved=%s,state=%s,updated_at=clock_timestamp() WHERE id=%s", (run["spent"], run["reserved"], run["state"], run["id"]))

    def _expire(self, conn, run: dict) -> None:
        expired = conn.execute("SELECT a.*,t.build_attempts,t.verify_attempts FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE t.run_id=%s AND t.revision=%s AND a.state='ACTIVE' AND a.expires_at <= clock_timestamp()", (run["id"], run["revision"])).fetchall()
        limit = run["spec"]["max_attempts"]
        for attempt in expired:
            build = attempt["kind"] == "BUILD"
            if build:
                self._charge(conn, run, attempt["reservation"], attempt["reservation"])
            count = attempt["build_attempts"] if build else attempt["verify_attempts"]
            state = "EXHAUSTED" if count >= limit else ("PENDING" if build else "SUBMITTED")
            conn.execute("UPDATE graphos_attempts SET state='EXPIRED',actual_cost=%s,cost_uncertain=%s WHERE id=%s", (attempt["reservation"], build, attempt["id"]))
            conn.execute("UPDATE graphos_tasks SET state=%s,state_version=state_version+1,active_attempt_id=NULL,epoch=epoch+1 WHERE id=%s", (state, attempt["task_id"]))
            self._event(conn, run, f"{attempt['kind']}_LEASE_EXPIRED", {"task_id": attempt["task_id"], "attempt_id": attempt["id"], "consumed": attempt["reservation"], "state": state})
        self._refresh_state(conn, run)

    @staticmethod
    def _refresh_state(conn, run: dict) -> None:
        if run["state"] in {"CANCELLED", "RELEASED", "BUDGET_EXCEEDED"}:
            return
        # Prior revisions can still have billed remote work. Never limit this
        # accounting check to the current task graph or merely refund uncertainty.
        uncertain = conn.execute("SELECT 1 FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE t.run_id=%s AND a.cost_uncertain LIMIT 1", (run["id"],)).fetchone()
        states = [row["state"] for row in conn.execute("SELECT state FROM graphos_tasks WHERE run_id=%s AND revision=%s", (run["id"], run["revision"])).fetchall()]
        state = "RECONCILIATION_REQUIRED" if uncertain else "READY_FOR_RELEASE" if states and all(item == "ACCEPTED" for item in states) else "EXHAUSTED" if "EXHAUSTED" in states else "ACTIVE"
        if state != run["state"]:
            conn.execute("UPDATE graphos_runs SET state=%s,updated_at=clock_timestamp() WHERE id=%s", (state, run["id"]))
            run["state"] = state

    @staticmethod
    def _dependencies(conn, run: dict, task: dict) -> dict | None:
        rows = conn.execute("SELECT task_key,state,candidate_hash FROM graphos_tasks WHERE run_id=%s AND revision=%s", (run["id"], run["revision"])).fetchall()
        index = {row["task_key"]: row for row in rows}
        if any(index[key]["state"] != "ACCEPTED" for key in task["depends_on"]):
            return None
        return {key: index[key]["candidate_hash"] for key in sorted(task["depends_on"])}

    @staticmethod
    def _input(run: dict, task: dict, dependencies: dict) -> str:
        return _hash({"spec_hash": run["spec_hash"], "revision": run["revision"], "task_key": task["task_key"], "dependencies": dependencies})

    @staticmethod
    def _repair(conn, run: dict, task: dict, input_hash: str, before_epoch: int) -> dict | None:
        """Read failed evidence for this input, never carry it across a revision.

        The immutable verifier attempt survives clearing the task's candidate on
        rebuild. Only the latest completed verification may supply context; its
        diagnostics and candidate are data, not renewed acceptance evidence.
        """
        attempt = conn.execute("SELECT * FROM graphos_attempts WHERE task_id=%s AND kind='VERIFY' AND state='VERIFIED' AND epoch<%s ORDER BY epoch DESC LIMIT 1", (task["id"], before_epoch)).fetchone()
        if not attempt:
            return None
        record = attempt["result"] or {}
        if (record.get("passed") is not False or record.get("revision") != run["revision"]
                or record.get("input_hash") != input_hash or attempt["input_hash"] != input_hash
                or record.get("suite_hash") != run["spec"]["suite_hash"]
                or record.get("policy_hash") != run["spec"]["policy_hash"]
                or record.get("candidate_hash") != attempt["candidate_hash"]
                or record.get("attempt_id") != attempt["id"]
                or record.get("verifier_id") != attempt["worker_id"]):
            return None
        report = record.get("report", {})
        raw_checks = report.get("checks", []) if isinstance(report, dict) else []
        if not isinstance(raw_checks, list):
            raw_checks = []
        checks = []
        truncated = len(raw_checks) > 32
        # Preserve failed diagnostics first, including when a long report ends
        # with the only failure. A failed report with no usable failed check is
        # represented by its actual rejection decision, never as an all-pass.
        raw_checks = sorted(raw_checks, key=lambda c: not (isinstance(c, dict) and c.get("passed") is False))
        for check in raw_checks[:32]:
            if (not isinstance(check, dict) or not isinstance(check.get("name"), str)
                    or type(check.get("passed")) is not bool):
                truncated = True
                continue
            detail = check.get("detail", "")
            if not isinstance(detail, str):
                detail = ""
                truncated = True
            # Byte bounds keep even non-ASCII diagnostics within the prompt cap.
            name = check["name"].encode("utf-8")[:128].decode("utf-8", errors="ignore")
            bounded = detail.encode("utf-8")[:1024].decode("utf-8", errors="ignore")
            truncated = truncated or name != check["name"] or bounded != detail
            checks.append({"name": name, "passed": check["passed"], "detail": bounded})
        if not any(check["passed"] is False for check in checks):
            checks = [{"name": "verification_rejected", "passed": False,
                       "detail": "Independent verification rejected this candidate; detailed failed checks were unavailable."}, *checks[:31]]
            truncated = True
        return {"candidate_hash": _digest(record["candidate_hash"]),
                "evidence_hash": _digest(record["evidence_hash"]),
                "verifier_attempt_id": attempt["id"], "revision": run["revision"],
                "input_hash": input_hash, "suite_hash": record["suite_hash"],
                "policy_hash": record["policy_hash"], "checks": checks,
                "truncated": truncated}

    def _claim(self, conn, run: dict, task: dict, worker: str, kind: str, reservation: int, seconds: int, dependencies: dict) -> dict:
        token = secrets.token_urlsafe(32)
        epoch = task["epoch"] + 1
        attempt_id = str(uuid.uuid4())
        input_hash = self._input(run, task, dependencies)
        expires = conn.execute("SELECT clock_timestamp() + %s * interval '1 second' AS expires", (seconds,)).fetchone()["expires"]
        conn.execute("INSERT INTO graphos_attempts(id,task_id,kind,epoch,worker_id,token_hash,reservation,expires_at,input_hash,candidate_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (attempt_id, task["id"], kind, epoch, worker, hashlib.sha256(token.encode()).hexdigest(), reservation, expires, input_hash, task["candidate_hash"] if kind == "VERIFY" else None))
        if kind == "BUILD":
            conn.execute("UPDATE graphos_tasks SET state='BUILDING',epoch=%s,active_attempt_id=%s,input_hash=%s,state_version=state_version+1,build_attempts=build_attempts+1,verify_attempts=0,candidate_hash=NULL,evidence_hash=NULL,verification=NULL,producer_id=%s WHERE id=%s", (epoch, attempt_id, input_hash, worker, task["id"]))
            run["reserved"] += reservation
            conn.execute("UPDATE graphos_runs SET reserved=%s,updated_at=clock_timestamp() WHERE id=%s", (run["reserved"], run["id"]))
        else:
            conn.execute("UPDATE graphos_tasks SET state='VERIFYING',epoch=%s,active_attempt_id=%s,state_version=state_version+1,verify_attempts=verify_attempts+1 WHERE id=%s", (epoch, attempt_id, task["id"]))
        self._event(conn, run, f"{kind}_CLAIMED", {"task_id": task["id"], "attempt_id": attempt_id, "epoch": epoch, "worker_id": worker, "reservation": reservation})
        result = {"run_id": run["id"], "task_id": task["id"], "task_key": task["task_key"], "attempt_id": attempt_id, "epoch": epoch, "revision": run["revision"], "token": token, "input_hash": input_hash, "expires_at": expires, "objective": task["objective"], "requirements": run["spec"]["requirements"], "profile": run["spec"]["profile"], "suite_hash": run["spec"]["suite_hash"], "policy_hash": run["spec"]["policy_hash"], "dependencies": dependencies, "reservation": reservation}
        if kind == "VERIFY":
            result.update(candidate_hash=task["candidate_hash"], producer_id=task["producer_id"])
        else:
            repair = self._repair(conn, run, task, input_hash, epoch)
            if repair is not None:
                result["repair"] = repair
        return _safe(result)

    def claim_build(self, run_id: str, worker_id: str, reserve: int, lease_seconds: int = 120) -> dict | None:
        worker_id = _text(worker_id, "worker_id")
        reserve = _integer(reserve, "reserve")
        seconds = _integer(lease_seconds, "lease_seconds", 1, 3600)
        with self._connect() as conn:
            run = self._run(conn, run_id)
            if run["state"] == "CANCELLED":
                return None
            self._expire(conn, run)
            if run["state"] != "ACTIVE" or run["spent"] + run["reserved"] + reserve > run["budget"]:
                return None
            tasks = conn.execute("SELECT * FROM graphos_tasks WHERE run_id=%s AND revision=%s AND state='PENDING' ORDER BY task_key", (run_id, run["revision"])).fetchall()
            for task in tasks:
                dependencies = self._dependencies(conn, run, task)
                if dependencies is not None:
                    return self._claim(conn, run, task, worker_id, "BUILD", reserve, seconds, dependencies)
            return None

    def claim_verify(self, run_id: str, verifier_id: str, lease_seconds: int = 120) -> dict | None:
        verifier_id = _text(verifier_id, "verifier_id")
        seconds = _integer(lease_seconds, "lease_seconds", 1, 3600)
        with self._connect() as conn:
            run = self._run(conn, run_id)
            if run["state"] == "CANCELLED":
                return None
            self._expire(conn, run)
            if run["state"] != "ACTIVE":
                return None
            tasks = conn.execute("SELECT * FROM graphos_tasks WHERE run_id=%s AND revision=%s AND state='SUBMITTED' AND producer_id<>%s ORDER BY task_key", (run_id, run["revision"], verifier_id)).fetchall()
            for task in tasks:
                dependencies = self._dependencies(conn, run, task)
                if dependencies is not None:
                    return self._claim(conn, run, task, verifier_id, "VERIFY", 0, seconds, dependencies)
            return None

    def authorize_artifact(self, run_id: str, task_id: str, token: str, epoch: int, digest: str, kind: str) -> None:
        """Grant only the artifacts consumed by a current worker lease."""
        digest = _digest(digest)
        if kind not in {"BUILD", "VERIFY"}:
            raise Conflict("invalid artifact lease kind")
        with self._connect() as conn:
            run = self._run(conn, run_id)
            self._active_run(run)
            task = self._task(conn, run, task_id)
            attempt = self._attempt(conn, task, token, epoch, kind)
            self._require_current(task, attempt)
            if kind == "VERIFY":
                allowed = task["state"] == "VERIFYING" and digest == task["candidate_hash"] == attempt["candidate_hash"]
            else:
                dependencies = self._dependencies(conn, run, task)
                repair = self._repair(conn, run, task, attempt["input_hash"], attempt["epoch"])
                allowed = (task["state"] == "BUILDING" and dependencies is not None
                           and self._input(run, task, dependencies) == attempt["input_hash"]
                           and (digest in dependencies.values()
                                or (repair is not None and digest == repair["candidate_hash"])))
            if not allowed:
                raise Conflict("artifact is outside this lease's scope")

    def create_receipt_grant(self, run_id: str, task_id: str, token: str, epoch: int,
                             revision: int, input_hash: str) -> dict:
        """Delegate capture only; the lease credential and accounting stay private."""
        with self._connect() as conn:
            run = self._run(conn, run_id)
            task = self._task(conn, run, task_id)
            self._bindings(run, task, revision, input_hash)
            attempt = self._attempt(conn, task, token, epoch, "BUILD")
            capture_token = hmac.new(token.encode(),
                ("graphos-receipt-v1:" + attempt["id"]).encode(), hashlib.sha256).hexdigest()
            digest = hashlib.sha256(capture_token.encode()).hexdigest()
            existing = conn.execute("SELECT token_hash FROM graphos_receipt_grants WHERE attempt_id=%s", (attempt["id"],)).fetchone()
            if existing:
                if not secrets.compare_digest(existing["token_hash"], digest):
                    raise Conflict("receipt grant binding changed")
            else:
                self._active_run(run)
                self._require_current(task, attempt)
                conn.execute("INSERT INTO graphos_receipt_grants(attempt_id,token_hash) VALUES (%s,%s)", (attempt["id"], digest))
                self._event(conn, run, "RECEIPT_CAPTURE_GRANTED", {"task_id": task_id, "attempt_id": attempt["id"]})
            return {"run_id": run_id, "task_id": task_id, "attempt_id": attempt["id"],
                    "capture_token": capture_token,
                    "capture_path": f"/v1/runs/{run_id}/attempts/{attempt['id']}/receipts"}

    @staticmethod
    def _receipt_attempt(conn, run_id: str, attempt_id: str) -> dict:
        attempt = conn.execute("SELECT a.*,a.expires_at > clock_timestamp() AS unexpired,t.run_id,t.revision AS attempt_revision,t.epoch AS task_epoch,t.active_attempt_id FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE a.id=%s AND t.run_id=%s AND a.kind='BUILD'", (attempt_id, run_id)).fetchone()
        if not attempt:
            raise Conflict("unknown build receipt attempt")
        return attempt

    def capture_attempt_receipt(self, run_id: str, attempt_id: str, capture_token: str,
                                payload: dict) -> dict:
        """Record bounded runtime facts without settling cost or accepting artifacts.

        Existing model callbacks survive fencing. New provider intents still need
        the current build lease, and an unresolved prior intent blocks another.
        IDs are recovery lookup keys, never authoritative provider cost evidence.
        """
        payload = _receipt_event(payload)
        _text(capture_token, "capture_token", 256)
        identity = payload["kind"] + (":" + payload["model_run_id"] if "model_run_id" in payload else "")
        payload_hash = _hash(payload)
        with self._connect() as conn:
            run = self._run(conn, run_id)
            attempt = self._receipt_attempt(conn, run_id, attempt_id)
            grant = conn.execute("SELECT * FROM graphos_receipt_grants WHERE attempt_id=%s", (attempt_id,)).fetchone()
            if not grant or not secrets.compare_digest(grant["token_hash"], hashlib.sha256(capture_token.encode()).hexdigest()):
                raise ReceiptAuthorizationError("invalid receipt capture capability")
            existing = conn.execute("SELECT * FROM graphos_attempt_receipt_events WHERE attempt_id=%s AND (event_id=%s OR identity_key=%s)", (attempt_id, payload["event_id"], identity)).fetchall()
            if existing:
                if any(record["payload_hash"] != payload_hash for record in existing):
                    raise Conflict("receipt identity reused with a different payload")
                return {"recorded": True, "duplicate": True, "attempt_id": attempt_id,
                        "event_id": payload["event_id"], "kind": payload["kind"]}

            kind = payload["kind"]
            if kind in {"session", "model_started"}:
                # Settlement remains legal during reconciliation/overrun, but a
                # fresh provider intent must not spend through either pause.
                if run["state"] != "ACTIVE":
                    raise Conflict("new receipt intent requires an active run")
                if (attempt["state"] != "ACTIVE" or not attempt["unexpired"]
                        or attempt["active_attempt_id"] != attempt_id
                        or attempt["task_epoch"] != attempt["epoch"]
                        or attempt["attempt_revision"] != run["revision"]):
                    raise Conflict("new receipt intent requires a current build lease")
                # Capture must never perform accounting or expiry transitions.
                # An abandoned sibling may already have unreported spend even
                # before a dispatcher observes its expiry and pauses the run.
                if conn.execute("SELECT 1 FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE t.run_id=%s AND a.kind='BUILD' AND a.state='ACTIVE' AND a.expires_at<=clock_timestamp() LIMIT 1", (run_id,)).fetchone():
                    raise Conflict("new receipt intent blocked by an unresolved expired build")
            if kind == "session":
                if (payload["task_id"] != attempt["task_id"] or payload["epoch"] != attempt["epoch"]
                        or payload["revision"] != attempt["attempt_revision"]
                        or payload["input_hash"] != attempt["input_hash"]):
                    raise Conflict("receipt session does not match its claimed input binding")
                try:
                    with conn.transaction():
                        conn.execute("UPDATE graphos_receipt_grants SET session_id=%s WHERE attempt_id=%s", (payload["session_id"], attempt_id))
                except psycopg.errors.UniqueViolation as exc:
                    raise Conflict("session is already bound to another attempt") from exc
            else:
                if grant["session_id"] != payload["session_id"]:
                    raise Conflict("receipt session does not match this attempt")
                if kind == "session_terminal":
                    conn.execute("UPDATE graphos_receipt_grants SET terminal_outcome=%s WHERE attempt_id=%s", (payload["outcome"], attempt_id))
                else:
                    model = conn.execute("SELECT * FROM graphos_model_receipts WHERE attempt_id=%s AND model_run_id=%s", (attempt_id, payload["model_run_id"])).fetchone()
                    if kind == "model_started":
                        if grant["terminal_outcome"] is not None:
                            raise Conflict("terminal session cannot dispatch another model")
                        models = conn.execute("SELECT usage FROM graphos_model_receipts WHERE attempt_id=%s", (attempt_id,)).fetchall()
                        if len(models) >= 3 or any(item["usage"] is None for item in models):
                            raise Conflict("model receipt budget exhausted or previous model unresolved")
                        conn.execute("INSERT INTO graphos_model_receipts(attempt_id,model_run_id,model_id,model_attempt) VALUES (%s,%s,%s,%s)", (attempt_id, payload["model_run_id"], payload["model_id"], payload["model_attempt"]))
                    else:
                        if not model or model["model_id"] != payload["model_id"] or model["model_attempt"] != payload["model_attempt"]:
                            raise Conflict("receipt model does not match a registered intent")
                        generation = payload.get("generation_id") if kind == "generation" else payload["usage"]["generation_id"]
                        if generation is not None:
                            if model["generation_id"] is not None and model["generation_id"] != generation:
                                raise Conflict("model generation identity changed")
                            try:
                                with conn.transaction():
                                    conn.execute("UPDATE graphos_model_receipts SET generation_id=%s WHERE attempt_id=%s AND model_run_id=%s", (generation, attempt_id, payload["model_run_id"]))
                            except psycopg.errors.UniqueViolation as exc:
                                raise Conflict("generation is already bound to another model") from exc
                        if kind == "usage":
                            conn.execute("UPDATE graphos_model_receipts SET usage=%s WHERE attempt_id=%s AND model_run_id=%s", (Jsonb({**payload["usage"], "cost_source": "eve_gateway_usage_events"}), attempt_id, payload["model_run_id"]))
            conn.execute("INSERT INTO graphos_attempt_receipt_events(attempt_id,event_id,identity_key,payload_hash,payload) VALUES (%s,%s,%s,%s,%s)", (attempt_id, payload["event_id"], identity, payload_hash, Jsonb(payload)))
            self._event(conn, run, "ATTEMPT_RECEIPT_CAPTURED", {"attempt_id": attempt_id,
                "event_id": payload["event_id"], "kind": kind, "attempt_revision": attempt["attempt_revision"]})
            return {"recorded": True, "duplicate": False, "attempt_id": attempt_id,
                    "event_id": payload["event_id"], "kind": kind}

    def get_attempt_receipts(self, run_id: str, attempt_id: str) -> dict:
        """Operator recovery view; includes old revisions, never capability secrets."""
        with self._connect() as conn:
            self._run(conn, run_id)
            attempt = self._receipt_attempt(conn, run_id, attempt_id)
            grant = conn.execute("SELECT session_id,terminal_outcome,created_at FROM graphos_receipt_grants WHERE attempt_id=%s", (attempt_id,)).fetchone()
            models = conn.execute("SELECT model_run_id,model_id,model_attempt,generation_id,usage,created_at FROM graphos_model_receipts WHERE attempt_id=%s ORDER BY created_at,model_run_id", (attempt_id,)).fetchall()
            events = conn.execute("SELECT event_id,payload,created_at FROM graphos_attempt_receipt_events WHERE attempt_id=%s ORDER BY created_at,event_id", (attempt_id,)).fetchall()
            return _safe({"run_id": run_id, "attempt_id": attempt_id, "task_id": attempt["task_id"],
                "attempt_revision": attempt["attempt_revision"], "attempt_state": attempt["state"],
                "cost_uncertain": attempt["cost_uncertain"], "capture": grant, "models": models,
                "events": events, "failure_usage": (attempt["result"] or {}).get("usage"),
                "source": "trusted_runtime_capture", "settles_cost": False})

    @staticmethod
    def _attempt(conn, task: dict, token: str, epoch: int, kind: str) -> dict:
        _text(token, "lease token", 256)
        _integer(epoch, "epoch", 1)
        attempt = conn.execute("SELECT *, expires_at > clock_timestamp() AS unexpired FROM graphos_attempts WHERE task_id=%s AND epoch=%s AND kind=%s", (task["id"], epoch, kind)).fetchone()
        if not attempt or not secrets.compare_digest(attempt["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise Conflict("invalid lease binding")
        return attempt

    @staticmethod
    def _require_current(task: dict, attempt: dict) -> None:
        if attempt["state"] != "ACTIVE" or not attempt["unexpired"] or task["active_attempt_id"] != attempt["id"] or task["epoch"] != attempt["epoch"]:
            raise Conflict("expired or fenced lease")

    @staticmethod
    def _bindings(run: dict, task: dict, revision: int, input_hash: str) -> None:
        if type(revision) is not int or revision != run["revision"] or _digest(input_hash) != task["input_hash"]:
            raise Conflict("stale revision or input binding")

    def submit_build(self, run_id: str, task_id: str, token: str, epoch: int, revision: int, input_hash: str, candidate_hash: str, actual_cost: int, provenance: dict) -> dict:
        candidate_hash = _digest(candidate_hash)
        actual_cost = _integer(actual_cost, "actual_cost")
        if not isinstance(provenance, dict) or len(_json(provenance)) > 65536:
            raise Conflict("invalid provenance")
        submission = _hash({"candidate": candidate_hash, "cost": actual_cost, "provenance": provenance})
        with self._connect() as conn:
            run = self._run(conn, run_id)
            task = self._task(conn, run, task_id)
            self._bindings(run, task, revision, input_hash)
            attempt = self._attempt(conn, task, token, epoch, "BUILD")
            if attempt["state"] == "SUBMITTED" and attempt["submission_hash"] == submission:
                return _safe(task)
            self._active_run(run)
            self._require_current(task, attempt)
            if task["state"] != "BUILDING":
                raise Conflict("task is not building")
            self._charge(conn, run, attempt["reservation"], actual_cost)
            conn.execute("UPDATE graphos_attempts SET state='SUBMITTED',actual_cost=%s,candidate_hash=%s,submission_hash=%s,result=%s WHERE id=%s", (actual_cost, candidate_hash, submission, Jsonb(provenance), attempt["id"]))
            conn.execute("UPDATE graphos_tasks SET state='SUBMITTED',candidate_hash=%s,active_attempt_id=NULL,state_version=state_version+1 WHERE id=%s", (candidate_hash, task_id))
            self._event(conn, run, "BUILD_SUBMITTED", {"task_id": task_id, "attempt_id": attempt["id"], "candidate_hash": candidate_hash, "actual_cost": actual_cost, "provenance": provenance})
            return _safe(self._task(conn, run, task_id))

    def fail_build(self, run_id: str, task_id: str, token: str, epoch: int, reason: str, actual_cost: int, cost_known: bool = False, usage: dict | None = None) -> dict:
        reason = _text(reason, "reason", 4096)
        actual_cost = _integer(actual_cost, "actual_cost")
        if type(cost_known) is not bool:
            raise Conflict("cost_known must be boolean")
        usage = _failure_usage(usage, actual_cost, cost_known)
        metadata = {"usage": usage} if usage is not None else {}
        submission = _hash({"reason": reason, "cost": actual_cost, "cost_known": cost_known, **metadata})
        with self._connect() as conn:
            run = self._run(conn, run_id)
            task = self._task(conn, run, task_id)
            attempt = self._attempt(conn, task, token, epoch, "BUILD")
            if attempt["state"] == "FAILED" and attempt["submission_hash"] == submission:
                return _safe(task)
            self._active_run(run)
            self._require_current(task, attempt)
            if usage is not None and conn.execute("SELECT 1 FROM graphos_receipt_grants WHERE attempt_id=%s", (attempt["id"],)).fetchone():
                captured = conn.execute("SELECT * FROM graphos_model_receipts WHERE attempt_id=%s", (attempt["id"],)).fetchall()
                reported = {item["run_id"]: item for item in usage["generations"]}
                if (set(reported) != {item["model_run_id"] for item in captured}
                        or any(item["usage"] is None for item in captured)):
                    raise Conflict("failure usage does not cover completed captured models")
                for item in captured:
                    detail = reported[item["model_run_id"]]
                    if ((detail["generation_id"] is not None and detail["generation_id"] != item["generation_id"])
                            or detail["finish_reason"] != item["usage"]["finish_reason"]):
                        raise Conflict("failure usage conflicts with captured model identity")
                for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "actual_cost_microdollars"):
                    if usage[key] != sum(item["usage"][key] for item in captured):
                        raise Conflict("failure usage does not match captured model totals")
            charge = actual_cost if cost_known else max(actual_cost, attempt["reservation"])
            self._charge(conn, run, attempt["reservation"], charge)
            state = "EXHAUSTED" if task["build_attempts"] >= run["spec"]["max_attempts"] else "PENDING"
            conn.execute("UPDATE graphos_attempts SET state='FAILED',actual_cost=%s,cost_uncertain=%s,submission_hash=%s,result=%s WHERE id=%s", (charge, not cost_known, submission, Jsonb({"reason": reason, "cost_known": cost_known, **metadata}), attempt["id"]))
            conn.execute("UPDATE graphos_tasks SET state=%s,active_attempt_id=NULL,state_version=state_version+1 WHERE id=%s", (state, task_id))
            self._event(conn, run, "BUILD_FAILED", {"task_id": task_id, "attempt_id": attempt["id"], "reason": reason, "actual_cost": charge, "cost_known": cost_known, "state": state, **metadata})
            self._refresh_state(conn, run)
            return _safe(self._task(conn, run, task_id))

    def submit_verification(self, run_id: str, task_id: str, token: str, epoch: int, revision: int, input_hash: str, candidate_hash: str, suite_hash: str, policy_hash: str, passed: bool, evidence_hash: str, report: dict) -> dict:
        candidate_hash, suite_hash, policy_hash, evidence_hash = map(_digest, (candidate_hash, suite_hash, policy_hash, evidence_hash))
        if type(passed) is not bool or not isinstance(report, dict) or len(_json(report)) > 262144:
            raise Conflict("invalid verification report")
        record = {"candidate_hash": candidate_hash, "suite_hash": suite_hash, "policy_hash": policy_hash, "evidence_hash": evidence_hash, "input_hash": _digest(input_hash), "revision": revision, "passed": passed, "report": report}
        submission = _hash(record)
        with self._connect() as conn:
            run = self._run(conn, run_id)
            task = self._task(conn, run, task_id)
            self._bindings(run, task, revision, input_hash)
            attempt = self._attempt(conn, task, token, epoch, "VERIFY")
            if attempt["state"] == "VERIFIED" and attempt["submission_hash"] == submission:
                return _safe(task)
            self._active_run(run)
            self._require_current(task, attempt)
            if task["state"] != "VERIFYING" or attempt["worker_id"] == task["producer_id"] or candidate_hash != task["candidate_hash"] or candidate_hash != attempt["candidate_hash"] or suite_hash != run["spec"]["suite_hash"] or policy_hash != run["spec"]["policy_hash"]:
                raise Conflict("verification does not match current independent candidate and policy")
            record["verifier_id"] = attempt["worker_id"]
            record["attempt_id"] = attempt["id"]
            state = "ACCEPTED" if passed else "PENDING" if task["build_attempts"] < run["spec"]["max_attempts"] else "EXHAUSTED"
            conn.execute("UPDATE graphos_attempts SET state='VERIFIED',submission_hash=%s,result=%s WHERE id=%s", (submission, Jsonb(record), attempt["id"]))
            conn.execute("UPDATE graphos_tasks SET state=%s,evidence_hash=%s,verification=%s,active_attempt_id=NULL,state_version=state_version+1 WHERE id=%s", (state, evidence_hash, Jsonb(record), task_id))
            self._event(conn, run, "VERIFICATION_COMPLETED", {"task_id": task_id, "passed": passed, "evidence_hash": evidence_hash, "candidate_hash": candidate_hash, "verifier_id": attempt["worker_id"], "state": state})
            self._refresh_state(conn, run)
            return _safe(self._task(conn, run, task_id))

    def _fence(self, conn, run: dict, state: str) -> None:
        attempts = conn.execute("SELECT a.* FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE t.run_id=%s AND t.revision=%s AND a.state='ACTIVE'", (run["id"], run["revision"])).fetchall()
        for attempt in attempts:
            if attempt["kind"] == "BUILD":
                self._charge(conn, run, attempt["reservation"], attempt["reservation"])
            conn.execute("UPDATE graphos_attempts SET state='FENCED',actual_cost=%s,cost_uncertain=%s WHERE id=%s", (attempt["reservation"], attempt["kind"] == "BUILD", attempt["id"]))
        conn.execute("UPDATE graphos_tasks SET state=%s,epoch=epoch+1,active_attempt_id=NULL,state_version=state_version+1 WHERE run_id=%s AND revision=%s", (state, run["id"], run["revision"]))

    def revise_run(self, run_id: str, spec: dict, expected_revision: int) -> dict:
        spec = _spec(spec)
        _integer(expected_revision, "expected_revision", 1)
        with self._connect() as conn:
            run = self._run(conn, run_id)
            if run["state"] in {"CANCELLED", "BUDGET_EXCEEDED"} or run["revision"] != expected_revision:
                raise Conflict("cancelled or budget-blocked run, or stale revision")
            self._fence(conn, run, "INVALIDATED")
            conn.execute("UPDATE graphos_releases SET invalidated_at=clock_timestamp() WHERE run_id=%s AND invalidated_at IS NULL", (run_id,))
            old_revision = run["revision"]
            run = conn.execute("UPDATE graphos_runs SET revision=revision+1,state='ACTIVE',spec=%s,spec_hash=%s,updated_at=clock_timestamp() WHERE id=%s RETURNING *", (Jsonb(spec), _hash(spec), run_id)).fetchone()
            self._insert_tasks(conn, run_id, run["revision"], spec)
            self._refresh_state(conn, run)
            self._event(conn, run, "RUN_REVISED", {"previous_revision": old_revision, "spec_hash": run["spec_hash"]})
            return self._snapshot(conn, run)

    def cancel_run(self, run_id: str) -> dict:
        with self._connect() as conn:
            run = self._run(conn, run_id)
            if run["state"] != "CANCELLED":
                self._fence(conn, run, "CANCELLED")
                run = conn.execute("UPDATE graphos_runs SET state='CANCELLED',updated_at=clock_timestamp() WHERE id=%s RETURNING *", (run_id,)).fetchone()
                self._event(conn, run, "RUN_CANCELLED", {"spent": run["spent"]})
            return self._snapshot(conn, run)

    def release_manifest(self, run_id: str, expected_revision: int | None = None, expected_spec_hash: str | None = None) -> dict:
        if expected_revision is not None:
            _integer(expected_revision, "expected_revision", 1)
        if expected_spec_hash is not None:
            expected_spec_hash = _digest(expected_spec_hash)
        with self._connect() as conn:
            run = self._run(conn, run_id)
            if (expected_revision is not None and run["revision"] != expected_revision) or (expected_spec_hash is not None and run["spec_hash"] != expected_spec_hash):
                raise Conflict("release preflight snapshot is stale")
            if run["state"] not in {"READY_FOR_RELEASE", "RELEASED"}:
                raise Conflict("run is not ready for release")
            tasks = conn.execute("SELECT * FROM graphos_tasks WHERE run_id=%s AND revision=%s ORDER BY task_key", (run_id, run["revision"])).fetchall()
            bindings = []
            for task in tasks:
                verification = task["verification"] or {}
                dependencies = self._dependencies(conn, run, task)
                if task["state"] != "ACCEPTED" or dependencies is None or task["input_hash"] != self._input(run, task, dependencies) or not verification.get("passed") or verification.get("candidate_hash") != task["candidate_hash"] or verification.get("input_hash") != task["input_hash"] or verification.get("revision") != run["revision"] or verification.get("suite_hash") != run["spec"]["suite_hash"] or verification.get("policy_hash") != run["spec"]["policy_hash"] or verification.get("evidence_hash") != task["evidence_hash"] or verification.get("verifier_id") == task["producer_id"]:
                    raise Conflict("release evidence is stale or incomplete")
                build = conn.execute("SELECT * FROM graphos_attempts WHERE task_id=%s AND kind='BUILD' AND state='SUBMITTED' ORDER BY epoch DESC LIMIT 1", (task["id"],)).fetchone()
                if not build or build["candidate_hash"] != task["candidate_hash"] or build["input_hash"] != task["input_hash"] or build["worker_id"] != task["producer_id"]:
                    raise Conflict("release build provenance is stale or missing")
                bindings.append({"task_id": task["id"], "task_key": task["task_key"], "candidate_hash": task["candidate_hash"], "evidence_hash": task["evidence_hash"], "input_hash": task["input_hash"], "suite_hash": verification["suite_hash"], "policy_hash": verification["policy_hash"], "verifier_id": verification["verifier_id"], "producer_id": task["producer_id"], "provenance": build["result"]})
            manifest = {"run_id": run_id, "revision": run["revision"], "spec_hash": run["spec_hash"], "profile": run["spec"]["profile"], "tasks": bindings}
            digest = _hash(manifest)
            existing = conn.execute("SELECT * FROM graphos_releases WHERE run_id=%s AND revision=%s", (run_id, run["revision"])).fetchone()
            if existing:
                if existing["invalidated_at"] or existing["manifest_hash"] != digest:
                    raise Conflict("release manifest changed")
                return {**manifest, "manifest_hash": digest, "release_id": existing["id"]}
            release_id = str(uuid.uuid4())
            conn.execute("INSERT INTO graphos_releases(id,run_id,revision,manifest_hash,manifest) VALUES (%s,%s,%s,%s,%s)", (release_id, run_id, run["revision"], digest, Jsonb(manifest)))
            conn.execute("UPDATE graphos_runs SET state='RELEASED',updated_at=clock_timestamp() WHERE id=%s", (run_id,))
            self._event(conn, run, "RELEASE_RECORDED", {"release_id": release_id, "manifest_hash": digest})
            return {**manifest, "manifest_hash": digest, "release_id": release_id}

    def prepare_effect(self, run_id: str, key: str, payload_hash: str, receiver_deduplicates: bool) -> dict:
        key, payload_hash = _text(key, "operation key"), _digest(payload_hash)
        if type(receiver_deduplicates) is not bool:
            raise Conflict("receiver_deduplicates must be boolean")
        with self._connect() as conn:
            run = self._run(conn, run_id)
            existing = conn.execute("SELECT * FROM graphos_effects WHERE run_id=%s AND operation_key=%s", (run_id, key)).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash or existing["receiver_deduplicates"] != receiver_deduplicates or existing["revision"] != run["revision"]:
                    raise Conflict("effect key already binds a different payload, contract or revision")
                return _safe(existing)
            if run["state"] in {"CANCELLED", "EXHAUSTED", "BUDGET_EXCEEDED", "RECONCILIATION_REQUIRED"}:
                raise Conflict("run cannot prepare effects")
            effect = conn.execute("INSERT INTO graphos_effects(run_id,operation_key,revision,payload_hash,receiver_deduplicates) VALUES (%s,%s,%s,%s,%s) RETURNING *", (run_id, key, run["revision"], payload_hash, receiver_deduplicates)).fetchone()
            self._event(conn, run, "EFFECT_PREPARED", {"key": key, "payload_hash": payload_hash, "receiver_deduplicates": receiver_deduplicates})
            return _safe(effect)

    def begin_effect(self, run_id: str, key: str) -> dict:
        key = _text(key, "operation key")
        with self._connect() as conn:
            run = self._run(conn, run_id)
            effect = conn.execute("SELECT * FROM graphos_effects WHERE run_id=%s AND operation_key=%s", (run_id, key)).fetchone()
            if not effect or effect["revision"] != run["revision"] or run["state"] in {"CANCELLED", "EXHAUSTED", "BUDGET_EXCEEDED", "RECONCILIATION_REQUIRED"}:
                raise Conflict("effect cannot dispatch")
            if effect["state"] == "CONFIRMED" or effect["state"] in {"DISPATCHED", "UNKNOWN"} and not effect["receiver_deduplicates"]:
                raise Conflict("effect already confirmed or ambiguous without receiver deduplication")
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            effect = conn.execute("UPDATE graphos_effects SET attempt=attempt+1,state='DISPATCHED',token_hash=%s,updated_at=clock_timestamp() WHERE run_id=%s AND operation_key=%s RETURNING *", (digest, run_id, key)).fetchone()
            conn.execute("INSERT INTO graphos_effect_attempts(run_id,operation_key,attempt,token_hash) VALUES (%s,%s,%s,%s)", (run_id, key, effect["attempt"], digest))
            self._event(conn, run, "EFFECT_DISPATCH_RECORDED", {"key": key, "attempt": effect["attempt"]})
            return {**_safe(effect), "token": token}

    def resolve_effect(self, run_id: str, key: str, attempt: int, token: str, outcome: str) -> dict:
        key = _text(key, "operation key")
        _integer(attempt, "attempt", 1)
        _text(token, "effect token")
        if outcome not in {"CONFIRMED", "UNKNOWN", "NOT_APPLIED"}:
            raise Conflict("invalid effect outcome")
        with self._connect() as conn:
            run = self._run(conn, run_id)
            effect = conn.execute("SELECT * FROM graphos_effects WHERE run_id=%s AND operation_key=%s", (run_id, key)).fetchone()
            if not effect or effect["attempt"] != attempt or not effect["token_hash"] or not secrets.compare_digest(effect["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
                raise Conflict("stale effect receipt")
            if effect["state"] == outcome:
                return _safe(effect)
            if effect["state"] in {"CONFIRMED", "NOT_APPLIED"}:
                raise Conflict("terminal effect outcome cannot be rewritten")
            effect = conn.execute("UPDATE graphos_effects SET state=%s,updated_at=clock_timestamp() WHERE run_id=%s AND operation_key=%s RETURNING *", (outcome, run_id, key)).fetchone()
            conn.execute("UPDATE graphos_effect_attempts SET outcome=%s,updated_at=clock_timestamp() WHERE run_id=%s AND operation_key=%s AND attempt=%s", (outcome, run_id, key, attempt))
            self._event(conn, run, "EFFECT_RESOLVED", {"key": key, "attempt": attempt, "outcome": outcome, "effect_revision": effect["revision"]})
            return _safe(effect)

    def claim_effect_reconciliation(self, run_id: str, key: str) -> dict:
        """Rotate a receipt credential without dispatching or inventing an attempt.

        The authenticated operator/adapter may recover an uncertain operation even
        after losing begin_effect's response, cancellation, or a run revision.
        This is authority to reconcile remote facts, never authority to resend.
        """
        key = _text(key, "operation key")
        with self._connect() as conn:
            run = self._run(conn, run_id)
            effect = conn.execute("SELECT * FROM graphos_effects WHERE run_id=%s AND operation_key=%s", (run_id, key)).fetchone()
            if not effect or effect["state"] not in {"DISPATCHED", "UNKNOWN"} or effect["attempt"] < 1:
                raise Conflict("effect has no uncertain dispatched attempt to reconcile")
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            effect = conn.execute("UPDATE graphos_effects SET state='UNKNOWN',token_hash=%s,updated_at=clock_timestamp() WHERE run_id=%s AND operation_key=%s RETURNING *", (digest, run_id, key)).fetchone()
            conn.execute("UPDATE graphos_effect_attempts SET token_hash=%s,outcome='UNKNOWN',updated_at=clock_timestamp() WHERE run_id=%s AND operation_key=%s AND attempt=%s", (digest, run_id, key, effect["attempt"]))
            self._event(conn, run, "EFFECT_RECONCILIATION_CLAIMED", {"key": key, "attempt": effect["attempt"], "effect_revision": effect["revision"]})
            return {**_safe(effect), "token": token}

    def reconcile_cost(self, run_id: str, attempt_id: str, receipt_id: str, actual_cost: int) -> dict:
        """Record one immutable, operator-asserted provider total for a build.

        This endpoint does not verify a provider invoice. The operator must obtain
        authoritative external evidence. Totals can replace conservative charges,
        including after a task was fenced or superseded, but cannot accept work,
        change revisions, or revive a cancelled/overrun run. Only a pause solely
        for unresolved cost can resume, after all such attempts are reconciled.
        An additional authoritative
        correction is deliberately unsupported rather than silently overwritten.
        """
        attempt_id = _text(attempt_id, "attempt_id", 128)
        receipt_id = _text(receipt_id, "receipt_id", 256)
        actual_cost = _integer(actual_cost, "actual_cost")
        payload_hash = _hash({"run_id": run_id, "attempt_id": attempt_id, "actual_cost": actual_cost})
        with self._connect() as conn:
            run = self._run(conn, run_id)
            existing = conn.execute("SELECT * FROM graphos_cost_receipts WHERE receipt_id=%s", (receipt_id,)).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise Conflict("cost receipt id reused with a different payload")
                return _safe(existing["result"])
            attempt = conn.execute("SELECT a.*,t.run_id,t.revision AS attempt_revision FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE a.id=%s", (attempt_id,)).fetchone()
            if not attempt or attempt["run_id"] != run_id or attempt["kind"] != "BUILD":
                raise Conflict("cost receipt does not identify this run's build attempt")
            if conn.execute("SELECT 1 FROM graphos_cost_receipts WHERE attempt_id=%s", (attempt_id,)).fetchone():
                raise Conflict("build attempt already has an authoritative cost receipt")
            if attempt["state"] == "ACTIVE":
                # Server-time expiry can settle an abandoned attempt. Still-live
                # work may incur more spend and cannot receive a definitive total.
                self._expire(conn, run)
                attempt = conn.execute("SELECT a.*,t.run_id,t.revision AS attempt_revision FROM graphos_attempts a JOIN graphos_tasks t ON t.id=a.task_id WHERE a.id=%s", (attempt_id,)).fetchone()
                if attempt["state"] == "ACTIVE":
                    raise Conflict("cost receipt requires a settled or expired build attempt")
            if attempt["actual_cost"] is None:
                raise Conflict("settled build attempt has no prior charge")
            previous = attempt["actual_cost"]
            delta = actual_cost - previous
            new_spent = run["spent"] + delta
            if new_spent < 0:
                raise Conflict("cost receipt would violate accounting integrity")
            overrun = actual_cost > attempt["reservation"] or new_spent + run["reserved"] > run["budget"]
            if overrun and run["state"] != "CANCELLED":
                run["state"] = "BUDGET_EXCEEDED"
            run["spent"] = new_spent
            conn.execute("UPDATE graphos_attempts SET actual_cost=%s,cost_uncertain=false WHERE id=%s", (actual_cost, attempt_id))
            conn.execute("UPDATE graphos_runs SET spent=%s,state=%s,updated_at=clock_timestamp() WHERE id=%s", (new_spent, run["state"], run_id))
            self._refresh_state(conn, run)
            result = {"run_id": run_id, "attempt_id": attempt_id, "receipt_id": receipt_id,
                      "actual_cost": actual_cost, "previous_charge": previous, "delta": delta,
                      "attempt_revision": attempt["attempt_revision"], "accounting_revision": run["revision"],
                      "spent": new_spent, "reserved": run["reserved"], "state": run["state"],
                      "source": "operator_asserted_provider_total"}
            inserted = conn.execute("INSERT INTO graphos_cost_receipts(receipt_id,run_id,attempt_id,payload_hash,actual_cost,previous_charge,delta,attempt_revision,accounting_revision,result) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(receipt_id) DO NOTHING RETURNING receipt_id", (receipt_id, run_id, attempt_id, payload_hash, actual_cost, previous, delta, attempt["attempt_revision"], run["revision"], Jsonb(result))).fetchone()
            if not inserted:
                raise Conflict("cost receipt id was concurrently used for another payload")
            if overrun:
                self._event(conn, run, "COST_OVERRUN", {"attempt_id": attempt_id, "receipt_id": receipt_id,
                            "attempt_revision": attempt["attempt_revision"], "reservation": attempt["reservation"],
                            "actual_cost": actual_cost, "spent": new_spent, "budget": run["budget"],
                            "reason": "authoritative provider total exceeded authorization"})
            self._event(conn, run, "COST_RECONCILED", result)
            return result
