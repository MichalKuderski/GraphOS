import { gateway, wrapLanguageModel, type LanguageModelMiddleware } from "ai";
import { AdapterError, assertLiveAuthorization, MAX_OUTPUT_TOKENS, MAX_PROMPT_BYTES, MODEL_ID } from "./contracts.js";

// Enforced on the actual provider request, independent of model instructions.
export const boundedMiddleware: LanguageModelMiddleware = {
  specificationVersion: "v4",
  transformParams: async ({params}) => {
    if (Buffer.byteLength(JSON.stringify(params.prompt)) > MAX_PROMPT_BYTES) {
      throw new AdapterError("model_context_limit");
    }
    return {...params, maxOutputTokens: MAX_OUTPUT_TOKENS};
  },
};

export function boundedModel() {
  assertLiveAuthorization();
  let invoked = false;
  const oneShot: LanguageModelMiddleware = {
    specificationVersion: "v4",
    transformParams: async ({params}) => {
      // Block SDK/harness retries through this resolved instance. A crash/replay
      // can create another instance. Provider budgets are soft caps; uncertain
      // work must pause dispatch and be reconciled before another live attempt.
      if (invoked) throw new AdapterError("model_retry_blocked");
      invoked = true;
      const timeout = AbortSignal.timeout(90_000);
      return {...params, abortSignal: params.abortSignal ? AbortSignal.any([params.abortSignal, timeout]) : timeout};
    },
  };
  return wrapLanguageModel({model: gateway(MODEL_ID), middleware: [oneShot, boundedMiddleware]});
}
