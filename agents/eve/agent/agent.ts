import { defineAgent, defineDynamic } from "eve";
import { runs, turns } from "eve/events";
import { boundedModel } from "../src/model.js";
import { AdapterError, MAX_MODEL_CALLS, MAX_OUTPUT_TOKENS } from "../src/contracts.js";

export default defineAgent({
  model: defineDynamic(ctx => {
    // Durable observations survive process restarts. Never rely on an in-memory counter.
    if (turns(ctx.view).length > 1 || runs(ctx.view).filter(run => run.status === "settled").length >= MAX_MODEL_CALLS) {
      throw new AdapterError("model_call_limit");
    }
    return {model: boundedModel(), reasoning: "low", modelContextWindowTokens: 1_050_000};
  }),
  defaultTools: false,
  tool: false,
  limits: {
    sessionUsage: ({total}) => total.outputTokens >= MAX_OUTPUT_TOKENS * MAX_MODEL_CALLS ||
      total.inputTokens >= 660_000 || (total.costUsd ?? 0) >= 0.09,
    sessionTimeoutMs: 60_000,
  },
});
