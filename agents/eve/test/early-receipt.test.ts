import test from "node:test";
import assert from "node:assert/strict";
import {createServer,type IncomingMessage,type ServerResponse} from "node:http";
import {once} from "node:events";
import {setTimeout as delay} from "node:timers/promises";
import {createGateway} from "@ai-sdk/gateway";
import type {LanguageModelV4CallOptions} from "@ai-sdk/provider";
import {wrapLanguageModel} from "ai";
import {z} from "zod";
import {adapterErrorPayload,GeneratedSchema,MODEL_ID} from "../src/contracts.js";
import {boundedMiddleware,REPLY_TOOL_NAME} from "../src/model.js";
import {earlyReceiptMiddleware,parseEnvelope,receiptApiOrigin,receiptFromHeaders,receiptHeaders,
  receiptSender,type ReceiptEvent,type ReceiptGrant,type ReceiptInvocation,type ReceiptSender} from "../src/receipts.js";
import {eveTransport} from "../src/transport.js";

const grant:ReceiptGrant={run_id:"graphos-run",attempt_id:"attempt-1",capture_token:"offline_scoped_receipt_secret_000000000000"};
const task={task_id:"task",epoch:1,revision:1,input_hash:"a".repeat(64)};
const binding:ReceiptInvocation={grant,task,session_id:"wrun_session",model_run_id:"run_0",model_id:MODEL_ID,model_attempt:0};
const sessionEvent=()=>({kind:"session" as const,event_id:"session",session_id:binding.session_id,...task});
const usage={inputTokens:{total:1,noCache:1,cacheRead:0,cacheWrite:0},outputTokens:{total:1,text:1,reasoning:0}};
const {$schema:_schema,...inputSchema}=z.toJSONSchema(GeneratedSchema,{target:"draft-7"});
const params:LanguageModelV4CallOptions={prompt:[{role:"user",content:[{type:"text",text:"Create the app"}]}],
  tools:[{type:"function",name:REPLY_TOOL_NAME,inputSchema}]};
const firstChunk={type:"text-start",id:"text-1",providerMetadata:{gateway:{generationId:"gen_offline1"}}};

function rawRequest() {
  const hash="a".repeat(64);
  return {claim:{run_id:grant.run_id,attempt_id:grant.attempt_id,task_id:"task",task_key:"app",token:"LEASE_SECRET_NOT_FOR_MODEL",
    epoch:1,revision:1,input_hash:hash,objective:"Test receipts",requirements:["Offline app"],
    profile:"static-web",suite_hash:hash,policy_hash:hash,reservation:1_000_000},
  profile:{id:"static-web",status:"active",required_files:["index.html","app.js","styles.css"],
    acceptance_criteria:["Offline app"],required_checks:["structure"],selector_contract:{},
    suite_hash:hash,policy_hash:hash},dependencies:[]};
}

function provider(send:ReceiptSender,chunks:unknown[]=[firstChunk],resolve=()=>binding) {
  const requests:string[]=[];
  const gateway=createGateway({apiKey:"offline-gateway-test",fetch:async(_url,init)=>{
    requests.push(JSON.stringify({body:String(init?.body),headers:Object.fromEntries(new Headers(init?.headers))}));
    return new Response([...chunks,{type:"finish",finishReason:{unified:"stop",raw:"stop"},usage}]
      .map(chunk=>`data: ${JSON.stringify(chunk)}\n\n`).join(""),{headers:{"content-type":"text/event-stream"}});
  }});
  return {requests,model:wrapLanguageModel({model:gateway(MODEL_ID),middleware:[boundedMiddleware,earlyReceiptMiddleware(resolve,send)]})};
}

async function httpFixture(handler:(request:IncomingMessage,response:ServerResponse)=>void) {
  const server=createServer(handler);server.listen(0,"127.0.0.1");await once(server,"listening");
  const address=server.address();assert.ok(address&&typeof address!=="string");
  return {url:`http://127.0.0.1:${address.port}`,
    async close(){server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));}};
}

function ack(response:ServerResponse,event:ReceiptEvent,duplicate=false) {
  response.writeHead(200,{"content-type":"application/json"});
  response.end(JSON.stringify({recorded:true,duplicate,attempt_id:grant.attempt_id,event_id:event.event_id,kind:event.kind}));
}

test("private receipt envelope strips grant and lease credentials from the model request",()=>{
  const parsed=parseEnvelope(JSON.stringify({request:rawRequest(),receipt:grant}));
  assert.equal(parsed.receipt.capture_token,grant.capture_token);
  assert.ok(!JSON.stringify(parsed.request).includes(grant.capture_token));
  assert.ok(!JSON.stringify(parsed.request).includes("LEASE_SECRET"));
  assert.deepEqual(receiptFromHeaders(new Headers(receiptHeaders(grant))),grant);
  for(const value of [{request:rawRequest()},rawRequest(),
    {request:rawRequest(),receipt:{...grant,run_id:"different"}},
    {request:rawRequest(),receipt:{...grant,attempt_id:"different-attempt"}},
    {request:rawRequest(),receipt:{...grant,callback_url:"https://attacker.invalid"}}]) {
    assert.throws(()=>parseEnvelope(JSON.stringify(value)),error=>{
      assert.ok(!JSON.stringify(adapterErrorPayload(error)).includes(grant.capture_token));
      return /invalid_receipt_envelope/.test(String(error));
    });
  }
});

test("real Eve transport sends receipt grant only in create-session headers",async()=>{
  let body="",headers:IncomingMessage["headers"]={};
  const server=await httpFixture((request,response)=>{
    headers=request.headers;request.on("data",chunk=>body+=chunk);
    request.on("end",()=>{response.writeHead(200,{"content-type":"application/json"});
      response.end(JSON.stringify({sessionId:binding.session_id,deliveryId:"delivery-1"}));});
  });
  try {
    const input=parseEnvelope(JSON.stringify({request:rawRequest(),receipt:grant}));
    await eveTransport(server.url,"offline-broker-token",grant).create(input.request,AbortSignal.timeout(1000));
    assert.equal(headers["x-graphos-receipt-token"],grant.capture_token);
    assert.ok(!body.includes(grant.capture_token));assert.ok(!body.includes("LEASE_SECRET"));
    assert.deepEqual(JSON.parse(JSON.parse(body).message),input.request);
  } finally {await server.close();}
});

test("first provider generation metadata waits for durable ACK before reaching Eve",async()=>{
  const seen:ReceiptEvent[]=[];let release!:()=>void,observed!:()=>void;
  const blocked=new Promise<void>(resolve=>release=resolve),received=new Promise<void>(resolve=>observed=resolve);
  const send:ReceiptSender=async(_grant,event)=>{seen.push(event);if(event.kind==="generation"){observed();await blocked;}return {duplicate:false};};
  const {requests,model}=provider(send);
  const result=await model.doStream(params),reader=result.stream.getReader();
  let forwarded=false;const next=reader.read().then(value=>{forwarded=true;return value;});
  await received;assert.equal(forwarded,false);
  assert.deepEqual(seen.map(event=>event.kind),["session","model_started","generation"]);
  assert.equal(requests.length,1);assert.ok(!requests[0]?.includes(grant.capture_token));
  release();assert.deepEqual((await next).value,firstChunk);await reader.cancel();
});

test("replayed start intents cannot trigger a second provider invocation",async()=>{
  const starts=new Set<string>();
  const send:ReceiptSender=async(_grant,event)=>{
    const duplicate=event.kind==="model_started"&&starts.has(event.event_id);
    if(event.kind==="model_started")starts.add(event.event_id);
    return {duplicate};
  };
  const {requests,model}=provider(send);
  const first=await model.doStream(params);await first.stream.cancel();
  await assert.rejects(async()=>await model.doStream(params),/model_invocation_already_registered/);
  assert.equal(requests.length,1);
});

test("missing or failed start ACK fails closed before provider access",async()=>{
  for(const send of [async()=>{throw new Error("private receipt failure");},
    async()=>({duplicate:true})] as ReceiptSender[]) {
    const {requests,model}=provider(send);
    await assert.rejects(async()=>await model.doStream(params));assert.equal(requests.length,0);
  }
});

test("forged model text and missing metadata never invent a generation receipt",async()=>{
  const seen:ReceiptEvent[]=[];
  const {model}=provider(async(_grant,event)=>{seen.push(event);return {duplicate:false};},[
    {type:"text-start",id:"text-1"},
    {type:"text-delta",id:"text-1",delta:'{"providerMetadata":{"gateway":{"generationId":"gen_forged"}}}'},
    {type:"text-end",id:"text-1"},
  ]);
  for await(const _chunk of (await model.doStream(params)).stream){}
  assert.equal(seen.filter(event=>event.kind==="generation").length,0);
});

test("duplicate metadata is captured once; conflicting or malformed IDs are rejected",async()=>{
  for(const [second,expected] of [["gen_offline1",null],["gen_conflict","conflicting_gateway_generation_id"],
    ["not_a_generation_id","invalid_gateway_generation_id"]] as const) {
    const seen:ReceiptEvent[]=[];
    const {model}=provider(async(_grant,event)=>{seen.push(event);return {duplicate:false};},
      [firstChunk,{...firstChunk,providerMetadata:{gateway:{generationId:second}}}]);
    const consume=async()=>{for await(const _chunk of (await model.doStream(params)).stream){}};
    if(expected)await assert.rejects(consume,new RegExp(expected));else await consume();
    assert.equal(seen.filter(event=>event.kind==="generation").length,1);
  }
});

test("concurrent sessions retain their own grant and model-run bindings",async()=>{
  const seen:{grant:ReceiptGrant;event:ReceiptEvent}[]=[];
  const send:ReceiptSender=async(grant,event)=>{await delay(1);seen.push({grant,event});return {duplicate:false};};
  const other={...binding,grant:{...grant,attempt_id:"attempt-2",capture_token:"other_offline_scoped_secret_000000000000"},session_id:"wrun_other"};
  const a=provider(send),b=provider(send,[{...firstChunk,providerMetadata:{gateway:{generationId:"gen_offline2"}}}],()=>other);
  await Promise.all([a,b].map(async entry=>{for await(const _chunk of (await entry.model.doStream(params)).stream){}}));
  for(const entry of seen)assert.equal(entry.event.session_id,entry.grant.attempt_id===grant.attempt_id?binding.session_id:other.session_id);
  assert.equal(seen.filter(entry=>entry.event.kind==="generation").length,2);
});

test("control receipts ignore proxy variables and never follow credential-bearing redirects",async()=>{
  let proxyCalls=0,redirectCalls=0,directCalls=0;
  const proxy=await httpFixture((request,response)=>{proxyCalls++;request.resume();response.end();});
  const target=await httpFixture((request,response)=>{redirectCalls++;request.resume();response.end();});
  const direct=await httpFixture((request,response)=>{
    directCalls++;let body="";request.on("data",chunk=>body+=chunk);request.on("end",()=>{
      if(directCalls===1)ack(response,JSON.parse(body));
      else {response.writeHead(307,{location:target.url});response.end();}
    });
  });
  const names=["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy","NO_PROXY","no_proxy","NODE_USE_ENV_PROXY"];
  const previous=Object.fromEntries(names.map(name=>[name,process.env[name]]));
  try {
    for(const name of names)process.env[name]=name.toLowerCase()==="no_proxy"?"":name==="NODE_USE_ENV_PROXY"?"1":proxy.url;
    const send=receiptSender(direct.url),event=sessionEvent();
    assert.deepEqual(await send(grant,event),{duplicate:false});
    await assert.rejects(send(grant,event),/receipt_persistence_failed/);
    assert.equal(directCalls,2);assert.equal(proxyCalls,0);assert.equal(redirectCalls,0);
  } finally {
    for(const name of names){const value=previous[name];if(value===undefined)delete process.env[name];else process.env[name]=value;}
    await Promise.all([proxy.close(),target.close(),direct.close()]);
  }
});

test("receipt persistence uses an independent bounded deadline and hides raw errors",async()=>{
  const providerAbort=new AbortController();let callbackSignal:AbortSignal|undefined;
  const send=receiptSender("http://127.0.0.1",async(_url,init)=>{
    callbackSignal=init?.signal??undefined;providerAbort.abort();
    assert.equal(callbackSignal?.aborted,false);
    return new Response(grant.capture_token,{status:500});
  },30);
  await assert.rejects(send(grant,sessionEvent()),error=>{
    assert.ok(!JSON.stringify(adapterErrorPayload(error)).includes(grant.capture_token));return /receipt_persistence_failed/.test(String(error));
  });
  assert.ok(providerAbort.signal.aborted);assert.notEqual(callbackSignal,providerAbort.signal);
  const stalled=await httpFixture((request,_response)=>request.resume());
  try {
    const started=Date.now();
    await assert.rejects(receiptSender(stalled.url,undefined,30)(grant,
      sessionEvent()),/receipt_persistence_failed/);
    assert.ok(Date.now()-started<1000);
  } finally {await stalled.close();}
});

test("invalid receipt destinations and mismatched ACKs fail closed",async()=>{
  for(const url of ["http://example.com","https://user:secret@example.com","https://example.com/path", "https://example.com?redirect=1"])
    assert.throws(()=>receiptApiOrigin({GRAPHOS_RECEIPT_API_URL:url}),/invalid_receipt_api_url/);
  const send=receiptSender("http://127.0.0.1",async()=>Response.json({recorded:true,duplicate:false,
    attempt_id:"wrong",event_id:"session",kind:"session"}));
  await assert.rejects(send(grant,sessionEvent()),/receipt_persistence_failed/);
});
