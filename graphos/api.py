"""Single-tenant control API. Generated applications never execute on this origin."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .artifacts import ArtifactError, ArtifactStore
from .config import Settings
from .ledger import Conflict, Ledger
from .profiles import default_spec, get_profile

Nonnegative = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
Digest = Annotated[str, Field(pattern=r"^(sha256:)?[0-9a-f]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=20000)


class TaskSpec(Record):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    objective: str = Field(min_length=1, max_length=10000)
    depends_on: list[str] = Field(default_factory=list, max_length=256)


class RunSpec(Record):
    name: str = Field(min_length=1, max_length=200)
    profile: str = "static-web"
    requirements: list[str] = Field(default_factory=list, max_length=100)
    tasks: list[TaskSpec] = Field(min_length=1, max_length=256)
    suite_hash: Digest | None = None
    policy_hash: Digest | None = None
    max_attempts: int = Field(default=3, strict=True, ge=1, le=10)


class Admission(Record):
    spec: RunSpec
    budget: int = Field(strict=True, ge=1, le=5_000_000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class Revision(Record):
    spec: RunSpec
    expected_revision: int = Field(strict=True, ge=1)


class Claim(Record):
    worker_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    lease_seconds: int = Field(default=300, strict=True, ge=1, le=3600)


class BuildClaim(Claim):
    reserve: Nonnegative = 1_000_000


class Binding(Record):
    token: str = Field(min_length=1, max_length=256)
    epoch: int = Field(strict=True, ge=1)
    revision: int = Field(strict=True, ge=1)
    input_hash: Digest


class BuildResult(Binding):
    files: dict[str, str]
    actual_cost: Nonnegative
    provenance: dict[str, Any]


class BuildFailure(Record):
    token: str = Field(min_length=1, max_length=256)
    epoch: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    actual_cost: Nonnegative
    cost_known: StrictBool = False


class Verification(Binding):
    candidate_hash: Digest
    suite_hash: Digest
    policy_hash: Digest
    passed: StrictBool
    report: dict[str, Any]


class Effect(Record):
    key: str = Field(min_length=1, max_length=200)
    payload_hash: Digest
    receiver_deduplicates: StrictBool = False


class EffectKey(Record):
    key: str = Field(min_length=1, max_length=200)


class Resolution(EffectKey):
    attempt: int = Field(strict=True, ge=1)
    token: str = Field(min_length=1, max_length=256)
    outcome: Literal["CONFIRMED", "UNKNOWN", "NOT_APPLIED"]


class CostReceipt(Record):
    attempt_id: UUID
    receipt_id: str = Field(min_length=1, max_length=200)
    actual_cost: Nonnegative


class BodyLimitMiddleware:
    """Bound actual received bytes, including chunked requests, before parsing."""
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"detail": "Request body too large"}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    ledger = Ledger(settings.database_url)
    store = ArtifactStore(settings.artifact_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ledger.migrate()
        yield

    app = FastAPI(title="GraphOS", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ledger, app.state.store, app.state.settings = ledger, store, settings
    app.add_middleware(BodyLimitMiddleware, limit=settings.max_body_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"
        )
        return response

    def principal(authorization: Annotated[str | None, Header()] = None) -> str:
        candidate = authorization.removeprefix("Bearer ") if authorization else ""
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        for role in ("operator", "builder", "verifier"):
            if secrets.compare_digest(candidate.encode(), getattr(settings, f"{role}_token").encode()):
                return role
        raise HTTPException(401, "Invalid credential")

    def require(role: str):
        def dependency(actual: str = Depends(principal)):
            if actual != role:
                raise HTTPException(403, f"{role} role required")
            return actual
        return dependency

    operator = require("operator")
    builder = require("builder")
    verifier = require("verifier")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": [
            {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]}, 422)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(ArtifactError)
    async def artifact_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 422)

    def normalized(spec: RunSpec) -> dict:
        try:
            profile = get_profile(spec.profile)
        except (KeyError, ValueError) as exc:
            raise HTTPException(422, "Unknown capability profile") from exc
        if profile["status"] != "active":
            raise HTTPException(422, "This capability profile is not implemented or verified")
        criteria = profile["acceptance_criteria"]
        if spec.requirements and spec.requirements != criteria:
            raise HTTPException(422, "Requirements must match the registered profile contract; "
                                "additional behavior needs a new versioned verification profile")
        value = spec.model_dump()
        if value["tasks"] != default_spec()["tasks"]:
            raise HTTPException(422, "This profile supports only its registered task and objective; "
                                "a new task contract needs its own verifier")
        for key in ("suite_hash", "policy_hash"):
            if value[key] and value[key].removeprefix("sha256:") != profile[key]:
                raise HTTPException(409, f"{key} does not match the current profile")
            value[key] = profile[key]
        value["requirements"] = criteria
        return value

    def run_result(value: dict) -> dict:
        if "run_id" not in value and "id" in value:
            value["run_id"] = value["id"]
        if "spec" in value:
            profile = get_profile(value["spec"]["profile"])
            value["evidence_current"] = all(value["spec"][key] == profile[key]
                                            for key in ("suite_hash", "policy_hash"))
            if not value["evidence_current"]:
                value["revalidation_required"] = "Registered verification suite or policy changed"
        return value

    def current_profile(run_id: str) -> tuple[dict, dict]:
        value = ledger.get_run(run_id)
        profile = get_profile(value["spec"]["profile"])
        if profile["status"] != "active" or any(value["spec"][key] != profile[key]
                                                for key in ("suite_hash", "policy_hash")):
            raise HTTPException(409, "Verification suite or policy changed; revise the run before continuing")
        return value, profile

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/readyz", dependencies=[Depends(operator)])
    def ready():
        ledger.list_runs()
        return {"status": "ready", "storage": "postgresql", "fixture_enabled": settings.allow_fixture}

    @app.get("/v1/profiles", dependencies=[Depends(operator)])
    def profiles():
        items = [get_profile(name) for name in
                 ("static-web", "games", "bots", "data", "media", "trading-research")]
        items[0]["task_template"] = default_spec()["tasks"]
        return items

    @app.post("/v1/runs", dependencies=[Depends(operator)], status_code=201)
    def create(body: Admission):
        return run_result(ledger.create_run(normalized(body.spec), body.budget, body.idempotency_key))

    @app.get("/v1/runs", dependencies=[Depends(operator)])
    def runs():
        return [run_result(r) for r in ledger.list_runs()]

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(operator)])
    def run(run_id: UUID):
        return run_result(ledger.get_run(str(run_id)))

    @app.post("/v1/runs/{run_id}/revise", dependencies=[Depends(operator)])
    def revise(run_id: UUID, body: Revision):
        return run_result(ledger.revise_run(str(run_id), normalized(body.spec), body.expected_revision))

    @app.post("/v1/runs/{run_id}/cancel", dependencies=[Depends(operator)])
    def cancel(run_id: UUID):
        return run_result(ledger.cancel_run(str(run_id)))

    @app.post("/v1/runs/{run_id}/claim/build", dependencies=[Depends(builder)])
    def claim_build(run_id: UUID, body: BuildClaim):
        current_profile(str(run_id))
        return ledger.claim_build(str(run_id), f"builder:{body.worker_id}",
                                  body.reserve, body.lease_seconds)

    @app.post("/v1/runs/{run_id}/claim/verify", dependencies=[Depends(verifier)])
    def claim_verify(run_id: UUID, body: Claim):
        current_profile(str(run_id))
        return ledger.claim_verify(str(run_id), f"verifier:{body.worker_id}", body.lease_seconds)

    @app.post("/v1/runs/{run_id}/tasks/{task_id}/submit", dependencies=[Depends(builder)])
    def submit(run_id: UUID, task_id: UUID, body: BuildResult):
        mode = body.provenance.get("mode")
        if mode not in {"fixture", "eve"}:
            raise HTTPException(422, "Explicit supported builder provenance is required")
        if mode == "fixture" and not settings.allow_fixture:
            raise HTTPException(403, "Fixture mode is disabled for this service")
        candidate = store.put_bundle(body.files)
        return ledger.submit_build(str(run_id), str(task_id), body.token, body.epoch,
                                   body.revision, body.input_hash, candidate,
                                   body.actual_cost, body.provenance)

    @app.post("/v1/runs/{run_id}/tasks/{task_id}/fail", dependencies=[Depends(builder)])
    def fail(run_id: UUID, task_id: UUID, body: BuildFailure):
        return ledger.fail_build(str(run_id), str(task_id), body.token, body.epoch,
                                 body.reason, body.actual_cost, cost_known=body.cost_known)

    @app.post("/v1/runs/{run_id}/tasks/{task_id}/verify", dependencies=[Depends(verifier)])
    def verify(run_id: UUID, task_id: UUID, body: Verification):
        _, profile = current_profile(str(run_id))
        store.get_bundle(body.candidate_hash.removeprefix("sha256:"))
        report = body.report
        if type(report.get("passed")) is not bool or report["passed"] != body.passed:
            raise HTTPException(422, "Evidence report outcome does not match submission")
        checks = report.get("checks", [])
        if not isinstance(checks, list) or not checks:
            raise HTTPException(422, "Evidence must include executed checks")
        if body.passed and any(not isinstance(c, dict) or c.get("passed") is not True for c in checks):
            raise HTTPException(422, "Passing evidence contains failed or invalid checks")
        if body.passed and (
            [c.get("name") for c in checks] != profile["required_checks"]
            or report.get("suite_hash") != profile["suite_hash"]
            or report.get("policy_hash") != profile["policy_hash"]
            or report.get("runner") != "docker-trusted-playwright-static-web-v1"
            or not isinstance(report.get("image_id"), str)
            or not report["image_id"].startswith("sha256:")
        ):
            raise HTTPException(422, "Passing evidence must cover the complete trusted profile suite")
        evidence_hash = store.put_json(report)
        return ledger.submit_verification(str(run_id), str(task_id), body.token, body.epoch,
                                          body.revision, body.input_hash, body.candidate_hash,
                                          body.suite_hash, body.policy_hash, body.passed,
                                          evidence_hash, report)

    @app.get("/v1/artifacts/{digest}")
    def artifact(digest: Digest, role: str = Depends(principal),
                 run_id: Annotated[str | None, Header(alias="X-GraphOS-Run-Id")] = None,
                 task_id: Annotated[str | None, Header(alias="X-GraphOS-Task-Id")] = None,
                 token: Annotated[str | None, Header(alias="X-GraphOS-Lease-Token")] = None,
                 epoch: Annotated[int | None, Header(alias="X-GraphOS-Lease-Epoch")] = None):
        key = digest.removeprefix("sha256:")
        if role != "operator":
            if not all((run_id, task_id, token, epoch)):
                raise HTTPException(403, "An active scoped worker lease is required")
            ledger.authorize_artifact(run_id, task_id, token, epoch, key,
                                      "BUILD" if role == "builder" else "VERIFY")
        return {"manifest_hash": key, "files": store.get_bundle(key)}

    @app.get("/v1/runs/{run_id}/release", dependencies=[Depends(operator)])
    def release(run_id: UUID):
        run, _ = current_profile(str(run_id))
        # Recompute bytes at delivery; an intact DB reference cannot certify corrupt storage.
        for task in run["tasks"]:
            if task.get("candidate_hash"):
                store.get_bundle(task["candidate_hash"])
            if task.get("evidence_hash"):
                store.get_json(task["evidence_hash"])
        result = ledger.release_manifest(str(run_id), expected_revision=run["revision"],
                                         expected_spec_hash=run["spec_hash"])
        result["deployment_performed"] = False
        result["scope"] = "Acceptance applies only to the registered capability profile"
        result["fixture_enabled_on_service"] = settings.allow_fixture
        return result

    @app.post("/v1/runs/{run_id}/effects", dependencies=[Depends(operator)])
    def prepare_effect(run_id: UUID, body: Effect):
        return ledger.prepare_effect(str(run_id), body.key, body.payload_hash, body.receiver_deduplicates)

    @app.post("/v1/runs/{run_id}/effects/begin", dependencies=[Depends(operator)])
    def begin_effect(run_id: UUID, body: EffectKey):
        return ledger.begin_effect(str(run_id), body.key)

    @app.post("/v1/runs/{run_id}/effects/reconcile-claim", dependencies=[Depends(operator)])
    def claim_effect_reconciliation(run_id: UUID, body: EffectKey):
        return ledger.claim_effect_reconciliation(str(run_id), body.key)

    @app.post("/v1/runs/{run_id}/effects/resolve", dependencies=[Depends(operator)])
    def resolve_effect(run_id: UUID, body: Resolution):
        return ledger.resolve_effect(str(run_id), body.key, body.attempt, body.token, body.outcome)

    @app.post("/v1/runs/{run_id}/costs/reconcile", dependencies=[Depends(operator)])
    def reconcile_cost(run_id: UUID, body: CostReceipt):
        return ledger.reconcile_cost(str(run_id), str(body.attempt_id), body.receipt_id, body.actual_cost)

    static = Path(__file__).parent / "static"
    if static.exists():
        app.mount("/static", StaticFiles(directory=static), name="static")

        @app.get("/")
        def index():
            return FileResponse(static / "index.html")

    return app
