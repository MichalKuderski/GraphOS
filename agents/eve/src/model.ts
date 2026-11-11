import { gateway, wrapLanguageModel, type LanguageModelMiddleware } from "ai";
import {isDeepStrictEqual} from "node:util";
import {z} from "zod";
import { AdapterError, assertLiveAuthorization, GeneratedSchema, MAX_OUTPUT_TOKENS, MAX_PROMPT_BYTES, MODEL_ID } from "./contracts.js";
import {earlyReceiptMiddleware,receiptApiOrigin,type ReceiptInvocation} from "./receipts.js";
import {journaledReceiptSender} from "./receipt-journal.js";

// Pinned eve 0.91: protocol/reply-tool.js and harness/model-call/tools.js
// inject this function for outputSchema. No private framework import is used.
export const REPLY_TOOL_NAME = "eve__reply";
const {$schema: _schemaVersion, ...replySchema} = z.toJSONSchema(GeneratedSchema, {target:"draft-7"});

// Enforced on the actual provider request, independent of model instructions.
export const boundedMiddleware: LanguageModelMiddleware = {
  specificationVersion: "v4",
  transformParams: async ({params}) => {
    if (Buffer.byteLength(JSON.stringify(params.prompt)) > MAX_PROMPT_BYTES) {
      throw new AdapterError("model_context_limit");
    }
    const reply = params.tools?.[0];
    if (params.tools?.length !== 1 || reply?.type !== "function" ||
        reply.name !== REPLY_TOOL_NAME || !isDeepStrictEqual(reply.inputSchema, replySchema)) {
      throw new AdapterError("structured_reply_tool_required");
    }
    // The native Gateway request carries this V4 function-tool flag to the
    // provider. Keep local validation: schema-keyword support is route-specific,
    // and refused/interrupted output must never qualify as a candidate.
    return {...params, tools: [{...reply, strict: true}], maxOutputTokens: MAX_OUTPUT_TOKENS,
      toolChoice: {type:"tool",toolName:REPLY_TOOL_NAME}};
  },
};

export function boundedModel(receiptBinding:()=>ReceiptInvocation) {
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
  return wrapLanguageModel({model: gateway(MODEL_ID), middleware: [oneShot, boundedMiddleware,
    earlyReceiptMiddleware(receiptBinding,journaledReceiptSender(receiptApiOrigin()))]});
}
