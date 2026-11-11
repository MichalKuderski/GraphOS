import {defineState} from "eve/context";
import {AdapterError, MODEL_ID} from "./contracts.js";
import {receiptFromAttributes,receiptTaskFromAttributes,type ReceiptInvocation} from "./receipts.js";

// Only the runtime's model.started hook writes this slot. It is scoped by Eve's
// session context, never a process-global active session or model counter.
export const receiptRun=defineState<ReceiptInvocation|null>("graphos.receipt.active-run",()=>null);
export const receiptSettlement=defineState<{
  run_id:string;outcome:string;generation_id:string|null;finish_reason:string|null;
}|null>("graphos.receipt.settled-run",()=>null);

export function currentReceiptInvocation(sessionId:string):ReceiptInvocation {
  const binding=receiptRun.get();
  if(!binding||binding.session_id!==sessionId||binding.model_id!==MODEL_ID||binding.model_attempt!==0)
    throw new AdapterError("receipt_model_binding_missing");
  return binding;
}

export function setReceiptInvocation(sessionId:string,
  attributes:Readonly<Record<string,string|readonly string[]>>|undefined,
  runId:string,modelId:string|undefined,attempt:number) {
  if(modelId!==MODEL_ID||attempt!==0)throw new AdapterError("receipt_model_binding_invalid");
  const grant=receiptFromAttributes(attributes);
  const task=receiptTaskFromAttributes(attributes);
  receiptRun.update(()=>({grant,task,session_id:sessionId,model_run_id:runId,model_id:MODEL_ID,model_attempt:0}));
  receiptSettlement.update(()=>null);
}
