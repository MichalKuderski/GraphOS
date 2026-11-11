import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,readdir,readFile,stat,chmod} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import type {SessionStreamEvent} from "eve/client";
import {MODEL_ID} from "../src/contracts.js";
import {journaledReceiptSender,replayReceiptJournal} from "../src/receipt-journal.js";
import {recoverRetainedReceipts} from "../src/receipt-recovery.js";
import type {ReceiptEvent,ReceiptSender} from "../src/receipts.js";

const grant={run_id:"run",attempt_id:"attempt",capture_token:"offline_receipt_capability_000000000000"};
const origin="http://127.0.0.1:8181";
const generation:ReceiptEvent={kind:"generation",event_id:"generation:model",session_id:"session",
  model_run_id:"model",model_id:MODEL_ID,model_attempt:0,generation_id:"gen_offline"};

for(const committed of [false,true])test(`journal recovers callback ${committed?"committed with lost ACK":"failed before commit"} without another provider call`,async()=>{
  const directory=await mkdtemp(join(tmpdir(),"graphos-receipt-journal-"));
  let persisted=false;
  try {
    await assert.rejects(journaledReceiptSender(origin,directory,async()=>{persisted=committed;throw new Error("lost");})(grant,generation));
    const files=await readdir(directory);assert.equal(files.length,1);
    assert.equal((await stat(join(directory,files[0]!))).mode&0o777,0o600);
    assert.deepEqual(JSON.parse(await readFile(join(directory,files[0]!),"utf8")).event,generation);
    const send:ReceiptSender=async(_grant,event)=>{assert.deepEqual(event,generation);const duplicate=persisted;persisted=true;return {duplicate};};
    const recovery=await replayReceiptJournal(origin,directory,grant.run_id,grant.attempt_id,send);
    assert.deepEqual(recovery,{recorded:1,duplicates:Number(committed),pending:0,settles_cost:false,provider_calls:0});
    assert.equal((await replayReceiptJournal(origin,directory,grant.run_id,grant.attempt_id,send)).duplicates,1);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("journal refuses conflicting identities, unsafe permissions and origin substitution before callbacks",async()=>{
  const directory=await mkdtemp(join(tmpdir(),"graphos-receipt-journal-"));let calls=0;
  const send=journaledReceiptSender(origin,directory,async()=>{calls++;return {duplicate:false};});
  try {
    await send(grant,generation);
    await assert.rejects(send(grant,{...generation,generation_id:"gen_changed"}),/receipt_journal_failed/);
    await assert.rejects(replayReceiptJournal("http://127.0.0.1:8282",directory,"run","attempt"),/origin_mismatch/);
    await chmod(directory,0o755);
    await assert.rejects(send(grant,generation),/receipt_journal_failed/);
    assert.equal(calls,1);
  } finally {await rm(directory,{recursive:true,force:true});}
});

function retained() {
  return [{type:"model.started",data:{runId:"model",modelId:MODEL_ID,attempt:0}},
    {type:"model.settled",data:{runId:"model",outcome:"completed",generationId:"gen_offline",finishReason:"tool-calls"}},
    {type:"usage.recorded",data:{kind:"model",owner:{runId:"model"},usage:{inputTokens:3,outputTokens:2,
      cacheReadTokens:0,cacheWriteTokens:0,costUsd:0.000017}}},
    {type:"session.ended",data:{outcome:"completed"}}] as SessionStreamEvent[];
}
test("retained-event recovery publishes only usage and terminal facts, never dispatch or settlement",async()=>{
  const sent:ReceiptEvent[]=[];
  const result=await recoverRetainedReceipts(grant,"session",retained(),async(_grant,event)=>{sent.push(event);return {duplicate:false};});
  assert.deepEqual(sent.map(event=>event.kind),["usage","session_terminal"]);
  assert.equal(sent[0]?.kind==="usage"&&sent[0].usage.actual_cost_microdollars,17);
  assert.deepEqual(result,{recorded:2,duplicates:0,settles_cost:false,provider_calls:0});
  const partial=await recoverRetainedReceipts(grant,"session",retained().slice(0,1),async()=>{throw new Error("must not send");});
  assert.equal(partial.recorded,0);
});
test("retained recovery rejects retries, orphaned or duplicate usage and missing cost before sending",async()=>{
  for(const change of [
    (events:SessionStreamEvent[])=>events.push({type:"model.retried",data:{}} as SessionStreamEvent),
    (events:SessionStreamEvent[])=>events.shift(),
    (events:SessionStreamEvent[])=>events.push(events[2]!),
    (events:SessionStreamEvent[])=>{const event=events[2]!;if(event.type==="usage.recorded")events[2]={...event,
      data:{...event.data,usage:{...event.data.usage,costUsd:undefined}}};},
  ]){
    const events=retained();change(events);let calls=0;
    await assert.rejects(recoverRetainedReceipts(grant,"session",events,async()=>{calls++;return {duplicate:false};}));
    assert.equal(calls,0);
  }
});
