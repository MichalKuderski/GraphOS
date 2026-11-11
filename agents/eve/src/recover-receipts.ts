import {readFile} from "node:fs/promises";
import {Client} from "eve/client";
import {parseArgs} from "node:util";
import {parseEnvelope,receiptApiOrigin} from "./receipts.js";
import {journaledReceiptSender,receiptJournalDirectory,replayReceiptJournal} from "./receipt-journal.js";
import {recoverRetainedReceipts} from "./receipt-recovery.js";

// Explicit recovery only. No sessions.create/send/end/cancel and no model key.
try {
  const {values}=parseArgs({options:{"envelope-file":{type:"string"},"session-id":{type:"string"},"eve-url":{type:"string"},
    "run-id":{type:"string"},"attempt-id":{type:"string"}}});
  const receipt=values["envelope-file"]?parseEnvelope(await readFile(values["envelope-file"],"utf8")).receipt:undefined;
  const runId=receipt?.run_id??values["run-id"],attemptId=receipt?.attempt_id??values["attempt-id"];
  if(!runId||!attemptId||![runId,attemptId].every(id=>/^[A-Za-z0-9_-]{1,128}$/.test(id)))throw new Error("scope required");
  if(values["session-id"]&&!receipt)throw new Error("retained recovery requires private envelope");
  const origin=receiptApiOrigin(),directory=receiptJournalDirectory();
  const journal=await replayReceiptJournal(origin,directory,runId,attemptId);
  let retained;
  if(values["session-id"]&&receipt){
    const url=new URL(values["eve-url"]??"");
    if(url.username||url.password||(url.protocol!=="https:"&&!(url.protocol==="http:"&&url.hostname==="127.0.0.1")))
      throw new Error("invalid Eve URL");
    const token=process.env.GRAPHOS_EVE_TOKEN;
    if(!token||token.length<32)throw new Error("broker token required");
    const client=new Client({baseUrl:url.origin,auth:{bearer:token},redirect:"error"});
    const session=client.sessions.attach(values["session-id"]);
    const snapshot=await session.snapshot({signal:AbortSignal.timeout(5_000)});
    retained=await recoverRetainedReceipts(receipt,session.id,snapshot.events,journaledReceiptSender(origin,directory));
  }
  process.stdout.write(JSON.stringify({journal,retained})+"\n");
  if(journal.pending)process.exitCode=1;
} catch {process.stderr.write("receipt_recovery_failed; no model invocation or settlement attempted\n");process.exitCode=1;}
