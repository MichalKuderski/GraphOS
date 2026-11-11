import {defineHook} from "eve/hooks";
import {AdapterError,MODEL_ID} from "../../src/contracts.js";
import {currentReceiptInvocation,receiptRun,receiptSettlement,setReceiptInvocation} from "../../src/receipt-context.js";
import {assertAbandonedReceiptObservation} from "../../src/receipt-abandonment.js";
import {receiptApiOrigin,receiptFromAttributes} from "../../src/receipts.js";
import {journaledReceiptSender} from "../../src/receipt-journal.js";

export default defineHook({events:{
  "model.started"(event,ctx) {
    setReceiptInvocation(ctx.session.id,ctx.session.auth.initiator?.attributes,
      event.data.runId,event.data.modelId,event.data.attempt);
  },
  async "model.settled"(event,ctx) {
    // An interrupted step restores context before model.started, while its
    // published events and journal survive. Validate the historical observation
    // without repopulating the state used to dispatch or account for new work.
    if(receiptRun.get()===null&&event.data.outcome==="abandoned") {
      await assertAbandonedReceiptObservation(event,ctx);
      return;
    }
    const binding=currentReceiptInvocation(ctx.session.id);
    if(binding.model_run_id!==event.data.runId)throw new AdapterError("receipt_usage_binding_invalid");
    receiptSettlement.update(()=>({run_id:event.data.runId,outcome:event.data.outcome,
      generation_id:event.data.generationId??null,finish_reason:event.data.finishReason??null}));
  },
  async "usage.recorded"(event,ctx) {
    const {kind,owner,usage}=event.data;
    if(kind!=="model"||!owner||!("runId"in owner))throw new AdapterError("receipt_usage_binding_invalid");
    const binding=currentReceiptInvocation(ctx.session.id),settled=receiptSettlement.get();
    if(binding.model_run_id!==owner.runId||!settled||settled.run_id!==owner.runId||settled.outcome!=="completed")
      throw new AdapterError("receipt_usage_binding_invalid");
    if(usage.costUsd===undefined||!Number.isFinite(usage.costUsd)||usage.costUsd<0)
      throw new AdapterError("receipt_usage_missing_cost");
    const grant=receiptFromAttributes(ctx.session.auth.initiator?.attributes);
    await journaledReceiptSender(receiptApiOrigin())(grant,{kind:"usage",event_id:`usage:${owner.runId}`,
      session_id:ctx.session.id,model_run_id:owner.runId,model_id:MODEL_ID,model_attempt:0,
      usage:{input_tokens:usage.inputTokens,output_tokens:usage.outputTokens,
        cache_read_tokens:usage.cacheReadTokens,cache_write_tokens:usage.cacheWriteTokens,
        actual_cost_microdollars:Math.ceil(usage.costUsd*1_000_000),
        generation_id:settled.generation_id,finish_reason:settled.finish_reason}});
  },
}});
