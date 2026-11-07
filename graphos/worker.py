"""HTTP-only workers: explicit fixture builder, real eve adapter, isolated verifier."""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .artifacts import ArtifactError, bundle_digest, canonical, validate_digest, validate_files
from .profiles import ROOT, fixture_files, require_active
from .sandbox import ProcessError, run_bounded, verify_bundle
from .transport import WorkerError, validate_api_url

MAX_RESPONSE = 4 * 1024 * 1024
MAX_EVE_REQUEST_BYTES = 128 * 1024  # agents/eve/src/cli.ts stdin contract


class BuildFailure(WorkerError):
    def __init__(self, message: str, actual_cost: int | None = None, usage: dict | None = None):
        super().__init__(message)
        self.actual_cost = actual_cost
        self.usage = _safe_failure_usage(usage, actual_cost)


def _safe_failure_usage(value, actual_cost: int | None) -> dict | None:
    """Forward only bounded, settled receipt metadata; never arbitrary adapter output."""
    if (not isinstance(value, dict) or type(actual_cost) is not int
            or value.get("actual_cost_microdollars") != actual_cost
            or value.get("cost_source") != "eve_gateway_usage_events"):
        return None
    counts = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
              "actual_cost_microdollars", "model_runs")
    if any(type(value.get(key)) is not int or not 0 <= value[key] <= 2**53 - 1 for key in counts):
        return None
    generations = value.get("generations")
    if not 1 <= value["model_runs"] <= 3 or not isinstance(generations, list) or len(generations) != value["model_runs"]:
        return None
    result = {key: value[key] for key in counts}
    result.update(cost_source=value["cost_source"], generations=[])
    runs, ids = set(), set()
    for generation in generations:
        if not isinstance(generation, dict):
            return None
        run_id = generation.get("run_id")
        generation_id = generation.get("generation_id")
        reason = generation.get("finish_reason")
        if (not isinstance(run_id, str) or not re.fullmatch(r"run_[A-Za-z0-9_-]{1,128}", run_id)
                or run_id in runs or (generation_id is not None and
                    (not isinstance(generation_id, str) or not re.fullmatch(r"gen_[A-Za-z0-9_-]{1,128}", generation_id)
                     or generation_id in ids))
                or (reason is not None and not isinstance(reason, str))
                or reason not in {None, "stop", "length", "content-filter", "tool-calls", "error", "other", "unknown"}):
            return None
        runs.add(run_id)
        if generation_id:
            ids.add(generation_id)
        result["generations"].append({"run_id": run_id, "generation_id": generation_id, "finish_reason": reason})
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _request(api_url: str, token: str, path: str, data: dict | None = None, *,
             lease_headers: dict[str, str] | None = None):
    try:
        api_url = validate_api_url(api_url)
    except ValueError:
        raise WorkerError("invalid API URL; remote connections require HTTPS") from None
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if lease_headers:
        headers.update(lease_headers)
    request = urllib.request.Request(api_url.rstrip("/") + "/v1" + path,
                                     data=None if data is None else canonical(data),
                                     headers=headers,
                                     method="GET" if data is None else "POST")
    try:
        # Control-plane bearer/lease tokens must not traverse an ambient proxy,
        # including a loopback request when NO_PROXY is missing or incomplete.
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect).open(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise WorkerError("API response exceeded size limit")
        return json.loads(body)
    except urllib.error.HTTPError as exc:
        raise WorkerError(f"API request rejected with HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise WorkerError("API request could not complete") from None
    except (ValueError, UnicodeError) as exc:
        raise WorkerError("API response was not valid JSON") from exc


def _segment(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _identity(claim: dict) -> dict:
    return {key: claim[key] for key in ("token", "epoch", "revision", "input_hash")}


def _lease_headers(run_id: str, claim: dict) -> dict[str, str]:
    return {"X-GraphOS-Run-Id": run_id, "X-GraphOS-Task-Id": claim["task_id"],
            "X-GraphOS-Lease-Token": claim["token"], "X-GraphOS-Lease-Epoch": str(claim["epoch"])}


def _eve_environment() -> dict[str, str]:
    if not os.environ.get("GRAPHOS_EVE_TOKEN"):
        raise WorkerError("eve requires GRAPHOS_EVE_TOKEN for its configured server; fixture fallback is disabled")
    # Model credentials stay in the eve server. No broker, DB or cloud credentials.
    allowed = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "NODE_EXTRA_CA_CERTS",
               "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
               "https_proxy", "http_proxy", "no_proxy", "GRAPHOS_EVE_TOKEN", "EVE_SERVER_URL"}
    return {name: value for name, value in os.environ.items() if name in allowed}


def _eve_build(claim: dict, profile: dict, dependencies: list[dict], repair: dict | None = None) -> dict:
    environment = _eve_environment()
    command = ["node", str(ROOT / "agents" / "eve" / "dist" / "src" / "cli.js")]
    # The resolved top-level context carries the same diagnostics as the claim.
    # Avoid doubling it, while preserving the original claim for ledger calls.
    request = {"claim": {key: value for key, value in claim.items() if key != "repair"},
               "profile": profile, "dependencies": dependencies}
    if repair is not None:
        request["repair"] = repair
    try:
        encoded = canonical(request)
    except ArtifactError as exc:
        raise BuildFailure("eve request could not be serialized before generation", actual_cost=0) from exc
    # Check serialized bytes, including JSON escaping and UTF-8 expansion. Never
    # truncate candidate files: that would break their evidence/hash binding.
    if len(encoded) > MAX_EVE_REQUEST_BYTES:
        raise BuildFailure("eve request exceeds the 128 KiB adapter input limit before generation", actual_cost=0)
    code, stdout, stderr = run_bounded(command, stdin=encoded, timeout=150,
                                  output_limit=3 * 1024 * 1024, env=environment,
                                  cwd=ROOT / "agents" / "eve")
    if code:
        known_cost = None
        failure_usage = None
        failure_code = "unclassified_adapter_failure"
        try:
            error = json.loads(stderr)
            # Preserve actionable adapter failures, never raw provider messages.
            allowed_codes = {"invalid_generated_files", "eve_turn_not_completed",
                             "reservation_exceeded", "unreconciled_model_usage",
                             "eve_timeout", "eve_transport_or_runtime_error",
                             "invalid_task_contract", "request_too_large", "response_too_large"}
            if (isinstance(error, dict) and isinstance(error.get("error"), str)
                    and error["error"] in allowed_codes):
                failure_code = error["error"]
            if (isinstance(error, dict) and error.get("cost_known") is True
                    and type(error.get("actual_cost_microdollars")) is int
                    and error["actual_cost_microdollars"] >= 0):
                known_cost = error["actual_cost_microdollars"]
                failure_usage = _safe_failure_usage(error.get("usage"), known_cost)
        except (ValueError, UnicodeError):
            pass
        raise BuildFailure(f"eve adapter failed ({failure_code}); no fixture fallback was attempted", known_cost, failure_usage)
    try:
        output = json.loads(stdout)
    except (ValueError, UnicodeError) as exc:
        raise WorkerError("eve adapter did not return valid JSON") from exc
    if not isinstance(output, dict) or not isinstance(output.get("usage"), dict):
        raise WorkerError("eve adapter returned an invalid result")
    cost = output["usage"].get("actual_cost_microdollars")
    if type(cost) is not int or cost < 0:
        raise WorkerError("eve usage did not satisfy the reserved cost contract")
    if cost > claim["reservation"]:
        raise BuildFailure("provider-reported cost exceeded its reservation; dispatch must halt", cost)
    try:
        validate_files(output.get("files"))
        if not isinstance(output.get("provenance"), dict) or output["provenance"].get("mode") != "eve":
            raise WorkerError("live adapter did not attest eve provenance")
    except (ArtifactError, WorkerError) as exc:
        raise BuildFailure(str(exc), cost) from exc
    return output


def build_once(api_url: str, token: str, run_id: str, builder: str = "fixture",
               worker_id: str = "builder", *, reserve: int | None = None,
               lease_seconds: int = 300) -> dict:
    if builder not in {"fixture", "eve"}:
        raise WorkerError("builder must be explicitly fixture or eve")
    if builder == "eve":
        _eve_environment()  # reject absent auth before reserving work
    if reserve is None:
        reserve = 1 if builder == "fixture" else int(os.environ.get("GRAPHOS_BUILD_RESERVATION", "1000000"))
    if type(reserve) is not int or reserve <= 0:
        raise WorkerError("a positive integer reservation is required")
    route = "/runs/" + _segment(run_id)
    claim = _request(api_url, token, route + "/claim/build",
                     {"worker_id": worker_id, "reserve": reserve, "lease_seconds": lease_seconds})
    if claim is None:
        return {"status": "idle", "claim": None}
    task_route = route + "/tasks/" + _segment(claim["task_id"])
    model_started = False
    try:
        profile = require_active(claim["profile"])
        if (claim["suite_hash"] != profile["suite_hash"] or claim["policy_hash"] != profile["policy_hash"]
                or claim["requirements"] != profile["acceptance_criteria"]):
            raise WorkerError("claimed task does not match the installed trusted profile")
        if builder == "fixture":
            output = {"files": fixture_files(claim["profile"]), "usage": {"actual_cost_microdollars": 0},
                      "provenance": {"mode": "fixture", "fixture": f"{profile['id']}-v{profile['version']}",
                                     "ai_generated": False}}
        else:
            dependencies = []
            dependency_refs = claim.get("dependencies", [])
            if isinstance(dependency_refs, dict):
                dependency_refs = list(dependency_refs.values())
            for dependency in dependency_refs:
                digest = dependency if isinstance(dependency, str) else dependency["candidate_hash"]
                validate_digest(digest)
                bundle = _request(api_url, token, "/artifacts/" + digest,
                                  lease_headers=_lease_headers(run_id, claim))
                validate_files(bundle["files"])
                if bundle.get("manifest_hash") != digest or bundle_digest(bundle["files"]) != digest:
                    raise WorkerError("dependency content does not match its accepted manifest")
                dependencies.append({"candidate_hash": digest, "files": bundle["files"]})
            repair = claim.get("repair")
            if repair is not None:
                if (not isinstance(repair, dict)
                        or any(repair.get(key) != claim[key] for key in
                               ("revision", "input_hash", "suite_hash", "policy_hash"))):
                    raise WorkerError("repair feedback does not match the current input")
                digest = validate_digest(repair["candidate_hash"])
                bundle = _request(api_url, token, "/artifacts/" + digest,
                                  lease_headers=_lease_headers(run_id, claim))
                validate_files(bundle["files"])
                if bundle.get("manifest_hash") != digest or bundle_digest(bundle["files"]) != digest:
                    raise WorkerError("repair candidate content does not match its rejected manifest")
                repair = {**repair, "files": bundle["files"]}
            model_started = True
            output = _eve_build(claim, profile, dependencies, repair)
        payload = {**_identity(claim), "files": output["files"],
                   "actual_cost": output["usage"]["actual_cost_microdollars"],
                   "provenance": {**output["provenance"], "usage": output["usage"]}}
    except (WorkerError, ArtifactError, ProcessError, OSError, KeyError, ValueError) as exc:
        # Live work may have incurred unreported spend. Never refund uncertainty.
        charge = (exc.actual_cost if isinstance(exc, BuildFailure) and exc.actual_cost is not None
                  else claim["reservation"] if model_started else 0)
        cost_known = not model_started or (isinstance(exc, BuildFailure) and exc.actual_cost is not None)
        result = _request(api_url, token, task_route + "/fail",
                          {"token": claim["token"], "epoch": claim["epoch"],
                           "reason": str(exc)[:300], "actual_cost": charge, "cost_known": cost_known})
        return {"status": "failed", "claim": claim, "result": result,
                "reason": str(exc)[:300], "provenance": {"mode": builder},
                **({"usage": exc.usage} if isinstance(exc, BuildFailure) and exc.usage else {})}
    # A transport failure here is ambiguous: do not issue a compensating fail.
    result = _request(api_url, token, task_route + "/submit", payload)
    return {"status": "submitted", "claim": claim, "result": result,
            "provenance": output["provenance"], "usage": output["usage"]}


def verify_once(api_url: str, token: str, run_id: str, worker_id: str = "verifier", *,
                lease_seconds: int = 180) -> dict:
    route = "/runs/" + _segment(run_id)
    claim = _request(api_url, token, route + "/claim/verify",
                     {"worker_id": worker_id, "lease_seconds": lease_seconds})
    if claim is None:
        return {"status": "idle", "claim": None}
    profile = require_active(claim["profile"])
    if claim["suite_hash"] != profile["suite_hash"] or claim["policy_hash"] != profile["policy_hash"]:
        raise WorkerError("claimed verification suite differs from the installed trusted suite")
    digest = validate_digest(claim["candidate_hash"])
    bundle = _request(api_url, token, "/artifacts/" + digest,
                      lease_headers=_lease_headers(run_id, claim))
    if bundle.get("manifest_hash") != digest or bundle_digest(bundle["files"]) != digest:
        raise WorkerError("API returned a different candidate manifest")
    report = verify_bundle(bundle["files"], claim["requirements"], profile_id=claim["profile"])
    payload = {**_identity(claim), "candidate_hash": digest,
               "suite_hash": claim["suite_hash"], "policy_hash": claim["policy_hash"],
               "passed": report["passed"], "report": report}
    result = _request(api_url, token, route + "/tasks/" + _segment(claim["task_id"]) + "/verify", payload)
    return {"status": "verified", "passed": report["passed"], "report": report,
            "claim": claim, "result": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("run_id")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--worker-id")
    parser.add_argument("--builder", choices=("fixture", "eve"), default="fixture")
    parser.add_argument("--reserve", type=int)
    args = parser.parse_args()
    role = "BUILDER" if args.mode == "build" else "VERIFIER"
    token = os.environ.get("GRAPHOS_" + role + "_TOKEN")
    if not token:
        parser.error(f"GRAPHOS_{role}_TOKEN is required")
    try:
        if args.mode == "build":
            result = build_once(args.api_url, token, args.run_id, args.builder,
                                args.worker_id or "builder", reserve=args.reserve)
        else:
            result = verify_once(args.api_url, token, args.run_id, args.worker_id or "verifier")
    except (WorkerError, ProcessError, ArtifactError) as exc:
        parser.exit(1, str(exc) + "\n")
    # Lease tokens are intentionally not printed to logs.
    print(json.dumps({key: value for key, value in result.items() if key not in {"claim", "result"}}))


if __name__ == "__main__":
    main()
