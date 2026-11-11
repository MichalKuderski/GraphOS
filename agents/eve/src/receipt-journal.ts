import {constants} from "node:fs";
import {open,mkdir,lstat,link,unlink,readdir,readFile} from "node:fs/promises";
import {createHash,randomUUID} from "node:crypto";
import {join,resolve} from "node:path";
import {AdapterError} from "./contracts.js";
import {ReceiptEventSchema,ReceiptGrantSchema,receiptApiOrigin,receiptSender,
  type ReceiptEvent,type ReceiptGrant,type ReceiptSender} from "./receipts.js";

// Requires a retained private volume. fsync protects process death on that
// volume, not loss of the host/volume itself. Records contain scoped secrets.
export function receiptJournalDirectory(env:NodeJS.ProcessEnv=process.env) {
  return resolve(env.GRAPHOS_RECEIPT_OUTBOX_DIR??".state/receipt-outbox");
}
async function privateDirectory(directory:string) {
  await mkdir(directory,{recursive:true,mode:0o700});
  const info=await lstat(directory);
  if(!info.isDirectory()||info.isSymbolicLink()||(info.mode&0o077)!==0||
     (process.getuid&&info.uid!==process.getuid()))throw new Error("unsafe journal directory");
}
async function syncDirectory(directory:string) {
  const handle=await open(directory,constants.O_RDONLY|constants.O_DIRECTORY);
  try {await handle.sync();}finally{await handle.close();}
}
async function retain(directory:string,origin:string,grant:ReceiptGrant,event:ReceiptEvent) {
  await privateDirectory(directory);
  const value=JSON.stringify({version:1,origin,grant:ReceiptGrantSchema.parse(grant),event:ReceiptEventSchema.parse(event)});
  const key=createHash("sha256").update(JSON.stringify([grant.run_id,grant.attempt_id,event.event_id])).digest("hex");
  const destination=join(directory,key+".json"),temporary=join(directory,"."+randomUUID()+".tmp");
  const handle=await open(temporary,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600);
  try {await handle.writeFile(value);await handle.sync();}finally{await handle.close();}
  try {
    try {await link(temporary,destination);}
    catch(error){
      if((error as NodeJS.ErrnoException).code!=="EEXIST")throw error;
      const existing=await open(destination,constants.O_RDONLY|constants.O_NOFOLLOW);
      try {if(await existing.readFile("utf8")!==value)throw new Error("receipt journal conflict");}
      finally{await existing.close();}
    }
    await syncDirectory(directory);
  } finally {await unlink(temporary);}
}
export function journaledReceiptSender(origin:string,directory=receiptJournalDirectory(),
  send:ReceiptSender=receiptSender(origin)):ReceiptSender {
  const safeOrigin=receiptApiOrigin({GRAPHOS_RECEIPT_API_URL:origin});
  return async(grant,event)=>{
    try {await retain(directory,safeOrigin,grant,event);}
    catch {throw new AdapterError("receipt_journal_failed");}
    // Lost ACKs retain the identical payload; recovery repeats facts only.
    return send(grant,event);
  };
}
export async function replayReceiptJournal(origin:string,directory:string,runId:string,attemptId:string,
  send:ReceiptSender=receiptSender(origin)) {
  const safeOrigin=receiptApiOrigin({GRAPHOS_RECEIPT_API_URL:origin});
  await privateDirectory(directory);
  const names=(await readdir(directory)).filter(name=>/^[a-f0-9]{64}\.json$/.test(name)).sort();
  if(names.length>4096)throw new AdapterError("receipt_journal_scan_limit");
  const pending:{grant:ReceiptGrant;event:ReceiptEvent}[]=[];
  for(const name of names){
    const path=join(directory,name),info=await lstat(path);
    if(!info.isFile()||info.isSymbolicLink()||(info.mode&0o077)!==0||info.size>8192)
      throw new AdapterError("receipt_journal_invalid");
    const item=JSON.parse(await readFile(path,"utf8"));
    const grant=ReceiptGrantSchema.parse(item.grant),event=ReceiptEventSchema.parse(item.event);
    if(grant.run_id!==runId||grant.attempt_id!==attemptId)continue;
    if(item.version!==1||item.origin!==safeOrigin)throw new AdapterError("receipt_journal_origin_mismatch");
    pending.push({grant,event});
  }
  if(pending.length>16)throw new AdapterError("receipt_journal_attempt_limit");
  let recorded=0,duplicates=0;
  // Progress-bounded sweeps resolve reordered prerequisites. Rejected stale
  // intents remain pending; recovery never bypasses the controller's fences.
  for(let progress=true;progress&&pending.length;){
    progress=false;
    for(let index=0;index<pending.length;){
      const item=pending[index]!;
      try {
        const ack=await send(item.grant,item.event);
        recorded++;duplicates+=Number(ack.duplicate);pending.splice(index,1);progress=true;
      } catch {index++;}
    }
  }
  return {recorded,duplicates,pending:pending.length,settles_cost:false,provider_calls:0};
}
