import { defineAgent, defineDynamic } from "eve";
import { runs, turns } from "eve/events";
import { boundedModel } from "../src/model.js";
import { AdapterError, MAX_MODEL_CALLS, MAX_OUTPUT_TOKENS, MODEL_CONTEXT_TOKENS } from "../src/contracts.js";
import {currentReceiptInvocation} from "../src/receipt-context.js";

export default defineAgent({
  // Private sessions otherwise request deletion at end, racing the broker's
  // completion receipt and destroying the evidence needed for reconciliation.
  // Retain in the private Workflow store under its configured default policy.
  experimental: {workflow: {retention: "default"}},
  model: defineDynamic(ctx => {
    // Durable observations survive process restarts. Never rely on an in-memory counter.
    if (turns(ctx.view).length > 1 || runs(ctx.view).filter(run => run.status === "settled").length >= MAX_MODEL_CALLS) {
      throw new AdapterError("model_call_limit");
    }
    return {model: boundedModel(()=>currentReceiptInvocation(ctx.session.id)), reasoning: "low", modelContextWindowTokens: MODEL_CONTEXT_TOKENS};
  }),
  defaultTools: false,
  tool: false,
  limits: {
    sessionUsage: ({total}) => total.outputTokens >= MAX_OUTPUT_TOKENS * MAX_MODEL_CALLS ||
      total.inputTokens >= 660_000 || (total.costUsd ?? 0) >= 0.09,
    sessionTimeoutMs: 60_000,
  },
});
