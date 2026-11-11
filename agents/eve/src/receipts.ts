import {z} from "zod";
import type {LanguageModelMiddleware} from "ai";
import {request as httpRequest} from "node:http";
import {request as httpsRequest} from "node:https";
import {AdapterError, MAX_REQUEST_BYTES, MODEL_ID, parseRequest} from "./contracts.js";

const id=z.string().regex(/^[A-Za-z0-9_-]{1,128}$/);
const generationId=z.string().regex(/^gen_[A-Za-z0-9_-]{1,508}$/);
const count=z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
export const ReceiptTaskSchema=z.object({task_id:id,epoch:count,revision:count,
  input_hash:z.string().regex(/^[0-9a-f]{64}$/)}).strict();
export type ReceiptTask=z.infer<typeof ReceiptTaskSchema>;
export const ReceiptGrantSchema=z.object({run_id:id,attempt_id:id,
  capture_token:z.string().regex(/^[A-Za-z0-9_-]{32,512}$/)}).strict();
export type ReceiptGrant=z.infer<typeof ReceiptGrantSchema>;
const modelFields={model_run_id:id,model_id:z.literal(MODEL_ID),model_attempt:z.literal(0)};
const base={event_id:z.string().regex(/^[A-Za-z0-9_:-]{1,200}$/),session_id:id};
export const ReceiptEventSchema=z.discriminatedUnion("kind",[
  z.object({...base,...ReceiptTaskSchema.shape,kind:z.literal("session")}).strict(),
  z.object({...base,...modelFields,kind:z.literal("model_started")}).strict(),
  z.object({...base,...modelFields,kind:z.literal("generation"),generation_id:generationId}).strict(),
  z.object({...base,...modelFields,kind:z.literal("usage"),usage:z.object({
    input_tokens:count,output_tokens:count,cache_read_tokens:count,cache_write_tokens:count,
    actual_cost_microdollars:count,generation_id:generationId.nullable(),
    finish_reason:z.string().regex(/^[A-Za-z0-9_-]{1,128}$/).nullable(),
  }).strict()}).strict(),
  z.object({...base,kind:z.literal("session_terminal"),
    outcome:z.enum(["completed","failed","cancelled"])}).strict(),
]);
export type ReceiptEvent=z.infer<typeof ReceiptEventSchema>;
export interface ReceiptInvocation {
  grant:ReceiptGrant;task:ReceiptTask;session_id:string;model_run_id:string;
  model_id:typeof MODEL_ID;model_attempt:0;
}
export type ReceiptSender=(grant:ReceiptGrant,event:ReceiptEvent)=>Promise<{duplicate:boolean}>;

export function parseEnvelope(text:string) {
  if(Buffer.byteLength(text)>MAX_REQUEST_BYTES) throw new AdapterError("request_too_large");
  try {
    const envelope=z.object({request:z.unknown(),receipt:ReceiptGrantSchema}).strict().parse(JSON.parse(text));
    const request=parseRequest(JSON.stringify(envelope.request));
    if(envelope.receipt.run_id!==request.claim.run_id||envelope.receipt.attempt_id!==request.claim.attempt_id)
      throw new Error("binding");
    return {request,receipt:envelope.receipt};
  } catch {throw new AdapterError("invalid_receipt_envelope");}
}

export function receiptHeaders(grant:ReceiptGrant):Record<string,string> {
  const parsed=ReceiptGrantSchema.safeParse(grant);
  if(!parsed.success) throw new AdapterError("invalid_receipt_grant");
  return {"x-graphos-receipt-run-id":parsed.data.run_id,
    "x-graphos-receipt-attempt-id":parsed.data.attempt_id,
    "x-graphos-receipt-token":parsed.data.capture_token};
}

export function receiptFromHeaders(headers:Headers):ReceiptGrant {
  const parsed=ReceiptGrantSchema.safeParse({run_id:headers.get("x-graphos-receipt-run-id"),
    attempt_id:headers.get("x-graphos-receipt-attempt-id"),capture_token:headers.get("x-graphos-receipt-token")});
  if(!parsed.success) throw new AdapterError("invalid_receipt_grant");
  return parsed.data;
}

export function receiptFromAttributes(attributes:Readonly<Record<string,string|readonly string[]>>|undefined):ReceiptGrant {
  const parsed=ReceiptGrantSchema.safeParse({run_id:attributes?.["graphos.receipt.run_id"],
    attempt_id:attributes?.["graphos.receipt.attempt_id"],capture_token:attributes?.["graphos.receipt.capture_token"]});
  if(!parsed.success) throw new AdapterError("invalid_receipt_grant");
  return parsed.data;
}

export function receiptTaskFromClaim(claim:unknown):ReceiptTask {
  const parsed=ReceiptTaskSchema.strip().safeParse(claim);
  if(!parsed.success)throw new AdapterError("invalid_receipt_task_binding");
  return parsed.data;
}

export function receiptTaskFromAttributes(attributes:Readonly<Record<string,string|readonly string[]>>|undefined):ReceiptTask {
  const epoch=attributes?.["graphos.receipt.epoch"],revision=attributes?.["graphos.receipt.revision"];
  if(typeof epoch!=="string"||typeof revision!=="string"||!/^\d+$/.test(epoch)||!/^\d+$/.test(revision))
    throw new AdapterError("invalid_receipt_task_binding");
  return receiptTaskFromClaim({task_id:attributes?.["graphos.receipt.task_id"],epoch:Number(epoch),revision:Number(revision),
    input_hash:attributes?.["graphos.receipt.input_hash"]});
}

export function receiptAttributes(grant:ReceiptGrant,task:ReceiptTask) {
  return {"graphos.receipt.run_id":grant.run_id,"graphos.receipt.attempt_id":grant.attempt_id,
    "graphos.receipt.capture_token":grant.capture_token,"graphos.receipt.task_id":task.task_id,
    "graphos.receipt.epoch":String(task.epoch),"graphos.receipt.revision":String(task.revision),
    "graphos.receipt.input_hash":task.input_hash};
}

export function receiptApiOrigin(env:NodeJS.ProcessEnv=process.env) {
  try {
    const url=new URL(env.GRAPHOS_RECEIPT_API_URL??"");
    const local=["localhost","127.0.0.1","[::1]"].includes(url.hostname);
    if(url.username||url.password||url.search||url.hash||url.pathname!=="/"||
       (url.protocol!=="https:"&&!(url.protocol==="http:"&&local))) throw new Error("origin");
    return url.origin;
  } catch {throw new AdapterError("invalid_receipt_api_url");}
}

// Dedicated control-plane transport: Node's direct request APIs do not consult
// HTTP_PROXY/HTTPS_PROXY or a global fetch dispatcher. Never follow redirects.
export const directReceiptFetch:typeof fetch=async(input,init)=>{
  const url=new URL(String(input));
  return await new Promise<Response>((resolve,reject)=>{
    const request=(url.protocol==="https:"?httpsRequest:httpRequest)(url,{
      method:"POST",headers:Object.fromEntries(new Headers(init?.headers)),
      signal:init?.signal??undefined,agent:false,
    },response=>{
      let bytes=0;const chunks:Buffer[]=[];
      response.on("data",(chunk:Buffer)=>{
        bytes+=chunk.length;
        if(bytes>4096){response.destroy(new Error("receipt response limit"));return;}
        chunks.push(chunk);
      });
      response.on("error",reject);
      response.on("end",()=>resolve(new Response(Buffer.concat(chunks),{status:response.statusCode??502})));
    });
    request.on("error",reject);
    request.end(String(init?.body??""));
  });
};

export function receiptSender(origin:string,fetcher:typeof fetch=directReceiptFetch,timeoutMs=5_000):ReceiptSender {
  // Callers supply only an operator-configured origin. Revalidate even in tests;
  // neither a task nor a model can choose the credential's destination.
  const safeOrigin=receiptApiOrigin({GRAPHOS_RECEIPT_API_URL:origin});
  return async(grant,event)=>{
    try {
      const safeGrant=ReceiptGrantSchema.parse(grant),safeEvent=ReceiptEventSchema.parse(event);
      const response=await fetcher(`${safeOrigin}/v1/runs/${safeGrant.run_id}/attempts/${safeGrant.attempt_id}/receipts`,{
        method:"POST",headers:{authorization:`Bearer ${safeGrant.capture_token}`,"content-type":"application/json"},
        body:JSON.stringify(safeEvent),redirect:"error",signal:AbortSignal.timeout(timeoutMs),
      });
      if(!response.ok||!response.body) throw new Error("receipt unavailable");
      const reader=response.body.getReader();let bytes=0;const chunks:Uint8Array[]=[];
      try {for(;;){const next=await reader.read();if(next.done)break;bytes+=next.value.byteLength;
        if(bytes>4096)throw new Error("receipt response limit");chunks.push(next.value);}}
      finally {await reader.cancel().catch(()=>undefined);}
      const ack=z.object({recorded:z.literal(true),duplicate:z.boolean(),attempt_id:id,
        event_id:z.string(),kind:z.string()}).parse(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      if(ack.attempt_id!==safeGrant.attempt_id||ack.event_id!==safeEvent.event_id||ack.kind!==safeEvent.kind)
        throw new Error("receipt acknowledgement binding");
      return {duplicate:ack.duplicate};
    } catch {throw new AdapterError("receipt_persistence_failed");}
  };
}

export function receiptModelFields(binding:ReceiptInvocation) {
  return {session_id:binding.session_id,model_run_id:binding.model_run_id,
    model_id:binding.model_id,model_attempt:binding.model_attempt};
}

/** Capture only trusted provider metadata, before its first chunk reaches Eve. */
export function earlyReceiptMiddleware(resolve:()=>ReceiptInvocation,send:ReceiptSender):LanguageModelMiddleware {
  async function start() {
    const binding=resolve(),fields=receiptModelFields(binding);
    await send(binding.grant,{kind:"session",event_id:"session",session_id:binding.session_id,...binding.task});
    const ack=await send(binding.grant,{kind:"model_started",event_id:`model_started:${binding.model_run_id}`,...fields});
    // An existing intent can already have incurred cost, including lost ACKs.
    // Never turn idempotent bookkeeping into a repeated model invocation.
    if(ack.duplicate) throw new AdapterError("model_invocation_already_registered");
    return binding;
  }
  function capture(binding:ReceiptInvocation) {
    let observed:string|undefined;
    return async(metadata:unknown)=>{
      if(!metadata||typeof metadata!=="object"||!("gateway"in metadata)) return;
      const gateway=metadata.gateway;
      if(!gateway||typeof gateway!=="object"||!("generationId"in gateway)||gateway.generationId===undefined) return;
      const parsed=generationId.safeParse(gateway.generationId);
      if(!parsed.success) throw new AdapterError("invalid_gateway_generation_id");
      if(observed===parsed.data)return;
      if(observed!==undefined)throw new AdapterError("conflicting_gateway_generation_id");
      await send(binding.grant,{kind:"generation",event_id:`generation:${binding.model_run_id}`,
        ...receiptModelFields(binding),generation_id:parsed.data});
      observed=parsed.data;
    };
  }
  return {specificationVersion:"v4",
    wrapStream:async({doStream})=>{
      const binding=await start(),persist=capture(binding),result=await doStream();
      return {...result,stream:result.stream.pipeThrough(new TransformStream({
        async transform(chunk,controller) {
          if("providerMetadata"in chunk)await persist(chunk.providerMetadata);
          controller.enqueue(chunk);
        },
      }))};
    },
    wrapGenerate:async({doGenerate})=>{
      const binding=await start(),result=await doGenerate();
      await capture(binding)(result.providerMetadata);return result;
    },
  };
}
