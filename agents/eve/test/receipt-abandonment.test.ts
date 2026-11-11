import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,writeFile,readdir,readFile,chmod,symlink,rename} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {createHash} from "node:crypto";
import http from "node:http";
import https from "node:https";
import {syncBuiltinESMExports} from "node:module";
import {emptySessionView,foldEvents,runs} from "eve/events";
import type {HookContext,HookEvent} from "eve/hooks";
import type {SessionStreamEvent} from "eve/client";
import {wrapLanguageModel} from "ai";
import {createGateway} from "@ai-sdk/gateway";
import hook from "../agent/hooks/receipts.js";
import {assertAbandonedReceiptObservation} from "../src/receipt-abandonment.js";
import {receiptRun,receiptSettlement,currentReceiptInvocation} from "../src/receipt-context.js";
import {journaledReceiptSender} from "../src/receipt-journal.js";
import {recoverRetainedReceipts} from "../src/receipt-recovery.js";
import {receiptAttributes,earlyReceiptMiddleware,receiptSender,type ReceiptEvent,type ReceiptInvocation} from "../src/receipts.js";
import {AdapterError,MODEL_ID,type TaskRequest} from "../src/contracts.js";
import {generate,usageFromEvents} from "../src/broker.js";

const origin="http://127.0.0.1:8181";
const grant={run_id:"graphos-run",attempt_id:"attempt-1",capture_token:"offline_receipt_capability_000000000000"};
const task={task_id:"task-1",epoch:1,revision:1,input_hash:"a".repeat(64)};
const binding:ReceiptInvocation={grant,task,session_id:"wrun_session",model_run_id:"run_0",model_id:MODEL_ID,model_attempt:0};
const at="2026-11-08T07:28:41.667Z";
const abandoned:HookEvent<"model.settled">={type:"model.settled",scope:{runId:"run_0",turnId:"turn_0"},data:{runId:"run_0",outcome:"abandoned"}};
function events():SessionStreamEvent[] {
  return [
    {type:"session.started",data:{runtime:{agentId:"test",agentName:"test",eveVersion:"0.91.0"}}},
    {type:"turn.started",data:{turnId:"turn_0",cause:{deliveryId:"delivery"},follows:null}},
    {type:"model.requested",data:{runId:"run_0",owner:{turnId:"turn_0"}}},
    {type:"model.started",data:{runId:"run_0",modelId:MODEL_ID,attempt:0}},abandoned,
  ].map((event,line)=>({...event,meta:{at,position:{line,index:0},endOfLine:true}})) as SessionStreamEvent[];
}
function context(records=events()):HookContext<"model.settled"> {
  return {session:{id:binding.session_id,auth:{initiator:{attributes:receiptAttributes(grant,task)}}},
    turn:{id:"turn_0",status:"running",input:[]},now:new Date(at),position:{line:4,index:0},
    view:foldEvents(emptySessionView(),records)} as unknown as HookContext<"model.settled">;
}
const facts:ReceiptEvent[]=[
  {kind:"session",event_id:"session",session_id:binding.session_id,...task},
  {kind:"model_started",event_id:"model_started:run_0",session_id:binding.session_id,model_run_id:"run_0",model_id:MODEL_ID,model_attempt:0},
  {kind:"generation",event_id:"generation:run_0",session_id:binding.session_id,model_run_id:"run_0",model_id:MODEL_ID,model_attempt:0,generation_id:"gen_original"},
];
type RecordValue={version:number;origin:string;grant:typeof grant;event:Record<string,unknown>};
const records=():RecordValue[]=>facts.map(event=>({version:1,origin,grant:{...grant},event:{...event}}));
function filename(record:RecordValue) {
  return createHash("sha256").update(JSON.stringify([record.grant.run_id,record.grant.attempt_id,record.event.event_id])).digest("hex")+".json";
}
async function writeRecords(directory:string,values=records()) {
  for(const value of values)await writeFile(join(directory,filename(value)),JSON.stringify(value),{mode:0o600});
}
async function fixture(values=records()) {
  const directory=await mkdtemp(join(tmpdir(),"graphos-abandonment-"));
  await writeRecords(directory,values);return directory;
}
async function contents(directory:string) {
  return await Promise.all((await readdir(directory)).sort().map(async name=>[name,await readFile(join(directory,name),"utf8")]));
}
const invalid=/receipt_abandonment_evidence_invalid/;

test("restored abandonment uses public persisted view and canonical journal without restoring authority",async t=>{
  const directory=await fixture(),before=await contents(directory);
  t.mock.method(receiptRun,"get",()=>null);
  const runWrites=t.mock.method(receiptRun,"update",()=>{throw new Error("must not restore dispatch state");});
  const settlementWrites=t.mock.method(receiptSettlement,"update",()=>{throw new Error("must not invent settlement");});
  const network=t.mock.method(globalThis,"fetch",async()=>{throw new Error("must not send");});
  const directHttp=t.mock.method(http,"request",()=>{throw new Error("must not send receipt");});
  const directHttps=t.mock.method(https,"request",()=>{throw new Error("must not send receipt");});
  syncBuiltinESMExports(); // Include receiptSender's actual named Node transport imports.
  t.after(()=>{t.mock.restoreAll();syncBuiltinESMExports();});
  const priorDirectory=process.env.GRAPHOS_RECEIPT_OUTBOX_DIR,priorOrigin=process.env.GRAPHOS_RECEIPT_API_URL;
  process.env.GRAPHOS_RECEIPT_OUTBOX_DIR=directory;process.env.GRAPHOS_RECEIPT_API_URL=origin;
  try {
    const ctx=context();assert.equal(runs(ctx.view)[0]?.outcome,"abandoned");
    await hook.events["model.settled"]!(abandoned,ctx);
    await hook.events["model.settled"]!(abandoned,ctx); // Duplicate callback is a read-only observation.
    assert.equal(receiptRun.get(),null);assert.equal(runWrites.mock.callCount(),0);
    assert.equal(settlementWrites.mock.callCount(),0);assert.equal(network.mock.callCount(),0);
    assert.equal(directHttp.mock.callCount(),0);assert.equal(directHttps.mock.callCount(),0);
    assert.throws(()=>currentReceiptInvocation(binding.session_id),/receipt_model_binding_missing/);
    assert.deepEqual(await contents(directory),before);
  } finally {
    if(priorDirectory===undefined)delete process.env.GRAPHOS_RECEIPT_OUTBOX_DIR;else process.env.GRAPHOS_RECEIPT_OUTBOX_DIR=priorDirectory;
    if(priorOrigin===undefined)delete process.env.GRAPHOS_RECEIPT_API_URL;else process.env.GRAPHOS_RECEIPT_API_URL=priorOrigin;
    await rm(directory,{recursive:true,force:true});
  }
});

test("journal arrival order and identical writes do not change reconstructed identity",async()=>{
  const directory=await mkdtemp(join(tmpdir(),"graphos-abandonment-"));
  try {
    const send=journaledReceiptSender(origin,directory,async()=>({duplicate:true}));
    for(const fact of [...facts].reverse())await send(grant,fact);
    for(const fact of facts)await send(grant,fact);
    assert.equal((await readdir(directory)).length,3);
    const overlap=events();overlap.push(overlap[4]!);
    await assertAbandonedReceiptObservation(abandoned,context(overlap),directory,origin);
    await assertAbandonedReceiptObservation({...abandoned,data:{...abandoned.data,generationId:"gen_original"}},context(),directory,origin);
  } finally {await rm(directory,{recursive:true,force:true});}
});

const recordMutations:Record<string,(values:RecordValue[])=>void>={
  "absent session":v=>{v.splice(0,1);},"absent model start":v=>{v.splice(1,1);},"absent generation":v=>{v.splice(2,1);},
  "wrong GraphOS run":v=>{for(const r of v)r.grant.run_id="other-run";},
  "wrong attempt":v=>{for(const r of v)r.grant.attempt_id="other-attempt";},
  "wrong capability":v=>{v[0]!.grant.capture_token="different_capability_00000000000000000";},
  "wrong origin":v=>{v[0]!.origin="http://127.0.0.1:8282";},"wrong version":v=>{v[0]!.version=2;},
  "wrong session":v=>{v[1]!.event.session_id="other-session";},"wrong task":v=>{v[0]!.event.task_id="other-task";},
  "stale epoch":v=>{v[0]!.event.epoch=2;},"stale revision":v=>{v[0]!.event.revision=2;},
  "stale input":v=>{v[0]!.event.input_hash="b".repeat(64);},
  "wrong model run":v=>{v[1]!.event.model_run_id="run_1";},"wrong model":v=>{v[1]!.event.model_id="other/model";},
  "provider retry":v=>{v[1]!.event.model_attempt=1;},
  "duplicate model identity":v=>{v.push({...v[1]!,event:{...v[1]!.event,event_id:"model_started:duplicate"}});},
  "conflicting generation":v=>{v.push({...v[2]!,event:{...v[2]!.event,event_id:"generation:conflict",generation_id:"gen_conflict"}});},
  "generation reused by another model":v=>{v.push({...v[2]!,event:{...v[2]!.event,event_id:"generation:run_1",model_run_id:"run_1"}});},
  "usage on abandoned model":v=>{v.push({version:1,origin,grant:{...grant},event:{kind:"usage",event_id:"usage:run_0",session_id:binding.session_id,
    model_run_id:"run_0",model_id:MODEL_ID,model_attempt:0,usage:{input_tokens:0,output_tokens:0,cache_read_tokens:0,cache_write_tokens:0,
      actual_cost_microdollars:0,generation_id:"gen_original",finish_reason:null}}});},
};
for(const [name,change] of Object.entries(recordMutations))test(`abandonment rejects ${name}`,async()=>{
  const values=records();change(values);const directory=await fixture(values);
  try {await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);}
  finally {await rm(directory,{recursive:true,force:true});}
});

test("missing, stale, reordered or conflicting runtime observation is rejected",async()=>{
  const directory=await fixture();
  try {
    const ctx=context();
    for(const [event,changed] of [
      [abandoned,context(events().slice(0,4))],
      [abandoned,{...ctx,turn:{...ctx.turn!,id:"turn_1"}}],
      [abandoned,{...ctx,session:{...ctx.session,id:"wrong-session"}}],
      [abandoned,{...ctx,session:{...ctx.session,auth:{initiator:{attributes:{}}}}}],
      [abandoned,{...ctx,now:new Date("2026-11-08T07:29:00.000Z")}],
      [abandoned,{...ctx,now:new Date("invalid")}],
      [{...abandoned,scope:undefined},ctx],
      [{...abandoned,scope:{runId:"run_1",turnId:"turn_0"}},ctx],
      [{...abandoned,scope:{runId:"run_0",turnId:"turn_0",changeId:"change_0"}},ctx],
      [{...abandoned,scope:{runId:"run_0",turnId:"turn_0",taskId:"task_0"}},ctx],
      [{...abandoned,data:{...abandoned.data,generationId:"gen_wrong"}},ctx],
      [{...abandoned,data:{...abandoned.data,outcome:"completed"}},ctx],
    ] as [HookEvent<"model.settled">,HookContext<"model.settled">][])
      await assert.rejects(assertAbandonedReceiptObservation(event,changed,directory,origin),invalid);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("unsupported persisted model and observed usage cannot identify an abandoned invocation",async()=>{
  const directory=await fixture();
  try {
    const changed=events();
    changed[3]={...changed[3]!,data:{runId:"run_0",modelId:"other/model",attempt:0}} as SessionStreamEvent;
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(changed),directory,origin),invalid);
    const usage={type:"usage.recorded",data:{kind:"model",owner:{runId:"run_0"},usage:{inputTokens:0,outputTokens:0,cacheReadTokens:0,cacheWriteTokens:0,costUsd:0}},
      meta:{at,position:{line:5,index:0},endOfLine:true}} as SessionStreamEvent;
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context([...events(),usage]),directory,origin),invalid);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("evidence reader never creates missing storage and rejects corrupt or unsafe records",async()=>{
  const directory=await fixture();
  try {
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),join(directory,"missing"),origin),invalid);
    assert.ok(!(await readdir(directory)).includes("missing"));
    const path=join(directory,filename(records()[2]!)),original=await readFile(path);
    for(const bytes of ["{", "x".repeat(8193)]) {
      await writeFile(path,bytes);await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
    }
    await writeFile(path,original);await chmod(path,0o644);
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
    await chmod(path,0o600);await rename(path,path+".saved");await symlink(path+".saved",path);
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
    await rm(path);await rename(path+".saved",path);await rename(path,join(directory,"0".repeat(64)+".json"));
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("private directory and bounded attempt/file counts are required",async()=>{
  const directory=await fixture(),alias=directory+"-alias";
  try {
    await symlink(directory,alias);
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),alias,origin),invalid);
    await chmod(directory,0o755);
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
    await chmod(directory,0o700);
    for(let n=1;n<=14;n++)await writeRecords(directory,[{version:1,origin,grant:{...grant},event:{...facts[1],model_run_id:`run_${n}`,event_id:`model_started:run_${n}`}}]);
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
    for(const file of await readdir(directory))await rm(join(directory,file));
    await writeRecords(directory);
    for(let n=0;n<4093;n++)await writeFile(join(directory,`.${n}.tmp`),"");
    await assertAbandonedReceiptObservation(abandoned,context(),directory,origin); // 4096 total, complete evidence.
    await writeFile(join(directory,".4093.tmp"),"");
    await assert.rejects(assertAbandonedReceiptObservation(abandoned,context(),directory,origin),invalid);
  } finally {await rm(alias,{force:true});await rm(directory,{recursive:true,force:true});}
});

test("other missing outcomes and non-null mismatched bindings cannot enter restoration",async t=>{
  let live:ReceiptInvocation|null=null;t.mock.method(receiptRun,"get",()=>live);
  const writes=t.mock.method(receiptSettlement,"update",()=>{throw new Error("unexpected write");});
  for(const outcome of ["completed","failed","interrupted"] as const)
    await assert.rejects(async()=>hook.events["model.settled"]!({...abandoned,data:{...abandoned.data,outcome}},context()),/receipt_model_binding_missing/);
  live={...binding,model_run_id:"run_1"};
  await assert.rejects(async()=>hook.events["model.settled"]!(abandoned,context()),/receipt_usage_binding_invalid/);
  live={...binding,session_id:"other-session"};
  await assert.rejects(async()=>hook.events["model.settled"]!(abandoned,context()),/receipt_model_binding_missing/);
  assert.equal(writes.mock.callCount(),0);
});

test("observation recovery cannot bypass the next model's stale-authority registration",async()=>{
  const directory=await fixture();let receiptCalls=0,providerCalls=0;
  try {
    await assertAbandonedReceiptObservation(abandoned,context(),directory,origin);
    const send=receiptSender(origin,async(_url,init)=>{
      receiptCalls++;const event=JSON.parse(String(init?.body)) as ReceiptEvent;
      if(event.kind==="session")return new Response(JSON.stringify({recorded:true,duplicate:true,attempt_id:grant.attempt_id,event_id:event.event_id,kind:event.kind}));
      return new Response(JSON.stringify({detail:"new receipt intent requires an active run"}),{status:409});
    });
    const gateway=createGateway({apiKey:"offline",fetch:async()=>{providerCalls++;throw new Error("must not dispatch");}});
    const model=wrapLanguageModel({model:gateway(MODEL_ID),middleware:earlyReceiptMiddleware(()=>({...binding,model_run_id:"run_1"}),send)});
    await assert.rejects(async()=>model.doStream({prompt:[{role:"user",content:[{type:"text",text:"offline"}]}]}),/receipt_persistence_failed/);
    assert.equal(receiptCalls,2);assert.equal(providerCalls,0);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("completed lifecycle after abandonment cannot create usage or successful generation",async t=>{
  const directory=await fixture();
  t.mock.method(receiptRun,"get",()=>null);t.mock.method(receiptSettlement,"get",()=>null);
  try {
    await assertAbandonedReceiptObservation(abandoned,context(),directory,origin);
    const unknownUsage={type:"usage.recorded",data:{kind:"model",owner:{runId:"run_0"},usage:{inputTokens:0,outputTokens:0,cacheReadTokens:0,cacheWriteTokens:0}}} as HookEvent<"usage.recorded">;
    await assert.rejects(async()=>hook.events["usage.recorded"]!(unknownUsage,context() as HookContext<"usage.recorded">),/receipt_model_binding_missing/);
    const retained=[...events(),{type:"turn.settled",data:{turnId:"turn_0",outcome:"failed"}},
      {type:"session.ended",data:{outcome:"completed"}}] as SessionStreamEvent[];
    const sent:ReceiptEvent[]=[];
    await recoverRetainedReceipts(grant,binding.session_id,retained,async(_grant,event)=>{sent.push(event);return {duplicate:false};});
    assert.deepEqual(sent,[{kind:"session_terminal",event_id:"session_terminal",session_id:binding.session_id,outcome:"completed"}]);
    assert.throws(()=>usageFromEvents(retained),/unreconciled_model_usage/);
    await assert.rejects(generate({claim:{reservation:1_000_000}} as TaskRequest,{async create(){return {
      id:binding.session_id,async result(){return {status:"failed",data:undefined,sessionId:binding.session_id,deliveryId:"delivery"};},
      async events(){return retained;},async cancel(){},async end(){},
    };}}),error=>{
      assert.ok(error instanceof AdapterError);assert.equal(error.costKnown,false);
      assert.equal(error.actualCostMicrodollars,undefined);assert.equal(error.usage,undefined);return true;
    });
  } finally {await rm(directory,{recursive:true,force:true});}
});
