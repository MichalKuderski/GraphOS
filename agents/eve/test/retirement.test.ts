import test from "node:test";
import assert from "node:assert/strict";
import type {SessionStreamEvent} from "eve/client";
import {waitForRetirement} from "../src/transport.js";

const applied = {type:"delivery.settled",data:{deliveryId:"end-1",outcome:"applied"}} as SessionStreamEvent;
const ended = {type:"session.ended",data:{cause:{deliveryId:"end-1"},outcome:"completed"}} as SessionStreamEvent;

test("retirement waits for both exact receipt and terminal evidence", async () => {
  const states = [[],[applied],[applied,ended]];
  let reads = 0;
  await waitForRetirement({async snapshot(){return {events:states[reads++]!};}}, "end-1", AbortSignal.timeout(1000));
  assert.equal(reads,3);
});

test("unrelated retirement cannot confirm this command; deadlines remain bounded", async () => {
  await assert.rejects(waitForRetirement({async snapshot(){return {events:[applied,ended]};}},
    "different-end", AbortSignal.timeout(60)));
});

test("unavailable history or refused end is never treated as retirement success", async () => {
  await assert.rejects(waitForRetirement({async snapshot(){throw new Error("HTTP410");}},
    "end-1", AbortSignal.timeout(1000)), /HTTP410/);
  const refused = {type:"delivery.settled",data:{deliveryId:"end-1",outcome:"refused"}} as SessionStreamEvent;
  await assert.rejects(waitForRetirement({async snapshot(){return {events:[refused,ended]};}},
    "end-1", AbortSignal.timeout(1000)), /retirement_delivery_not_applied/);
});
