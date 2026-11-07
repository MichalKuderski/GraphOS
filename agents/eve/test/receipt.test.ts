import test from "node:test";
import assert from "node:assert/strict";
import type { SessionStreamEvent } from "eve/client";
import { usageFromEvents } from "../src/broker.js";
import { MODEL_ID } from "../src/contracts.js";

function usageEvents(runId = "model-1"): SessionStreamEvent[] {
  return [
    {type:"model.started",data:{runId,modelId:MODEL_ID,attempt:0}},
    {type:"usage.recorded",data:{kind:"model",owner:{runId},usage:{
      inputTokens:100,outputTokens:200,cacheReadTokens:0,cacheWriteTokens:0,costUsd:0.001}}},
  ] as SessionStreamEvent[];
}

function settled(runId = "model-1", generationId: string | undefined = "gen_receipt-1",
                 outcome = "completed"): SessionStreamEvent {
  return {type:"model.settled",data:{runId,outcome,generationId,finishReason:"stop"}} as SessionStreamEvent;
}

test("Gateway generation IDs retain their model-run binding and reported cost", () => {
  // Settlement can precede usage in the public stream; joining is by run ID.
  const usage = usageFromEvents([settled(),...usageEvents()]);
  assert.deepEqual(usage.generations,[{run_id:"model-1",generation_id:"gen_receipt-1",finish_reason:"stop"}]);
  assert.equal(usage.actual_cost_microdollars,1000);
  assert.equal(usage.cost_source,"eve_gateway_usage_events");
});

test("missing lookup IDs remain explicit without inventing a provider receipt", () => {
  assert.deepEqual(usageFromEvents(usageEvents()).generations,
    [{run_id:"model-1",generation_id:null,finish_reason:null}]);
  const withoutId = settled();
  if (withoutId.type === "model.settled") {
    const {generationId: _unused, ...data} = withoutId.data;
    assert.deepEqual(usageFromEvents([...usageEvents(),{...withoutId,data}]).generations,
      [{run_id:"model-1",generation_id:null,finish_reason:"stop"}]);
  }
});

test("duplicate, orphaned or failed generation receipts cannot certify usage", () => {
  for (const records of [
    [...usageEvents(),settled(),settled()],
    [...usageEvents(),settled("unstarted-model")],
    [...usageEvents(),settled("model-1","gen_receipt-1","failed")],
    [...usageEvents(),settled("model-1","")],
    [...usageEvents(),...usageEvents("model-2"),settled(),settled("model-2")],
  ]) assert.throws(()=>usageFromEvents(records), /unreconciled_model_usage/);
});

test("multiple distinct Gateway receipts remain attached to their own runs", () => {
  assert.deepEqual(usageFromEvents([...usageEvents(),...usageEvents("model-2"),
    settled("model-2","gen_receipt-2"),settled()]).generations,
  [{run_id:"model-1",generation_id:"gen_receipt-1",finish_reason:"stop"},
    {run_id:"model-2",generation_id:"gen_receipt-2",finish_reason:"stop"}]);
});
