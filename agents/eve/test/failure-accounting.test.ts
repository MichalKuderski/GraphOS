import test from "node:test";
import assert from "node:assert/strict";
import type {SessionStreamEvent} from "eve/client";
import {generate} from "../src/broker.js";
import {AdapterError, adapterErrorPayload, MODEL_ID, parseRequest} from "../src/contracts.js";
import type {AgentTransport} from "../src/transport.js";

function input() {
  const hash="a".repeat(64);
  return parseRequest(JSON.stringify({claim:{run_id:"run",task_id:"task",task_key:"app",
    epoch:1,revision:1,input_hash:hash,objective:"Test terminal failure",requirements:["Offline app"],
    profile:"local-notes",suite_hash:hash,policy_hash:hash,reservation:1_000_000},
  profile:{id:"local-notes",status:"active",required_files:["index.html","app.js","styles.css"],
    acceptance_criteria:["Offline app"],required_checks:["structure"],selector_contract:{},
    suite_hash:hash,policy_hash:hash},dependencies:[]}));
}

function records(runId="run_0", generationId="gen_receipt0"): SessionStreamEvent[] {
  return [
    {type:"model.started",data:{runId,modelId:MODEL_ID,attempt:0}},
    {type:"model.settled",data:{runId,outcome:"completed",finishReason:"stop",generationId}},
    {type:"usage.recorded",data:{kind:"model",owner:{runId},usage:{
      inputTokens:2048,outputTokens:4160,cacheReadTokens:0,cacheWriteTokens:0,costUsd:0.008832}}},
  ] as SessionStreamEvent[];
}

function fakeTransport(history:SessionStreamEvent[], options:{endFails?:boolean;eventsFail?:boolean;readFails?:boolean}={}) {
  const calls:string[]=[];
  const transport:AgentTransport={async create(){calls.push("create");return {
    id:"session-failed",
    async result(){calls.push("result");if(options.readFails)throw new Error("PRIVATE_PROVIDER_RESPONSE");
      return {status:"failed",sessionId:"session-failed",deliveryId:"one-message",data:"PRIVATE_CANDIDATE"};},
    async cancel(){calls.push("cancel");},
    async end(){calls.push("end");if(options.endFails)throw new Error("PRIVATE_RETIREMENT_ERROR");},
    async events(){calls.push("events");if(options.eventsFail)throw new Error("PRIVATE_HISTORY_ERROR");return history;},
  };}};
  return {transport,calls};
}

async function failure(transport:AgentTransport) {
  try {await generate(input(),transport);assert.fail("A failed build must never return a candidate");}
  catch(error) {assert.ok(error instanceof AdapterError);return error;}
}

test("terminal schema failure recovers complete cost only after proved retirement", async()=>{
  const {transport,calls}=fakeTransport(records());
  const error=await failure(transport);
  assert.equal(error.code,"eve_turn_not_completed");
  assert.equal(error.costKnown,true);
  assert.equal(error.actualCostMicrodollars,8832);
  assert.deepEqual(error.usage?.generations,[{run_id:"run_0",generation_id:"gen_receipt0",finish_reason:"stop"}]);
  assert.deepEqual(calls,["create","result","cancel","end","events"]);
  assert.equal(calls.filter(value=>value==="create").length,1,"accounting cannot dispatch another model session");
});

test("interrupted missing retry duplicate and orphan observations remain unknown", async()=>{
  const valid=records();
  const changed=(index:number,data:Record<string,unknown>)=>valid.map((event,i)=>
    i===index?{...event,data:{...event.data,...data}} as SessionStreamEvent:event);
  const cases:Record<string,SessionStreamEvent[]>={
    interrupted:changed(1,{outcome:"interrupted"}),
    missing_settlement:[valid[0]!,valid[2]!],
    missing_usage:[valid[0]!,valid[1]!],
    missing_cost:changed(2,{usage:{inputTokens:2048,outputTokens:4160,cacheReadTokens:0,cacheWriteTokens:0}}),
    invalid_tokens:changed(2,{usage:{inputTokens:-1,outputTokens:4160,cacheReadTokens:0,cacheWriteTokens:0,costUsd:0.008832}}),
    retry:[...valid,{type:"model.retried",data:{runId:"run_0",attempt:1}} as SessionStreamEvent],
    duplicate_start:[...valid,valid[0]!],
    duplicate_usage:[...valid,valid[2]!],
    duplicate_settlement:[...valid,valid[1]!],
    orphan_usage:[...valid,records("orphan","gen_orphan")[2]!],
    orphan_settlement:[...valid,records("orphan","gen_orphan")[1]!],
    unreported_second_run:[...valid,records("run_1","gen_second")[0]!],
    unknown_model:changed(0,{modelId:"unapproved/model"}),
  };
  for(const [name,history]of Object.entries(cases)) {
    const {transport,calls}=fakeTransport(history);
    const error=await failure(transport);
    assert.equal(error.code,"eve_turn_not_completed",name);
    assert.equal(error.costKnown,false,name);
    assert.equal(error.actualCostMicrodollars,undefined,name);
    assert.equal(error.usage,undefined,name);
    assert.deepEqual(calls,["create","result","cancel","end","events"],name);
  }
});

test("failed retirement or unavailable retained history cannot certify a known cost", async()=>{
  for(const options of [{endFails:true},{eventsFail:true}]) {
    const {transport,calls}=fakeTransport(records(),options);
    const error=await failure(transport);
    assert.equal(error.code,"eve_turn_not_completed");
    assert.equal(error.costKnown,false);
    assert.equal(error.usage,undefined);
    if(options.endFails)assert.ok(!calls.includes("events"),"unretired history cannot be a final accounting source");
  }
});

test("transport read failure keeps its sanitized code when terminal usage is recovered", async()=>{
  const {transport}=fakeTransport(records(),{readFails:true});
  const error=await failure(transport);
  assert.equal(error.code,"eve_transport_or_runtime_error");
  assert.equal(error.actualCostMicrodollars,8832);
  assert.ok(!JSON.stringify(adapterErrorPayload(error)).includes("PRIVATE"));
});

test("failure recovery sums each model once and retains distinct generation lookup IDs", async()=>{
  const {transport,calls}=fakeTransport([...records(),...records("run_1","gen_receipt1")]);
  const error=await failure(transport);
  assert.equal(error.actualCostMicrodollars,17664);
  assert.equal(error.usage?.model_runs,2);
  assert.deepEqual(error.usage?.generations.map(value=>value.generation_id),["gen_receipt0","gen_receipt1"]);
  assert.equal(calls.filter(value=>value==="events").length,1);
  assert.equal(calls.filter(value=>value==="create").length,1);
});

test("CLI error serialization includes only validated known usage and never raw payloads", async()=>{
  const error=await failure(fakeTransport(records()).transport);
  const payload=adapterErrorPayload(error);
  assert.deepEqual(Object.keys(payload).sort(),["accounting","actual_cost_microdollars","cost_known","error","usage"]);
  assert.equal(payload.accounting,"provider_reported");
  assert.equal(payload.usage?.actual_cost_microdollars,8832);
  const unknown=adapterErrorPayload(new AdapterError("eve_turn_not_completed",false,8832,error.usage));
  assert.equal(unknown.usage,undefined);
  assert.equal(unknown.actual_cost_microdollars,undefined);
  assert.equal(unknown.accounting,"consume_reservation_and_reconcile");
  assert.equal(adapterErrorPayload(new AdapterError("failed",true,1,error.usage)).usage,undefined);
  const contaminated={...error.usage!,raw_response:"PRIVATE_PROVIDER_RESPONSE"};
  assert.equal(adapterErrorPayload(new AdapterError("failed",true,8832,contaminated)).usage,undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(adapterErrorPayload(new Error("PRIVATE_PROVIDER_RESPONSE")))),
    {error:"unexpected_adapter_error",cost_known:false,accounting:"consume_reservation_and_reconcile"});
});
