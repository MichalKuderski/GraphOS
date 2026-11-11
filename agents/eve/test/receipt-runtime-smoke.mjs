// Real compiled Eve hooks, session context and GraphOS middleware. Only the
// Gateway HTTP fetch is replaced, inside a disposable copied project.
import {spawn} from "node:child_process";
import {createServer} from "node:http";
import {once} from "node:events";
import {mkdtemp,cp,symlink,writeFile,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,resolve} from "node:path";
import {setTimeout as delay} from "node:timers/promises";
import assert from "node:assert/strict";
import {replayReceiptJournal,journaledReceiptSender} from "../dist/src/receipt-journal.js";
import {recoverRetainedReceipts} from "../dist/src/receipt-recovery.js";
import {eveTransport} from "../dist/src/transport.js";
import {parseEnvelope,ReceiptEventSchema,receiptHeaders} from "../dist/src/receipts.js";

const source=resolve(new URL("..",import.meta.url).pathname);
const fixture=await mkdtemp(join(tmpdir(),"graphos-eve-receipt-smoke-"));
const brokerToken="offline_fixture_broker_credential_000000000000";
const hash="a".repeat(64),defaultGrant={run_id:"fixture-run",attempt_id:"fixture-attempt",
  capture_token:"offline_fixture_scoped_receipt_000000000000"};
const externalFile=process.env.GRAPHOS_RECEIPT_SMOKE_ENVELOPE_FILE;
const external=Boolean(externalFile);
const mode=process.env.GRAPHOS_RECEIPT_SMOKE_MODE??"happy";
assert.ok(["happy","interrupt","kill-before-generation","kill-after-generation","kill-usage","kill-terminal"].includes(mode));
if(external&&process.env.GRAPHOS_RECEIPT_SMOKE_ALLOW_FAKE_RECEIPTS!=="1")
  throw new Error("external fixture requires explicit synthetic-receipt authorization");
const envelope=parseEnvelope(external?await readFile(externalFile,"utf8"):JSON.stringify({
  receipt:defaultGrant,request:{claim:{run_id:defaultGrant.run_id,attempt_id:defaultGrant.attempt_id,
    task_id:"fixture-task",task_key:"app",epoch:1,revision:1,input_hash:hash,
    objective:"Return the offline fixture",requirements:["Offline fixture"],profile:"static-web",
    suite_hash:hash,policy_hash:hash,reservation:1_000_000},
  profile:{id:"static-web",status:"active",required_files:["index.html","app.js","styles.css"],
    acceptance_criteria:["Offline fixture"],required_checks:["structure"],selector_contract:{},
    suite_hash:hash,policy_hash:hash},dependencies:[]}}));
let child,logs="",callback;
const receipts=[];let releaseGeneration,receivedGeneration,recovering=false;
const journalDirectory=join(fixture,"receipt-outbox");
const blockedKind=mode==="kill-usage"?"usage":mode==="kill-terminal"?"session_terminal":"generation";
const generationReceived=new Promise(resolve=>receivedGeneration=resolve);
const generationAck=new Promise(resolve=>releaseGeneration=resolve);
const auditPath=join(fixture,"provider-audit.jsonl");
const audit=async()=>{try{return (await readFile(auditPath,"utf8")).trim().split("\n").filter(Boolean).map(JSON.parse);}catch{return [];}};
const runtimeEnv={PATH:process.env.PATH,HOME:process.env.HOME,NODE_EXTRA_CA_CERTS:process.env.NODE_EXTRA_CA_CERTS,
  GRAPHOS_EVE_TOKEN:brokerToken,EVE_SCHEDULES_DISABLED:"1",EVE_TELEMETRY_DISABLED:"1",
  GRAPHOS_LIVE_ENABLED:"1",GRAPHOS_GATEWAY_BUDGET_USD:"0.01",AI_GATEWAY_API_KEY:"offline-fixture-not-a-provider-key",
  GRAPHOS_FIXTURE_RECEIPT_TOKEN:envelope.receipt.capture_token,GRAPHOS_FIXTURE_AUDIT_PATH:auditPath,
  GRAPHOS_RECEIPT_OUTBOX_DIR:journalDirectory,GRAPHOS_FIXTURE_MODE:mode,
  GRAPHOS_FIXTURE_GENERATION_ID:"gen_fixture_"+envelope.receipt.attempt_id};

async function runBuild() {
  const build=spawn(process.execPath,[join(source,"node_modules/eve/bin/eve.js"),"build"],
    {cwd:fixture,env:runtimeEnv,stdio:["ignore","pipe","pipe"]});
  let tail="";for(const stream of [build.stdout,build.stderr])stream.on("data",chunk=>tail=(tail+chunk).slice(-2000));
  const [code]=await once(build,"exit");
  // Build output is not dumped: later runtime failures may include private
  // session context. A fixed failure is enough for CI; fixture logs stay local.
  if(code!==0)throw new Error("temporary Eve fixture build failed");
}

try {
  for(const name of ["agent","src","package.json","package-lock.json","tsconfig.json"])
    await cp(join(source,name),join(fixture,name),{recursive:true});
  await symlink(join(source,"node_modules"),join(fixture,"node_modules"),"dir");
  const modelPath=join(fixture,"src/model.ts"),model=await readFile(modelPath,"utf8");
  assert.equal(model.split("model: gateway(MODEL_ID)").length,2,"fixture must replace exactly the Gateway factory");
  await writeFile(modelPath,'import {fakeGateway} from "../fixture-provider.js";\n'+
    model.replace("model: gateway(MODEL_ID)","model: fakeGateway(MODEL_ID)"));
  await writeFile(join(fixture,"fixture-provider.ts"),`
import {createGateway} from "@ai-sdk/gateway";
import {appendFile} from "node:fs/promises";
export const fakeGateway=createGateway({apiKey:"offline-fixture",fetch:async(_url,init)=>{
  const body=String(init?.body),parsed=JSON.parse(body);
  const secrets=[process.env.GRAPHOS_FIXTURE_RECEIPT_TOKEN,process.env.GRAPHOS_EVE_TOKEN];
  if(secrets.some(secret=>secret&&body.includes(secret)))throw new Error("fixture_secret_exposure");
  if(parsed.tools?.length!==1||parsed.tools[0].name!=="eve__reply"||parsed.tools[0].strict!==true||
     parsed.toolChoice?.toolName!=="eve__reply")throw new Error("fixture_reply_contract");
  await appendFile(process.env.GRAPHOS_FIXTURE_AUDIT_PATH!,JSON.stringify({request_safe:true,strict:true})+"\\n");
  const metadata={gateway:{generationId:process.env.GRAPHOS_FIXTURE_GENERATION_ID,cost:"0"}};
  const files={"index.html":"<!doctype html><main>Offline fixture</main>","app.js":"'use strict';","styles.css":"body{color:#111}"};
  const chunks=[{type:"stream-start",warnings:[]},
    {type:"tool-input-start",id:"fixture-tool",toolName:"eve__reply",providerMetadata:metadata},
    {type:"tool-input-delta",id:"fixture-tool",delta:JSON.stringify({files})},
    {type:"tool-input-end",id:"fixture-tool"},
    {type:"tool-call",toolCallId:"fixture-tool",toolName:"eve__reply",input:JSON.stringify({files}),providerMetadata:metadata},
    {type:"finish",finishReason:{unified:"tool-calls",raw:"tool_calls"},providerMetadata:metadata,
      usage:{inputTokens:{total:1,noCache:1,cacheRead:0,cacheWrite:0},outputTokens:{total:1,text:1,reasoning:0}}}];
  const encode=chunk=>new TextEncoder().encode("data: "+JSON.stringify(chunk)+"\\n\\n");
  const stream=new ReadableStream({start(controller){
    if(process.env.GRAPHOS_FIXTURE_MODE==="interrupt"){
      for(const chunk of chunks.slice(0,2))controller.enqueue(encode(chunk));
      setTimeout(()=>controller.error(new Error("offline_interrupted_stream")),750);
    }else{for(const chunk of chunks)controller.enqueue(encode(chunk));controller.close();}
  }});
  return new Response(stream,{headers:{"content-type":"text/event-stream"}});
}});
`);
  const identities=new Map();
  callback=createServer(async(request,response)=>{
    try {
      assert.equal(request.headers.authorization,`Bearer ${envelope.receipt.capture_token}`);
      assert.equal(request.url,`/v1/runs/${envelope.receipt.run_id}/attempts/${envelope.receipt.attempt_id}/receipts`);
      let body="";for await(const chunk of request){body+=chunk;if(body.length>4096)throw new Error("limit");}
      const event=ReceiptEventSchema.parse(JSON.parse(body)),previous=identities.get(event.event_id);
      if(previous)assert.deepEqual(event,previous);
      if(event.kind==="model_started"&&!previous)assert.equal((await audit()).length,0,"start must precede provider invocation");
      const blocked=!recovering&&event.kind===blockedKind;
      if(blocked&&mode!=="kill-after-generation"){
        receivedGeneration();await generationAck;
        // Death closes the outstanding HTTP connection. Do not accidentally
        // commit its old held callback when opening the recovery barrier.
        if(response.destroyed)return;
      }
      let ack={recorded:true,duplicate:Boolean(previous),attempt_id:envelope.receipt.attempt_id,event_id:event.event_id,kind:event.kind};
      if(external){
        const result=await fetch(process.env.GRAPHOS_RECEIPT_SMOKE_API_URL+request.url,{method:"POST",
          headers:{authorization:request.headers.authorization,"content-type":"application/json"},body,
          signal:AbortSignal.timeout(3000),redirect:"error"});
        if(!result.ok){response.writeHead(result.status);response.end();return;}
        ack=await result.json();
      }
      if(!previous){identities.set(event.event_id,event);receipts.push(event);}
      if(blocked&&mode==="kill-after-generation"){receivedGeneration();await generationAck;if(response.destroyed)return;}
      response.writeHead(200,{"content-type":"application/json"});response.end(JSON.stringify(ack));
    } catch {if(!response.destroyed){response.writeHead(409);response.end();}}
  });
  callback.listen(0,"127.0.0.1");await once(callback,"listening");
  runtimeEnv.GRAPHOS_RECEIPT_API_URL=`http://127.0.0.1:${callback.address().port}`;
  await runBuild();
  const reserve=createServer();reserve.listen(0,"127.0.0.1");await once(reserve,"listening");
  const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
  const baseUrl=`http://127.0.0.1:${port}`;
  child=spawn(process.execPath,[join(source,"node_modules/eve/bin/eve.js"),"start","--host","127.0.0.1","--port",String(port),"--no-schedules"],
    {cwd:fixture,env:runtimeEnv,stdio:["ignore","pipe","pipe"],detached:true});
  for(const stream of [child.stdout,child.stderr])stream.on("data",chunk=>logs=(logs+chunk).slice(-12000));
  let ready=false;
  for(let i=0;i<120;i++){
    if(child.exitCode!==null)throw new Error("temporary Eve fixture exited");
    try{if((await fetch(baseUrl+"/eve/v1/health",{signal:AbortSignal.timeout(500)})).ok){ready=true;break;}}catch{}
    await delay(250);
  }
  assert.ok(ready,"temporary Eve fixture startup timeout");
  const request={...envelope.request,claim:{...envelope.request.claim,attempt_id:"wrong-attempt"}};
  const denied=await fetch(baseUrl+"/eve/v1/session",{method:"POST",
    headers:{authorization:`Bearer ${brokerToken}`,"content-type":"application/json",...receiptHeaders(envelope.receipt)},
    body:JSON.stringify({message:JSON.stringify(request)}),signal:AbortSignal.timeout(2000)});
  assert.ok(!denied.ok,"channel must reject a crossed attempt before creating paid work");
  const signal=AbortSignal.timeout(15_000);
  const session=await eveTransport(baseUrl,brokerToken,envelope.receipt).create(envelope.request,signal);
  const resultPromise=session.result(signal);
  // Attach rejection immediately: death deliberately disconnects this stream.
  const observedResult=resultPromise.then(value=>({value}),()=>({failed:true}));
  let endPromise;
  if(mode==="kill-terminal"){
    const result=await resultPromise;assert.equal(result.status,"completed");
    endPromise=session.end(AbortSignal.timeout(5000)).catch(()=>undefined);
  }
  await Promise.race([generationReceived,delay(12_000,undefined,{ref:false}).then(()=>{throw new Error("receipt callback deadline");})]);
  const prefix=await session.events(AbortSignal.timeout(2000));
  if(blockedKind==="generation")assert.ok(!prefix.some(event=>event.type==="call.started"||event.type==="content.completed"),
    "provider chunk escaped before receipt ACK");
  let recovery=null,retainedRecovery=null;
  if(mode.startsWith("kill-")){
    if(mode==="kill-usage")assert.ok(prefix.some(event=>event.type==="usage.recorded"),"usage must be retained before hook callback");
    if(mode==="kill-terminal")assert.ok(prefix.some(event=>event.type==="session.ended"),"terminal must be retained before channel callback");
    process.kill(-child.pid,"SIGKILL");await once(child,"exit");child=undefined;
    await observedResult;
    if(endPromise)await endPromise;
    const before=receipts.map(event=>event.kind);
    assert.equal(before.includes(blockedKind),mode==="kill-after-generation");
    recovering=true;releaseGeneration();await delay(50);
    // Replay only callbacks. Never restart Eve or the provider after a kill.
    // For usage/terminal use the authenticated retained snapshot FIRST to
    // exercise recovery independent of whether the handler journal existed.
    if(mode==="kill-usage"||mode==="kill-terminal"){
      retainedRecovery=await recoverRetainedReceipts(envelope.receipt,session.id,prefix,
        journaledReceiptSender(runtimeEnv.GRAPHOS_RECEIPT_API_URL,journalDirectory));
      assert.ok(retainedRecovery.recorded>=1);
    }
    recovery=await replayReceiptJournal(runtimeEnv.GRAPHOS_RECEIPT_API_URL,journalDirectory,
      envelope.receipt.run_id,envelope.receipt.attempt_id);
    assert.equal(recovery.pending,0);assert.ok(receipts.some(event=>event.kind===blockedKind));
    const duplicate=await replayReceiptJournal(runtimeEnv.GRAPHOS_RECEIPT_API_URL,journalDirectory,
      envelope.receipt.run_id,envelope.receipt.attempt_id);
    assert.equal(duplicate.recorded,duplicate.duplicates);
    assert.equal((await audit()).length,1);
  }else{
    releaseGeneration();
    const result=await observedResult;
    if(mode==="happy")assert.equal(result.value?.status,"completed");
    else assert.ok(result.failed||result.value?.status!=="completed","interrupted stream must not complete");
    await session.end(AbortSignal.timeout(5000));
    for(let i=0;i<100&&!receipts.some(event=>event.kind==="session_terminal");i++)await delay(20);
    if(mode==="happy"){
      assert.deepEqual(receipts.map(event=>event.kind),["session","model_started","generation","usage","session_terminal"]);
      assert.equal(receipts.find(event=>event.kind==="usage").usage.actual_cost_microdollars,0);
    }else assert.ok(!receipts.some(event=>event.kind==="usage"),"incomplete stream must not fabricate zero usage");
    assert.ok(receipts.some(event=>event.kind==="session_terminal"));
  }
  assert.equal((await audit()).length,1);
  assert.ok(receipts.every(event=>event.session_id===session.id));
  const runIds=receipts.flatMap(event=>"model_run_id"in event?[event.model_run_id]:[]);
  assert.equal(new Set(runIds).size,1);
  console.log(JSON.stringify({mode,real_eve_receipt_hooks:true,strict_reply:true,crossed_attempt_rejected:true,
    trusted_run_binding:true,early_metadata_ack_barrier:blockedKind==="generation",captured:receipts.map(event=>event.kind),
    recovery,retainedRecovery,secret_free_provider_request:true,fixture_model_calls:1,live_model_calls:0,
    actual_model_cost_microdollars:0,settles_cost:false,
    callback:external?"disposable_api_postgres_fixture":"strict_offline_http_fixture"}));
} finally {
  releaseGeneration?.();
  if(child&&child.exitCode===null){try{process.kill(-child.pid,"SIGTERM");}catch{}await Promise.race([once(child,"exit"),delay(3000)]);
    if(child.exitCode===null)try{process.kill(-child.pid,"SIGKILL");}catch{}}
  if(callback){callback.closeAllConnections();await new Promise(resolve=>callback.close(resolve));}
  await rm(fixture,{recursive:true,force:true});
}
