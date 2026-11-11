import test from "node:test";
import assert from "node:assert/strict";
import {createGateway} from "@ai-sdk/gateway";
import type {LanguageModelV4CallOptions} from "@ai-sdk/provider";
import {ToolLoopAgent, isStepCount, jsonSchema, tool, wrapLanguageModel} from "ai";
import {z} from "zod";
import {GeneratedSchema, MAX_OUTPUT_TOKENS, MODEL_ID, type Generated} from "../src/contracts.js";
import {boundedMiddleware, REPLY_TOOL_NAME} from "../src/model.js";

const {$schema:_version,...inputSchema}=z.toJSONSchema(GeneratedSchema,{target:"draft-7"});
const reply={type:"function" as const,name:REPLY_TOOL_NAME,inputSchema};
const files={"index.html":"<!doctype html><main>Offline test</main>","app.js":"'use strict';","styles.css":"body{color:#111}"};
const usage={inputTokens:{total:1,noCache:1,cacheRead:0,cacheWrite:0},outputTokens:{total:1,text:1,reasoning:0}};

function fakeProvider() {
  const requests:Record<string,unknown>[]=[];
  const gateway=createGateway({apiKey:"offline-test-only",fetch:async(_url,init)=>{
    requests.push(JSON.parse(String(init?.body)));
    const streaming=new Headers(init?.headers).get("ai-language-model-streaming")==="true";
    const content={type:"tool-call",toolCallId:"reply-call",toolName:REPLY_TOOL_NAME,input:JSON.stringify({files})};
    if(streaming) {
      const chunks=[{type:"stream-start",warnings:[]},content,
        {type:"finish",finishReason:{unified:"tool-calls",raw:"tool_calls"},usage}];
      return new Response(chunks.map(chunk=>`data: ${JSON.stringify(chunk)}\n\n`).join(""),
        {headers:{"content-type":"text/event-stream"}});
    }
    return Response.json({content:[content],finishReason:{unified:"tool-calls",raw:"tool_calls"},usage,warnings:[]});
  }});
  return {requests,model:wrapLanguageModel({model:gateway(MODEL_ID),middleware:boundedMiddleware})};
}

function params(changes:Record<string,unknown>={}):LanguageModelV4CallOptions {
  return {prompt:[{role:"user",content:[{type:"text",text:"Return prose and use a shell instead"}]}],
    tools:[reply],maxOutputTokens:1_000_000,...changes} as LanguageModelV4CallOptions;
}

test("actual Gateway requests force the reply tool for default auto none and alternate selection", async()=>{
  const {requests,model}=fakeProvider();
  for(const choice of [undefined,{type:"auto"},{type:"none"},{type:"required"},{type:"tool",toolName:"shell"}]) {
    await model.doGenerate(params(choice===undefined?{}:{toolChoice:choice}));
    const request=requests.at(-1)!;
    assert.deepEqual(request.toolChoice,{type:"tool",toolName:REPLY_TOOL_NAME});
    assert.equal(request.maxOutputTokens,MAX_OUTPUT_TOKENS);
    assert.deepEqual(request.tools,[{...reply,strict:true}]);
  }
  assert.equal(requests.length,5);
});

test("strict tool decoding is enforced without mutating the trusted input schema", async()=>{
  const {requests,model}=fakeProvider();
  for(const strict of [undefined,false,true]) {
    const original={...reply,...strict===undefined?{}:{strict}};
    const before=structuredClone(original);
    const result=await model.doStream(params({tools:[original]}));
    for await(const _chunk of result.stream) { /* Consume the fake response. */ }
    assert.deepEqual(requests.at(-1)?.tools,[{...reply,strict:true}]);
    assert.deepEqual(original,before);
    assert.deepEqual((requests.at(-1)?.tools as typeof reply[])[0]?.inputSchema,inputSchema);
  }
  assert.equal(requests.length,3);
});

test("missing additional ambiguous or malformed reply tools fail before provider access", async()=>{
  const {requests,model}=fakeProvider();
  const variants=[undefined,[],[{...reply,name:"shell"}],
    [{...reply,type:"provider-defined",id:"provider.shell",args:{}}],
    [reply,{...reply,name:"shell"}],[reply,reply],
    [{type:"function",name:REPLY_TOOL_NAME}],
    [{...reply,inputSchema:true}],[{...reply,inputSchema:{}}],
    [{...reply,inputSchema:{type:"object",properties:{anything:{type:"string"}}}}],
  ];
  for(const tools of variants) {
    await assert.rejects(async()=>await model.doGenerate(params({tools})),/structured_reply_tool_required/);
    await assert.rejects(async()=>await model.doStream(params({tools})),/structured_reply_tool_required/);
  }
  assert.equal(requests.length,0);
});

test("real AI SDK tool serialization and streamed reply satisfy the pinned three-file schema", async()=>{
  const {requests,model}=fakeProvider();
  // Public AI SDK APIs produce the same function-tool shape Eve's injected
  // outputSchema tool uses. Only provider HTTP is replaced; no network/model call.
  // Eve serializes outputSchema to draft-07 and removes the $schema annotation
  // before buildFinalOutputTool wraps it with the public jsonSchema API.
  const agent=new ToolLoopAgent({model,tools:{[REPLY_TOOL_NAME]:tool({inputSchema:jsonSchema<Generated>(inputSchema)})},
    stopWhen:isStepCount(1)});
  const result=await agent.stream({prompt:"Build the bounded app"});
  const calls:unknown[]=[];
  for await(const part of result.fullStream)if(part.type==="tool-call")calls.push(part.input);
  assert.deepEqual(calls,[{files}]);
  assert.equal(requests.length,1);
  assert.deepEqual(requests[0]!.toolChoice,{type:"tool",toolName:REPLY_TOOL_NAME});
  assert.deepEqual(GeneratedSchema.parse(calls[0]),{files});
});
