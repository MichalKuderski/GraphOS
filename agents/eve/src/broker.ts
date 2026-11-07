import type { SessionStreamEvent } from "eve/client";
import { createHash } from "node:crypto";
import { AdapterError, CATALOG_SHA256, MODEL_ID, TIMEOUT_MS, validateGenerated, type TaskRequest } from "./contracts.js";
import type { AgentSession, AgentTransport } from "./transport.js";

export function usageFromEvents(events: readonly SessionStreamEvent[]) {
  let input_tokens = 0, output_tokens = 0, cache_read_tokens = 0, cache_write_tokens = 0;
  let actual_cost_microdollars = 0;
  const started = new Set<string>(), reported = new Set<string>();
  const settled = new Map<string, {generation_id: string | null; finish_reason: string | null}>();
  const generationIds = new Set<string>();
  for (const event of events) {
    if (event.type === "model.started") {
      if (event.data.modelId !== MODEL_ID || event.data.attempt !== 0) throw new AdapterError("unreconciled_model_usage");
      started.add(event.data.runId);
    }
    // A retry can have incurred provider cost without reporting usage; never call it free.
    if (event.type === "model.retried") throw new AdapterError("unreconciled_model_usage");
    if (event.type === "model.settled") {
      const {runId, outcome, generationId, finishReason} = event.data;
      if (settled.has(runId) || outcome !== "completed" ||
          (generationId !== undefined && (typeof generationId !== "string" ||
            generationId.length === 0 || generationId.length > 512 || generationIds.has(generationId))) ||
          (finishReason !== undefined && (typeof finishReason !== "string" || finishReason.length > 128))) {
        throw new AdapterError("unreconciled_model_usage");
      }
      if (generationId !== undefined) generationIds.add(generationId);
      settled.set(runId, {generation_id: generationId ?? null, finish_reason: finishReason ?? null});
    }
    if (event.type !== "usage.recorded") continue;
    const {kind, usage, owner} = event.data;
    if (kind !== "model" || !owner || !("runId" in owner) || reported.has(owner.runId)) {
      throw new AdapterError("unreconciled_model_usage");
    }
    const values = [usage.inputTokens, usage.outputTokens, usage.cacheReadTokens, usage.cacheWriteTokens];
    if (values.some(value => !Number.isSafeInteger(value) || value < 0) ||
        usage.costUsd === undefined || !Number.isFinite(usage.costUsd) || usage.costUsd < 0) {
      throw new AdapterError("unreconciled_model_usage");
    }
    reported.add(owner.runId);
    input_tokens += usage.inputTokens; output_tokens += usage.outputTokens;
    cache_read_tokens += usage.cacheReadTokens; cache_write_tokens += usage.cacheWriteTokens;
    // Round each provider report upward; never undercharge the ledger through float truncation.
    actual_cost_microdollars += Math.ceil(usage.costUsd * 1_000_000);
  }
  if (!started.size || started.size !== reported.size || [...started].some(id => !reported.has(id)) ||
      [...settled.keys()].some(id => !started.has(id)) ||
      !Number.isSafeInteger(actual_cost_microdollars)) throw new AdapterError("unreconciled_model_usage");
  // Missing Gateway lookup IDs remain explicit. Runtime usage is not a fetched
  // provider receipt, and a missing ID must never be synthesized from a run ID.
  const generations = [...started].map(run_id => ({run_id,
    generation_id: settled.get(run_id)?.generation_id ?? null,
    finish_reason: settled.get(run_id)?.finish_reason ?? null}));
  return {input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
    actual_cost_microdollars, model_runs: started.size, cost_source: "eve_gateway_usage_events", generations};
}

export async function generate(request: TaskRequest, transport: AgentTransport, timeoutMs = TIMEOUT_MS) {
  const signal = AbortSignal.timeout(timeoutMs);
  let session: AgentSession | undefined;
  let usage: ReturnType<typeof usageFromEvents> | undefined;
  let completed = false, ended = false;
  try {
    session = await transport.create(request, signal);
    const result = await session.result(signal);
    if (result.status !== "completed") throw new AdapterError("eve_turn_not_completed");
    completed = true;
    usage = usageFromEvents(await session.events(signal));
    if (usage.actual_cost_microdollars > request.claim.reservation) {
      throw new AdapterError("reservation_exceeded", true, usage.actual_cost_microdollars);
    }
    const {files} = validateGenerated(result.data);
    await session.end(AbortSignal.timeout(5_000));
    ended = true;
    return {files, usage, provenance: {
      mode: "eve", adapter_version: "0.1.0", eve_version: "0.91.0", ai_sdk_version: "7.0.164",
      model: MODEL_ID, reasoning: "low", catalog_sha256: CATALOG_SHA256,
      session_id: session.id, delivery_id: result.deliveryId,
      run_id: request.claim.run_id, task_id: request.claim.task_id,
      input_hash: request.claim.input_hash, suite_hash: request.claim.suite_hash,
      policy_hash: request.claim.policy_hash,
      request_sha256: createHash("sha256").update(JSON.stringify(request)).digest("hex"),
      generated_at: new Date().toISOString(), independent_verification: "pending",
    }};
  } catch (error) {
    if (error instanceof AdapterError) {
      if (usage && !error.costKnown) throw new AdapterError(error.code, true, usage.actual_cost_microdollars);
      throw error;
    }
    throw new AdapterError(signal.aborted ? "eve_timeout" : "eve_transport_or_runtime_error",
      Boolean(usage), usage?.actual_cost_microdollars);
  } finally {
    if (session && !ended) {
      // Aborting the client read does not cancel remote work. Request remote cancellation explicitly.
      if (!completed) await session.cancel(AbortSignal.timeout(5_000)).catch(() => undefined);
      await session.end(AbortSignal.timeout(5_000)).catch(() => undefined);
      // Failed cancellation leaves the attempt's reservation consumed by GraphOS.
    }
  }
}
