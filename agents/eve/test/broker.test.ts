import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import type { SessionStreamEvent } from "eve/client";
import { AdapterError, assertGatewayAuth, assertLiveAuthorization, brokerSettings, MAX_FILE_BYTES, MAX_PROMPT_BYTES,
  MODEL_ID, parseRequest, validateGenerated } from "../src/contracts.js";
import { generate, usageFromEvents } from "../src/broker.js";
import { boundedMiddleware } from "../src/model.js";
import type { AgentTransport } from "../src/transport.js";

const hash = "a".repeat(64);
const files = {"index.html": "<!doctype html><main>Task list</main>", "app.js": "'use strict';", "styles.css": "body {color:#111}"};
function requestInput() {
  return {claim: {run_id:"r1",task_id:"t1",task_key:"app",epoch:1,revision:1,input_hash:hash,
    token:"PRIVATE_LEASE_NOT_FOR_MODEL", objective:"Build an accessible task list",requirements:["Persist tasks"],
    profile:"static-web",suite_hash:hash,policy_hash:hash,reservation:1_000_000},
  profile: {id:"static-web",status:"active",required_files:["index.html","app.js","styles.css"],
    acceptance_criteria:["Persist tasks"],required_checks:["local_storage_reload"],
    selector_contract:{input:"New task",filters:["All","Active","Completed"]},suite_hash:hash,policy_hash:hash},dependencies:[]};
}
function events(costUsd: number | undefined = 0.0010001): SessionStreamEvent[] {
  // Only provider transport observations are mocked; broker/accounting implementation is real.
  return [{type:"model.started",data:{runId:"m1",modelId:MODEL_ID,attempt:0}},
    {type:"usage.recorded",data:{kind:"model",owner:{runId:"m1"},usage:{inputTokens:100,
      outputTokens:200,cacheReadTokens:10,cacheWriteTokens:0,costUsd}}}] as SessionStreamEvent[];
}
function mockTransport(options: {cost?: number; data?: unknown; fail?: boolean; missingCost?: boolean} = {}) {
  const calls: string[] = [];
  const transport: AgentTransport = {async create(request, signal) {
    calls.push("create"); assert.equal(signal.aborted,false);
    assert.ok(!JSON.stringify(request).includes("PRIVATE_LEASE"));
    return {id:"s1",async result() {calls.push("result"); if(options.fail) throw new Error("SECRET_PROVIDER_ERROR");
      return {status:"completed",data:options.data ?? {files},sessionId:"s1",deliveryId:"d1"};},
      async events(){calls.push("events"); const records=events(options.cost);
        if(options.missingCost) delete (records[1]!.data as {usage:{costUsd?:number}}).usage.costUsd;
        return records;},
      async cancel(){calls.push("cancel");},async end(){calls.push("end");}};
  }};
  return {transport,calls};
}

test("task parser removes lease credentials and rejects mismatched profile hashes", () => {
  assert.ok(!JSON.stringify(parseRequest(JSON.stringify(requestInput()))).includes("PRIVATE_LEASE"));
  const input=requestInput(); input.profile.policy_hash="b".repeat(64);
  assert.throws(()=>parseRequest(JSON.stringify(input)), /invalid_task_contract/);
  input.claim.reservation=1;
  assert.throws(()=>parseRequest(JSON.stringify(input)), /invalid_task_contract/);
});
test("trusted profile selection is bound to the claim even when hashes match", () => {
  const profiles=["static-web","local-notes","local-inventory"];
  for (const claimProfile of profiles) {
    for (const suppliedProfile of profiles) {
      const input=requestInput();
      input.claim.profile=claimProfile; input.profile.id=suppliedProfile;
      if (claimProfile === suppliedProfile) {
        const parsed=parseRequest(JSON.stringify(input));
        assert.equal(parsed.claim.profile,claimProfile);
        assert.equal(parsed.profile.id,suppliedProfile);
        assert.ok(!JSON.stringify(parsed).includes("PRIVATE_LEASE"));
      } else {
        assert.throws(()=>parseRequest(JSON.stringify(input)), /invalid_task_contract/);
      }
    }
  }
});
test("every admitted profile retains its exact three-file and active-status boundary", () => {
  for (const profile of ["static-web","local-notes","local-inventory"]) {
    const input=requestInput(); input.claim.profile=profile; input.profile.id=profile;
    for (const change of [{required_files:["index.html","app.js","../secret"]},
        {required_files:["index.html","app.js","app.js"]},
        {required_files:["index.html","app.js","styles.css","server.js"]},
        {status:"blocked"}]) {
      assert.throws(()=>parseRequest(JSON.stringify({...input,profile:{...input.profile,...change}})), /invalid_task_contract/);
    }
  }
});
test("unsupported profiles and excessive input fail before transport", () => {
  const input=requestInput(); input.claim.profile="games";
  assert.throws(()=>parseRequest(JSON.stringify(input)), /invalid_task_contract/);
  input.claim.profile="static-web"; input.profile.id="games";
  assert.throws(()=>parseRequest(JSON.stringify(input)), /invalid_task_contract/);
  assert.throws(()=>parseRequest(" ".repeat(128*1024+1)), /request_too_large/);
});
test("repair feedback is bounded and bound to the current verification contract", () => {
  const repair = {candidate_hash:hash,evidence_hash:hash,verifier_attempt_id:"v1",revision:1,
    input_hash:hash,suite_hash:hash,policy_hash:hash,truncated:false,files,
    checks:[{name:"local_storage_reload",passed:false,detail:"Task disappeared after reload"}]};
  const input = {...requestInput(), repair};
  const parsed = parseRequest(JSON.stringify(input));
  assert.deepEqual(parsed.repair,repair);
  assert.ok(!JSON.stringify(parsed).includes("PRIVATE_LEASE"));
  for (const change of [{revision:2},{input_hash:"b".repeat(64)},
      {suite_hash:"b".repeat(64)},{policy_hash:"b".repeat(64)},
      {checks:[{name:"reload",passed:true,detail:"OK"}]},
      {checks:[{name:"reload",passed:false,detail:"x".repeat(1025)}]},
      {files:{...files,"../secrets":"forbidden"}}]) {
    assert.throws(()=>parseRequest(JSON.stringify({...input,repair:{...repair,...change}})), /invalid_task_contract/);
  }
});
test("generated filenames and byte limits are enforced", () => {
  assert.throws(()=>validateGenerated({files:{...files,"../secret":"oops"}}), /invalid_generated_files/);
  assert.throws(()=>validateGenerated({files:{...files,"app.js":"é".repeat(MAX_FILE_BYTES)}}), /invalid_generated_files/);
});
test("explicit Gateway and broker credentials required; cleartext remote URL forbidden", () => {
  assert.throws(()=>assertGatewayAuth({}), /gateway_credentials_missing/);
  assert.doesNotThrow(()=>assertGatewayAuth({VERCEL_OIDC_TOKEN:"opaque-test-token"}));
  assert.throws(()=>assertLiveAuthorization({AI_GATEWAY_API_KEY:"test"}), /live_gateway_budget_not_confirmed/);
  assert.throws(()=>assertLiveAuthorization({AI_GATEWAY_API_KEY:"test",GRAPHOS_LIVE_ENABLED:"1",GRAPHOS_GATEWAY_BUDGET_USD:"6"}), /live_gateway_budget_not_confirmed/);
  assert.doesNotThrow(()=>assertLiveAuthorization({AI_GATEWAY_API_KEY:"test",GRAPHOS_LIVE_ENABLED:"1",GRAPHOS_GATEWAY_BUDGET_USD:"5"}));
  assert.throws(()=>brokerSettings({}), /eve_broker_token_missing/);
  assert.throws(()=>brokerSettings({GRAPHOS_EVE_TOKEN:"x".repeat(32),EVE_SERVER_URL:"http://example.com"}), /invalid_eve_server_url/);
  assert.equal(brokerSettings({GRAPHOS_EVE_TOKEN:"x".repeat(32)}).baseUrl,"http://127.0.0.1:3001");
});
test("model middleware constrains actual request tokens and prompt size", async () => {
  const transform=boundedMiddleware.transformParams as unknown as (value:{params:{prompt:unknown,maxOutputTokens:number}})=>Promise<{maxOutputTokens:number}>;
  assert.equal((await transform({params:{prompt:[],maxOutputTokens:1000000}})).maxOutputTokens,16384);
  await assert.rejects(transform({params:{prompt:"a".repeat(MAX_PROMPT_BYTES+1),maxOutputTokens:1}}), /model_context_limit/);
});
test("accounting uses provider cost rounded up and rejects incomplete, duplicate or retry-ambiguous reports", () => {
  assert.equal(usageFromEvents(events()).actual_cost_microdollars,1001);
  const missing=events(); delete (missing[1]!.data as {usage:{costUsd?:number}}).usage.costUsd;
  assert.throws(()=>usageFromEvents(missing), /unreconciled_model_usage/);
  assert.throws(()=>usageFromEvents([...events(),events()[1]!]), /unreconciled_model_usage/);
  const retry=events(); (retry[0]!.data as {attempt:number}).attempt=1;
  assert.throws(()=>usageFromEvents(retry), /unreconciled_model_usage/);
});
test("successful result is unverified model provenance, not model-supplied accounting", async () => {
  const {transport,calls}=mockTransport();
  const result=await generate(parseRequest(JSON.stringify(requestInput())),transport);
  assert.deepEqual(result.files,files);
  assert.equal(result.usage.actual_cost_microdollars,1001);
  assert.equal(result.provenance.mode,"eve");
  assert.equal(result.provenance.independent_verification,"pending");
  assert.deepEqual(calls,["create","result","events","end"]);
});
test("transport failure requests cancellation, closes session and hides provider error", async () => {
  const {transport,calls}=mockTransport({fail:true});
  await assert.rejects(generate(parseRequest(JSON.stringify(requestInput())),transport),
    error=>error instanceof AdapterError && error.code==="eve_transport_or_runtime_error" && !error.costKnown && !error.message.includes("SECRET"));
  assert.deepEqual(calls,["create","result","cancel","end"]);
});
test("over-reservation and missing-cost runs cannot produce a successful bundle", async () => {
  const over=mockTransport({cost:2});
  await assert.rejects(generate(parseRequest(JSON.stringify(requestInput())),over.transport),
    error=>error instanceof AdapterError && error.code==="reservation_exceeded" && error.actualCostMicrodollars===2000000);
  const missing=mockTransport({missingCost:true});
  await assert.rejects(generate(parseRequest(JSON.stringify(requestInput())),missing.transport), /unreconciled_model_usage/);
});
test("expired client deadline explicitly cancels remote work instead of returning a fixture", async () => {
  const calls:string[]=[];
  const transport:AgentTransport={async create(){return {id:"s-timeout",
    result:signal=>new Promise((_,reject)=>{
      const hold=setTimeout(()=>reject(new Error("timeout was not enforced")),1000);
      signal.addEventListener("abort",()=>{clearTimeout(hold);reject(signal.reason);},{once:true});
    }),
    async events(){throw new Error("unreachable");},async cancel(){calls.push("cancel");},async end(){calls.push("end");}};}};
  await assert.rejects(generate(parseRequest(JSON.stringify(requestInput())),transport,10),
    error=>error instanceof AdapterError && error.code==="eve_timeout" && !error.costKnown);
  assert.deepEqual(calls,["cancel","end"]);
});
test("real broker CLI with no credentials exits nonzero with empty stdout", () => {
  const result=spawnSync(process.execPath,[new URL("../src/cli.js",import.meta.url).pathname],
    {input:JSON.stringify(requestInput()),encoding:"utf8",env:{},timeout:3000});
  assert.equal(result.status,1);
  assert.equal(result.stdout,"");
  assert.equal(JSON.parse(result.stderr).error,"eve_broker_token_missing");
});
