import type {SessionStreamEvent} from "eve/client";
import {AdapterError,MODEL_ID,MAX_MODEL_CALLS} from "./contracts.js";
import {ReceiptEventSchema,type ReceiptEvent,type ReceiptGrant,type ReceiptSender} from "./receipts.js";

// Recover facts for an ALREADY REGISTERED session from its authenticated,
// retained snapshot. No registration, control command, model or settlement.
// This closes stream-commit -> hook-entry gaps that a local outbox cannot cover.
export async function recoverRetainedReceipts(grant:ReceiptGrant,sessionId:string,
  events:readonly SessionStreamEvent[],send:ReceiptSender) {
  const models=new Map<string,{settled?:Extract<SessionStreamEvent,{type:"model.settled"}>;usage?:Extract<SessionStreamEvent,{type:"usage.recorded"}>}>();
  const terminal=events.filter(event=>event.type==="session.ended");
  for(const event of events){
    if(event.type==="model.retried")throw new AdapterError("receipt_recovery_ambiguous_model");
    if(event.type==="model.started"){
      if(event.data.modelId!==MODEL_ID||event.data.attempt!==0||models.has(event.data.runId)||models.size>=MAX_MODEL_CALLS)
        throw new AdapterError("receipt_recovery_ambiguous_model");
      models.set(event.data.runId,{});
    }
    if(event.type==="model.settled"){
      const model=models.get(event.data.runId);
      if(!model||model.settled)throw new AdapterError("receipt_recovery_ambiguous_model");
      model.settled=event;
    }
    if(event.type==="usage.recorded"){
      const owner=event.data.owner;
      const model=owner&&"runId"in owner?models.get(owner.runId):undefined;
      if(event.data.kind!=="model"||!model||model.usage)throw new AdapterError("receipt_recovery_ambiguous_model");
      model.usage=event;
    }
  }
  if(terminal.length>1)throw new AdapterError("receipt_recovery_ambiguous_terminal");
  const facts:ReceiptEvent[]=[];
  for(const [runId,model] of models){
    if(model.settled?.data.outcome!=="completed"||!model.usage)continue;
    const {usage}=model.usage.data;
    if(usage.costUsd===undefined||!Number.isFinite(usage.costUsd)||usage.costUsd<0)
      throw new AdapterError("receipt_recovery_missing_cost");
    facts.push(ReceiptEventSchema.parse({kind:"usage",event_id:`usage:${runId}`,session_id:sessionId,
      model_run_id:runId,model_id:MODEL_ID,model_attempt:0,usage:{input_tokens:usage.inputTokens,
        output_tokens:usage.outputTokens,cache_read_tokens:usage.cacheReadTokens,cache_write_tokens:usage.cacheWriteTokens,
        actual_cost_microdollars:Math.ceil(usage.costUsd*1_000_000),
        generation_id:model.settled.data.generationId??null,finish_reason:model.settled.data.finishReason??null}}));
  }
  if(terminal[0]?.type==="session.ended")facts.push(ReceiptEventSchema.parse({kind:"session_terminal",
    event_id:"session_terminal",session_id:sessionId,outcome:terminal[0].data.outcome}));
  let duplicates=0;
  // All facts are validated before the first callback. The controller enforces
  // grant/session/model identities even after cancellation/expiry/revision.
  for(const fact of facts)duplicates+=Number((await send(grant,fact)).duplicate);
  return {recorded:facts.length,duplicates,settles_cost:false,provider_calls:0};
}
