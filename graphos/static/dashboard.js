"use strict";

(() => {
  // Credentials are deliberately ephemeral: no storage, URL parameters, or cookies.
  let operatorToken = "";
  let profiles = [];
  let runs = [];
  let selectedRun = null;
  let connected = false;
  let requestGeneration = 0;
  let admissionKey = null;
  const $ = (id) => document.getElementById(id);
  const money = (units) => new Intl.NumberFormat(undefined, {
    style: "currency", currency: "USD", minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(Number(units || 0) / 1000000);
  const identifier = (run) => run.run_id || run.id;
  const profileId = (profile) => profile.id || profile.name;
  const array = (value, key) => Array.isArray(value) ? value : (Array.isArray(value?.[key]) ? value[key] : []);
  const isActive = (profile) => profile.status === "active" || profile.status === "ACTIVE";
  const canonicalTasks = [{ key: "app", objective: "Build a polished task-list app satisfying every fixed static-web profile requirement.", depends_on: [] }];
  function taskTemplate(profile) {
    if (Array.isArray(profile?.task_template) && profile.task_template.length) return structuredClone(profile.task_template);
    if (profileId(profile) === "static-web") return structuredClone(canonicalTasks);
    throw new Error("This profile does not supply a registered task template.");
  }
  const stateName = (state) => String(state || "UNKNOWN").replaceAll("_", " ");
  const stateClass = (state) => {
    const normalized = String(state || "").toUpperCase();
    if (["ACCEPTED", "VERIFIED", "COMPLETED", "SUCCEEDED", "READY_FOR_RELEASE", "RELEASED"].includes(normalized)) return "success";
    if (["EXHAUSTED", "FAILED", "REJECTED", "CANCELLED", "BUDGET_EXCEEDED"].includes(normalized)) return "failure";
    if (["RUNNING", "BUILDING", "VERIFYING", "SUBMITTED", "CLAIMED", "STALE", "BLOCKED", "RECONCILIATION_REQUIRED"].includes(normalized)) return "warning";
    return "neutral";
  };
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function notify(message, error = false) {
    $("notice").textContent = message;
    $("notice").className = error ? "notice error" : "notice";
    $("notice").hidden = !message;
  }
  function formError(id, error) {
    $(id).textContent = error ? error.message : "";
    $(id).hidden = !error;
  }
  function setConnection(value) {
    connected = value;
    $("connection-dot").classList.toggle("connected", value);
    $("connection-label").textContent = value ? "Workspace connected" : "Not connected";
    $("connect-button").hidden = value;
    $("disconnect-button").hidden = !value;
    $("operator-token").hidden = value;
    $("operator-token").disabled = value;
    $("refresh-button").disabled = !value;
    $("new-run-button").disabled = !value || !profiles.some(isActive);
  }
  async function api(path, method = "GET", body) {
    if (!operatorToken) throw new Error("Connect with an operator token first.");
    const options = {
      method, credentials: "omit", redirect: "error", cache: "no-store",
      headers: { Authorization: `Bearer ${operatorToken}` },
      signal: AbortSignal.timeout(20000),
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try { response = await fetch(`/v1${path}`, options); }
    catch (error) {
      if (error.name === "TimeoutError") throw new Error("The request timed out. Refresh the run before retrying a change.");
      throw new Error("Cannot reach GraphOS. Check the service and try again.");
    }
    let data = null;
    try { data = await response.json(); } catch { /* Generic status message below. */ }
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) throw new Error("Operator access was denied. Check your token and its role.");
      let detail = data?.detail || data?.error || `Request failed (${response.status}).`;
      if (typeof detail !== "string") detail = "The request did not match the required format. Check the fields and try again.";
      throw new Error(detail.slice(0, 500));
    }
    return data;
  }
  function renderProfiles() {
    const list = $("profiles-list");
    list.replaceChildren();
    $("profile-input").replaceChildren();
    for (const profile of profiles) {
      const active = isActive(profile);
      const card = el("article", null, `profile-card${active ? " active-profile" : ""}`);
      const top = el("div", null, "profile-top");
      top.append(el("h3", profileId(profile).replaceAll("-", " ")), el("span", active ? "Available" : "Contract only", `badge ${active ? "success" : "neutral"}`));
      card.append(top, el("p", profile.description || (active ? "Executable browser acceptance checks." : "Defined requirements; execution is not enabled.")));
      const criteria = profile.acceptance_criteria || [];
      if (criteria.length) {
        const details = el("details");
        const ul = el("ul");
        for (const criterion of criteria) ul.append(el("li", typeof criterion === "string" ? criterion : (criterion.description || criterion.name || JSON.stringify(criterion))));
        details.append(el("summary", "Acceptance criteria"), ul); card.append(details);
      }
      list.append(card);
      if (active) {
        const option = el("option", profileId(profile).replaceAll("-", " "));
        option.value = profileId(profile); $("profile-input").append(option);
      }
    }
    if (!profiles.length) list.append(el("p", "No capability profiles were returned.", "muted"));
    updateProfileRequirements();
  }
  function updateProfileRequirements() {
    const profile = profiles.find((item) => profileId(item) === $("profile-input").value);
    const criteria = profile?.acceptance_criteria || [];
    $("requirements-input").value = criteria.map((item) => typeof item === "string" ? item : (item.description || item.name || JSON.stringify(item))).join("\n");
    $("objective-input").value = profile ? taskTemplate(profile).map((task) => task.objective).join("\n") : "";
    $("profile-contract-note").textContent = profile ? "The registered objective and fixed task-list behaviors define this profile. Arbitrary objectives are not accepted, and aesthetic preferences are not certified by these checks." : "No executable profile is available.";
  }
  function renderRuns() {
    const list = $("runs-list"); list.replaceChildren();
    $("run-count").textContent = runs.length;
    for (const run of runs) {
      const button = el("button", null, `run-card${selectedRun && identifier(selectedRun) === identifier(run) ? " selected" : ""}`);
      button.type = "button";
      button.setAttribute("aria-pressed", String(Boolean(selectedRun && identifier(selectedRun) === identifier(run))));
      button.append(el("strong", run.name || run.spec?.name || identifier(run)));
      const meta = el("span", null, "run-meta");
      meta.append(el("span", stateName(run.state), `badge ${stateClass(run.state)}`), el("span", `rev ${run.revision || 1}`));
      button.append(meta);
      button.addEventListener("click", () => selectRun(identifier(run)).catch((error) => notify(error.message, true)));
      list.append(button);
    }
    if (!runs.length) list.append(el("p", connected ? "No runs yet. Create one with a clear outcome and acceptance criteria." : "Connect to load your runs.", "empty-state"));
  }
  function binding(container, label, value) {
    const row = el("div"); row.append(el("dt", label), el("dd", value || "Not yet recorded", "mono digest")); container.append(row);
  }
  function renderTasks(tasks) {
    const list = $("tasks-list"); list.replaceChildren();
    $("task-count").textContent = `${tasks.filter((task) => task.state === "ACCEPTED").length} / ${tasks.length} accepted`;
    for (const task of tasks) {
      const card = el("article", null, "task-card");
      const top = el("div", null, "task-top");
      top.append(el("strong", task.task_key || task.key || task.task_id || task.id, "task-title"), el("span", stateName(task.state), `badge ${stateClass(task.state)}`));
      const meta = el("div", null, "task-meta");
      const submitted = (selectedRun?.events || []).slice().reverse().find((event) =>
        event.kind === "BUILD_SUBMITTED" && event.payload?.task_id === (task.task_id || task.id) &&
        event.payload?.candidate_hash === task.candidate_hash);
      const provenance = task.provenance || task.result?.provenance || submitted?.payload?.provenance || {};
      const mode = provenance.mode || provenance.builder || provenance.provider || "Not recorded";
      meta.append(el("span", `Attempts: ${task.attempts ?? task.build_attempts ?? 0}`), el("span", `Origin: ${mode}`));
      card.append(top, el("p", task.objective || "", "task-objective"), meta);
      const current = task.state === "ACCEPTED" && Boolean(task.evidence_hash);
      card.append(el("p", current ? "Current acceptance evidence recorded" : "No current acceptance certificate", "evidence-label"));
      const bindings = el("dl", null, "binding-list");
      binding(bindings, "Candidate", task.candidate_hash);
      binding(bindings, "Input manifest", task.input_hash);
      binding(bindings, "Evidence", task.evidence_hash);
      card.append(bindings);
      const report = task.report || task.verification?.report;
      if (report) {
        const details = el("details"); details.append(el("summary", "Verification report"), el("pre", JSON.stringify(report, null, 2), "json-content")); card.append(details);
      }
      list.append(card);
    }
    if (!tasks.length) list.append(el("p", "No tasks were returned for this run.", "muted"));
  }
  function renderEvents(events) {
    const list = $("events-list"); list.replaceChildren();
    for (const event of events.slice().reverse()) {
      const item = el("li"); const heading = el("div", null, "event-heading");
      const name = event.kind || event.type || event.event_type || "event";
      const timestamp = event.created_at || event.timestamp;
      const time = el("time", timestamp ? new Date(timestamp).toLocaleString() : "");
      if (timestamp && !Number.isNaN(new Date(timestamp).getTime())) time.dateTime = new Date(timestamp).toISOString();
      heading.append(el("strong", stateName(name).toLowerCase()), time); item.append(heading);
      const payload = event.payload || event.data || {};
      const detailParts = [];
      if (event.task_id || payload.task_id) detailParts.push(`Task ${event.task_id || payload.task_id}`);
      if (payload.revision !== undefined) detailParts.push(`revision ${payload.revision}`);
      if (payload.reason) detailParts.push(String(payload.reason).slice(0, 300));
      if (detailParts.length) item.append(el("div", detailParts.join(" · "), "event-detail"));
      list.append(item);
    }
    if (!events.length) list.append(el("li", "No events were returned.", "muted small-copy"));
  }
  function renderDetail(run) {
    $("detail-empty").hidden = true; $("detail-content").hidden = false;
    $("run-name").textContent = run.name || run.spec?.name || "Untitled run";
    $("run-id").textContent = identifier(run);
    $("run-profile").textContent = `${run.profile || run.spec?.profile || "Unknown profile"} · Run detail`;
    $("run-state").textContent = stateName(run.state);
    $("run-state").className = `badge ${stateClass(run.state)}`;
    $("budget-value").textContent = money(run.budget);
    $("spent-value").textContent = money(run.spent);
    $("reserved-value").textContent = money(run.reserved);
    $("revision-value").textContent = run.revision || 1;
    const tasks = run.tasks || [];
    const allAccepted = tasks.length > 0 && tasks.every((task) => task.state === "ACCEPTED");
    const cancelled = run.state === "CANCELLED";
    const releasable = allAccepted && ["READY_FOR_RELEASE", "RELEASED"].includes(run.state);
    $("release-button").disabled = !releasable;
    $("cancel-button").disabled = cancelled;
    $("revise-button").disabled = cancelled || !run.spec;
    let note = "Queued — a configured worker is required to execute this run. Creating a run does not start a model call.";
    if (cancelled) note = "Cancelled. Historical artifacts remain available; older attempts cannot submit new results.";
    else if (run.state === "RECONCILIATION_REQUIRED") note = "Dispatch is paused because an external request or its cost is unresolved. Reconcile authoritative provider results and costs before resuming work.";
    else if (run.state === "BUDGET_EXCEEDED") note = "The run’s budget is exhausted or exceeded. Further dispatch is blocked; review recorded usage and outstanding costs.";
    else if (releasable) note = "Every task is accepted. The release endpoint checks current evidence before issuing a manifest.";
    else if (tasks.some((task) => ["RUNNING", "BUILDING", "VERIFYING", "CLAIMED"].includes(task.state))) note = "Work is in progress. Use Refresh to inspect the latest recorded state.";
    else if (tasks.some((task) => task.state === "SUBMITTED")) note = "A candidate is waiting for independent verification. Submission alone does not establish acceptance.";
    else if (tasks.some((task) => task.state === "EXHAUSTED")) note = "An attempt limit was reached. Inspect the recorded failures before revising the specification or continuing.";
    $("run-progress-note").textContent = note;
    $("requirements-list").replaceChildren(...(run.spec?.requirements || []).map((requirement) => el("li", requirement)));
    $("spec-hash").textContent = run.spec_hash || "Not recorded";
    $("suite-hash").textContent = run.spec?.suite_hash || run.suite_hash || "Not recorded";
    $("policy-hash").textContent = run.spec?.policy_hash || run.policy_hash || "Not recorded";
    renderTasks(tasks); renderEvents(run.events || []);
  }
  async function selectRun(id) {
    const generation = ++requestGeneration;
    $("run-detail").setAttribute("aria-busy", "true");
    try {
      const run = await api(`/runs/${encodeURIComponent(id)}`);
      if (generation !== requestGeneration || !connected) return;
      selectedRun = run; renderDetail(run); renderRuns();
    } finally {
      if (generation === requestGeneration) $("run-detail").setAttribute("aria-busy", "false");
    }
  }
  async function refresh() {
    $("refresh-button").disabled = true;
    try {
      const generation = requestGeneration;
      const response = await api("/runs");
      if (generation !== requestGeneration || !connected) return;
      runs = array(response, "runs"); renderRuns();
      if (selectedRun) await selectRun(identifier(selectedRun));
    } finally { $("refresh-button").disabled = !connected; }
  }
  $("connect-form").addEventListener("submit", async (event) => {
    event.preventDefault(); $("connect-button").disabled = true; notify("");
    operatorToken = $("operator-token").value.trim();
    try {
      const [profileResponse, runResponse] = await Promise.all([api("/profiles"), api("/runs")]);
      profiles = array(profileResponse, "profiles"); runs = array(runResponse, "runs");
      $("operator-token").value = ""; renderProfiles(); setConnection(true); renderRuns();
      notify("Connected. Choose a run or create a new one.");
    } catch (error) { operatorToken = ""; setConnection(false); notify(error.message, true); }
    finally { $("connect-button").disabled = false; }
  });
  $("disconnect-button").addEventListener("click", () => {
    operatorToken = ""; profiles = []; runs = []; selectedRun = null; ++requestGeneration;
    $("operator-token").value = ""; setConnection(false); renderRuns();
    $("detail-empty").hidden = false; $("detail-content").hidden = true;
    $("detail-content").querySelectorAll(".json-content").forEach((node) => node.remove());
    $("profiles-list").replaceChildren(el("p", "Connect to inspect available profiles and their acceptance criteria.", "muted"));
    for (const dialog of document.querySelectorAll("dialog")) dialog.close();
    notify("Disconnected. The token has been cleared from this tab.");
    $("operator-token").focus();
  });
  $("refresh-button").addEventListener("click", () => refresh().then(() => notify("Run state refreshed.")).catch((error) => notify(error.message, true)));
  $("profile-input").addEventListener("change", updateProfileRequirements);
  $("new-run-button").addEventListener("click", () => { admissionKey = crypto.randomUUID(); formError("run-form-error", null); $("run-dialog").showModal(); });
  for (const button of document.querySelectorAll("[data-close]")) button.addEventListener("click", () => $(button.dataset.close).close());
  $("run-form").addEventListener("submit", async (event) => {
    event.preventDefault(); formError("run-form-error", null); $("create-submit").disabled = true;
    try {
      const profile = profiles.find((item) => profileId(item) === $("profile-input").value);
      if (!profile || !isActive(profile)) throw new Error("Choose an available capability profile.");
      const budget = Math.round(Number($("budget-input").value) * 1000000);
      if (!Number.isSafeInteger(budget) || budget <= 0) throw new Error("Enter a valid positive budget.");
      const requirements = structuredClone(profile.acceptance_criteria || []);
      if (!requirements.length) throw new Error("Provide at least one requirement.");
      const spec = {
        name: $("run-title-input").value.trim(), profile: profileId(profile), requirements,
        tasks: taskTemplate(profile),
        max_attempts: Number($("attempts-input").value),
      };
      const run = await api("/runs", "POST", { spec, budget, idempotency_key: admissionKey });
      $("run-dialog").close(); await refresh(); await selectRun(identifier(run));
      notify("Run queued. A configured worker can now claim the work.");
    } catch (error) { formError("run-form-error", error); }
    finally { $("create-submit").disabled = false; }
  });
  $("revise-button").addEventListener("click", () => {
    if (!selectedRun) return;
    $("revision-title").value = selectedRun.spec.name || "";
    $("revision-objective").value = selectedRun.spec.tasks?.[0]?.objective || "";
    $("revision-requirements").value = (selectedRun.spec.requirements || []).join("\n");
    formError("revision-error", null); $("revise-dialog").showModal();
  });
  $("revise-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selectedRun) return;
    formError("revision-error", null); $("revise-submit").disabled = true;
    try {
      const spec = structuredClone(selectedRun.spec);
      spec.name = $("revision-title").value.trim();
      const id = identifier(selectedRun);
      await api(`/runs/${encodeURIComponent(id)}/revise`, "POST", { spec, expected_revision: selectedRun.revision });
      $("revise-dialog").close(); await selectRun(id); await refresh(); notify("New revision recorded. Earlier verification no longer certifies this specification.");
    } catch (error) { formError("revision-error", error); }
    finally { $("revise-submit").disabled = false; }
  });
  $("cancel-button").addEventListener("click", () => { formError("cancel-error", null); $("cancel-dialog").showModal(); });
  $("cancel-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (!selectedRun) return;
    $("cancel-submit").disabled = true; formError("cancel-error", null);
    try {
      const id = identifier(selectedRun); await api(`/runs/${encodeURIComponent(id)}/cancel`, "POST", {});
      $("cancel-dialog").close(); await selectRun(id); await refresh(); notify("Run cancelled. The history is preserved.");
    } catch (error) { formError("cancel-error", error); }
    finally { $("cancel-submit").disabled = false; }
  });
  $("release-button").addEventListener("click", async () => {
    if (!selectedRun) return; $("release-button").disabled = true;
    try {
      const id = identifier(selectedRun); const manifest = await api(`/runs/${encodeURIComponent(id)}/release`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }));
      const anchor = el("a"); anchor.href = url; anchor.download = `graphos-release-${id}.json`;
      document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("Release evidence downloaded. No artifact was deployed or executed.");
    } catch (error) { notify(error.message, true); }
    finally { if (selectedRun) renderDetail(selectedRun); }
  });
})();
