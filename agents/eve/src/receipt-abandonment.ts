import {constants} from "node:fs";
import {open,opendir,lstat} from "node:fs/promises";
import {createHash} from "node:crypto";
import {join} from "node:path";
import {isDeepStrictEqual} from "node:util";
import {z} from "zod";
import {runs} from "eve/events";
import type {HookContext,HookEvent} from "eve/hooks";
import {AdapterError,MODEL_ID} from "./contracts.js";
import {receiptJournalDirectory} from "./receipt-journal.js";
import {ReceiptEventSchema,ReceiptGrantSchema,receiptApiOrigin,receiptFromAttributes,
  receiptTaskFromAttributes,type ReceiptEvent,type ReceiptGrant} from "./receipts.js";

const recordSchema=z.object({version:z.literal(1),origin:z.string().max(2048),
  grant:ReceiptGrantSchema,event:ReceiptEventSchema}).strict();

// Observation only: never create/repair files, replay callbacks, or confer a lease.
async function retainedFacts(directory:string,origin:string,grant:ReceiptGrant) {
  const directoryHandle=await open(directory,constants.O_RDONLY|constants.O_DIRECTORY|constants.O_NOFOLLOW);
  try {
    const root=await directoryHandle.stat();
    const privateOwner=(info:typeof root)=>(info.mode&0o077)===0&&(!process.getuid||info.uid===process.getuid());
    if(!root.isDirectory()||!privateOwner(root))throw new Error("directory");
    const facts:ReceiptEvent[]=[];
    let scanned=0;
    for await(const entry of await opendir(directory)) {
      if(++scanned>4096)throw new Error("scan limit");
      if(!entry.name.endsWith(".json"))continue; // Writer's temporary files are not committed facts.
      if(!/^[a-f0-9]{64}\.json$/.test(entry.name))throw new Error("filename");
      const file=await open(join(directory,entry.name),constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
      try {
        const info=await file.stat();
        if(!info.isFile()||!privateOwner(info)||info.size>8192)throw new Error("file");
        const bytes=Buffer.alloc(8193),read=await file.read(bytes,0,bytes.length,0);
        if(read.bytesRead!==info.size||read.bytesRead>8192)throw new Error("size");
        const record=recordSchema.parse(JSON.parse(bytes.subarray(0,read.bytesRead).toString("utf8")));
        const key=createHash("sha256").update(JSON.stringify([
          record.grant.run_id,record.grant.attempt_id,record.event.event_id])).digest("hex");
        if(entry.name!==key+".json")throw new Error("identity key");
        if(record.grant.run_id!==grant.run_id||record.grant.attempt_id!==grant.attempt_id)continue;
        if(record.origin!==origin||!isDeepStrictEqual(record.grant,grant))throw new Error("grant");
        if(facts.length>=16)throw new Error("attempt limit");
        facts.push(record.event);
      } finally {await file.close();}
    }
    const current=await lstat(directory);
    if(current.isSymbolicLink()||current.dev!==root.dev||current.ino!==root.ino||!privateOwner(current))
      throw new Error("directory changed");
    return facts;
  } finally {await directoryHandle.close();}
}

/** Validate a historical abandonment without restoring dispatch or usage state.
 * This deliberately requires early generation capture; earlier crash boundaries
 * remain fail-closed. An outbox record does not prove a controller ACK or cost.
 */
export async function assertAbandonedReceiptObservation(event:HookEvent<"model.settled">,
  ctx:HookContext<"model.settled">,directory=receiptJournalDirectory(),origin=receiptApiOrigin()):Promise<void> {
  try {
    const grant=receiptFromAttributes(ctx.session.auth.initiator?.attributes);
    const task=receiptTaskFromAttributes(ctx.session.auth.initiator?.attributes);
    const matching=runs(ctx.view).filter(run=>run.runId===event.data.runId);
    const observed=matching[0],ended=Date.parse(observed?.endedAt??"");
    if(event.data.outcome!=="abandoned"||!ctx.turn||matching.length!==1||
        event.scope?.runId!==event.data.runId||event.scope?.turnId!==ctx.turn.id||
        event.scope?.changeId!==undefined||event.scope?.taskId!==undefined||
        observed?.turnId!==ctx.turn.id||observed.modelId!==MODEL_ID||observed.status!=="settled"||
        observed.outcome!=="abandoned"||observed.usage!==undefined||!Number.isFinite(ended)||ended!==ctx.now.getTime())
      throw new Error("observation");
    const facts=await retainedFacts(directory,receiptApiOrigin({GRAPHOS_RECEIPT_API_URL:origin}),grant);
    const identities=new Set<string>();
    for(const fact of facts) {
      const identity="model_run_id"in fact?`${fact.kind}:${fact.model_run_id}`:fact.kind;
      if(fact.session_id!==ctx.session.id||fact.event_id!==identity||identities.has(identity))
        throw new Error("fact identity");
      identities.add(identity);
    }
    const session=facts.find(fact=>fact.kind==="session");
    const model=facts.find(fact=>fact.kind==="model_started"&&fact.model_run_id===event.data.runId);
    const generation=facts.find(fact=>fact.kind==="generation"&&fact.model_run_id===event.data.runId);
    if(session?.kind!=="session"||model?.kind!=="model_started"||generation?.kind!=="generation"||
        !isDeepStrictEqual({task_id:session.task_id,epoch:session.epoch,revision:session.revision,input_hash:session.input_hash},task)||
        facts.some(fact=>fact.kind==="usage"&&fact.model_run_id===event.data.runId)||
        facts.some(fact=>fact.kind==="generation"&&fact.model_run_id!==event.data.runId&&fact.generation_id===generation.generation_id)||
        (event.data.generationId!==undefined&&event.data.generationId!==generation.generation_id))
      throw new Error("captured binding");
    // Strict schemas bind the retained intent to the fixed model and attempt 0.
    // This is not proof of the runtime's latest attempt: the public projection
    // omits that field. No current authority or usage follows from this check.
  } catch {throw new AdapterError("receipt_abandonment_evidence_invalid");}
}
