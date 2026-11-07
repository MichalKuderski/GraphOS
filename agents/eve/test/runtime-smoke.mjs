// Compiled eve runtime and real eve/client; no mocked server and no model credentials.
import {spawn} from "node:child_process";
import assert from "node:assert/strict";
import {setTimeout as delay} from "node:timers/promises";
import {Client, SessionNotActiveError} from "eve/client";
import {waitForRetirement} from "../dist/src/transport.js";

const token = "graphos-offline-smoke-credential-000000000000";
const baseUrl = "http://127.0.0.1:3009";
const env = {PATH:process.env.PATH, HOME:process.env.HOME, NODE_EXTRA_CA_CERTS:process.env.NODE_EXTRA_CA_CERTS,
  GRAPHOS_EVE_TOKEN:token, EVE_SCHEDULES_DISABLED:"1"};
const child=spawn(process.execPath,["node_modules/eve/bin/eve.js","start","--host","127.0.0.1","--port","3009","--no-schedules"],
  {env,stdio:["ignore","pipe","pipe"],detached:true});
let logs="";
for (const stream of [child.stdout,child.stderr]) stream.on("data",chunk=>{logs=(logs+chunk.toString()).slice(-12000);});
try {
  let ready=false;
  for(let attempt=0;attempt<120;attempt++) {
    if(child.exitCode!==null) throw new Error("eve exited during startup");
    try {const health=await fetch(baseUrl+"/eve/v1/health",{signal:AbortSignal.timeout(500)});
      if(health.ok){ready=true;break;}}catch{}
    await delay(250);
  }
  assert.ok(ready,"compiled eve server did not become ready");
  assert.equal((await fetch(baseUrl+"/eve/v1/info")).status,401);
  assert.equal((await fetch(baseUrl+"/eve/v1/info",{headers:{authorization:token}})).status,401);
  const client=new Client({baseUrl,auth:{bearer:token}});
  const info=await client.info({signal:AbortSignal.timeout(3000)});
  assert.ok(info,"real public client reads authenticated compiled server info");
  // No message is sent: this tests terminal receipt retention without a model.
  // Private sessions otherwise default to zero retention, which can delete the
  // stream before the broker reads the accepted end command's settlement.
  const {session:idle}=await client.sessions.create({signal:AbortSignal.timeout(3000)});
  let endCommand;
  for(let attempt=0;attempt<20;attempt++) {
    await delay(100);
    try {
      endCommand=await idle.end({signal:AbortSignal.timeout(3000)});
      break;
    } catch(error) {
      // A just-created idle workflow can precede its command inbox. This error
      // explicitly means no delivery was accepted; never repeat accepted ends.
      if(!SessionNotActiveError.is(error) || error.code!=="session_not_active") throw error;
    }
  }
  assert.ok(endCommand,"idle session did not accept bounded retirement request");
  // Invoke the same broker helper immediately: end.result() alone can read a
  // finite prefix before the command settles and incorrectly reject the build.
  await waitForRetirement(idle,endCommand.deliveryId,AbortSignal.timeout(5000));
  await delay(250); // Must read after retirement, not win its deletion race.
  const retired=await endCommand.result({signal:AbortSignal.timeout(5000)});
  assert.equal(retired.status,"completed");
  assert.equal(retired.sessionEnded,true);
  const retained=await idle.snapshot({signal:AbortSignal.timeout(5000)});
  assert.ok(retained.events.some(event=>event.type==="session.ended"));
  assert.equal(retained.events.filter(event=>event.type==="model.started").length,0);
  await assert.rejects(waitForRetirement(idle,"wrong-retirement-delivery",AbortSignal.timeout(50)),
    "a different delivery cannot certify retirement");
  const response=await client.fetch("/eve/v1/session",{method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({message:"{}"}),signal:AbortSignal.timeout(3000)});
  assert.ok(!response.ok,"missing Gateway credentials must prevent a model request");
  console.log(JSON.stringify({compiled_server:true,public_eve_client:true,anonymous_info_rejected:true,
    raw_token_rejected:true,model_generation_without_credentials_rejected:true,
    immediate_end_receipt_poll:true,delayed_end_receipt_read:true,post_end_history_retained:true,
    wrong_retirement_delivery_rejected:true,idle_model_calls:0,live_model_calls:0}));
}catch(error){
  console.error(logs); throw error;
}finally{
  try{process.kill(-child.pid,"SIGTERM");}catch{}
  await Promise.race([new Promise(resolve=>child.once("exit",resolve)),delay(2000)]);
  try{process.kill(-child.pid,"SIGKILL");}catch{}
}
