import test from "node:test";
import assert from "node:assert/strict";
import {createServer, type ServerResponse} from "node:http";
import {once} from "node:events";
import {parseRequest} from "../src/contracts.js";
import {eveTransport} from "../src/transport.js";

const sessionId="session-http-lease-test", deliveryId="delivery-one-paid-turn";
const prefix={at:"2026-11-07T00:00:00.000Z",facts:[
  {type:"delivery.admitted",data:{deliveryId,principal:{id:"test",type:"service"},source:{channel:"channel:eve"}}},
  {type:"delivery.consumed",data:{deliveryId,turnId:"turn-0",parts:[]}},
  {type:"turn.started",data:{turnId:"turn-0",cause:{deliveryId},follows:[]}},
]};
const settled={at:"2026-11-07T00:01:01.000Z",facts:[
  {type:"turn.settled",data:{turnId:"turn-0",outcome:"completed",reply:[]}},
  {type:"delivery.settled",data:{deliveryId,turnId:"turn-0",outcome:"handled"}},
]};
const line=(value:unknown)=>JSON.stringify(value)+"\n";

function input() {
  const hash="a".repeat(64);
  return parseRequest(JSON.stringify({claim:{run_id:"run",task_id:"task",task_key:"app",
    epoch:1,revision:1,input_hash:hash,objective:"Test bounded transport",requirements:["Offline app"],
    profile:"local-inventory",suite_hash:hash,policy_hash:hash,reservation:1_000_000},
  profile:{id:"local-inventory",status:"active",required_files:["index.html","app.js","styles.css"],
    acceptance_criteria:["Offline app"],required_checks:["structure"],selector_contract:{},
    suite_hash:hash,policy_hash:hash},dependencies:[]}));
}

async function serverFixture(afterLease:(response:ServerResponse, requestNumber:number)=>void) {
  const requests:{method:string;path:string;startIndex:string|null}[]=[];
  let streamReads=0;
  // Only the HTTP server is simulated. The production transport and installed
  // eve client perform their actual POST/GET, cursor, lease, and abort handling.
  const server=createServer((request,response)=>{
    const url=new URL(request.url!,"http://localhost");
    requests.push({method:request.method!,path:url.pathname,startIndex:url.searchParams.get("startIndex")});
    if(request.method==="POST" && url.pathname==="/eve/v1/session") {
      request.resume();
      response.writeHead(200,{"content-type":"application/json"});
      response.end(JSON.stringify({sessionId,deliveryId}));
      return;
    }
    if(request.method==="GET" && url.pathname===`/eve/v1/session/${sessionId}/stream`) {
      streamReads++;
      if(streamReads===1) {
        response.writeHead(200,{"content-type":"application/x-ndjson","x-eve-stream-version":"27"});
        response.end(line(prefix)+line({$eve:"stream.lease-ended"}));
      } else afterLease(response,streamReads);
      return;
    }
    response.writeHead(404);response.end();
  });
  server.listen(0,"127.0.0.1");
  await once(server,"listening");
  const address=server.address();
  assert.ok(address && typeof address!=="string");
  return {requests,transport:eveTransport(`http://127.0.0.1:${address.port}`,"test-bearer-not-a-provider-key"),
    async close(){server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));}};
}

test("HTTP lease reconnection reads the same accepted delivery without another paid POST", async()=>{
  const server=await serverFixture(response=>{
    response.writeHead(200,{"content-type":"application/x-ndjson","x-eve-stream-version":"27"});
    response.end(line(settled)+line({$eve:"stream.ended"}));
  });
  try {
    const signal=AbortSignal.timeout(2000);
    const session=await server.transport.create(input(),signal);
    const result=await session.result(signal);
    assert.equal(result.status,"completed");
    assert.equal(result.sessionId,sessionId);
    assert.equal(result.deliveryId,deliveryId);
    assert.deepEqual(server.requests,[
      {method:"POST",path:"/eve/v1/session",startIndex:null},
      {method:"GET",path:`/eve/v1/session/${sessionId}/stream`,startIndex:null},
      {method:"GET",path:`/eve/v1/session/${sessionId}/stream`,startIndex:"1"},
    ]);
  } finally {await server.close();}
});

test("reconnected stream cannot outlive the original caller deadline", async()=>{
  const server=await serverFixture(response=>{
    response.writeHead(200,{"content-type":"application/x-ndjson","x-eve-stream-version":"27"});
    response.write(line({$eve:"heartbeat"})); // Keep the read open until aborted.
  });
  try {
    const signal=AbortSignal.timeout(150);
    const started=Date.now();
    const session=await server.transport.create(input(),signal);
    await assert.rejects(session.result(signal),()=>signal.aborted);
    assert.ok(Date.now()-started<1500,"reconnection extended the caller's deadline");
    assert.equal(server.requests.filter(r=>r.method==="POST").length,1);
    assert.equal(server.requests.filter(r=>r.method==="GET").length,2);
    assert.equal(server.requests.at(-1)?.startIndex,"1");
  } finally {await server.close();}
});

test("failed stream reopen attempts are bounded and never resubmit the accepted message", async()=>{
  const server=await serverFixture(response=>{response.writeHead(503);response.end("unavailable");});
  try {
    const signal=AbortSignal.timeout(2000);
    const session=await server.transport.create(input(),signal);
    await assert.rejects(session.result(signal));
    assert.equal(signal.aborted,false,"reopen retry count should exhaust before the outer deadline");
    assert.equal(server.requests.filter(r=>r.method==="POST").length,1);
    assert.equal(server.requests.filter(r=>r.method==="GET").length,4);
    assert.ok(server.requests.slice(2).every(r=>r.startIndex==="1"));
  } finally {await server.close();}
});
