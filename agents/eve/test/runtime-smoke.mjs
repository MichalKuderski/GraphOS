// Compiled eve runtime and real eve/client; no mocked server and no model credentials.
import {spawn} from "node:child_process";
import assert from "node:assert/strict";
import {setTimeout as delay} from "node:timers/promises";
import {Client} from "eve/client";

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
  const response=await client.fetch("/eve/v1/session",{method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({message:"{}"}),signal:AbortSignal.timeout(3000)});
  assert.ok(!response.ok,"missing Gateway credentials must prevent a model request");
  console.log(JSON.stringify({compiled_server:true,public_eve_client:true,anonymous_info_rejected:true,
    raw_token_rejected:true,model_generation_without_credentials_rejected:true,live_model_calls:0}));
}catch(error){
  console.error(logs); throw error;
}finally{
  try{process.kill(-child.pid,"SIGTERM");}catch{}
  await Promise.race([new Promise(resolve=>child.once("exit",resolve)),delay(2000)]);
  try{process.kill(-child.pid,"SIGKILL");}catch{}
}
