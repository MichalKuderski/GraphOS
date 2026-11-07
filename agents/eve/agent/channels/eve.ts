import { timingSafeEqual } from "node:crypto";
import { eveChannel, defaultEveAuth } from "eve/channels/eve";
import { AdapterError, assertLiveAuthorization, parseRequest } from "../../src/contracts.js";

export default eveChannel({
  auth: request => {
    const expected = process.env.GRAPHOS_EVE_TOKEN;
    const header = request.headers.get("authorization");
    const supplied = header?.startsWith("Bearer ") ? header.slice(7) : undefined;
    if (!expected || Buffer.byteLength(expected) < 32 || !supplied) return null;
    const a = Buffer.from(expected), b = Buffer.from(supplied);
    if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
    return {attributes: {}, authenticator: "graphos-eve-broker", principalId: "graphos-builder",
      principalType: "service", allowToolStubs: false, allowAgentInfo: true};
  },
  uploadPolicy: "disabled",
  cors: false,
  onMessage(ctx, message) {
    if (ctx.eve.sessionId || typeof message !== "string") throw new AdapterError("one_task_per_session_required");
    assertLiveAuthorization();
    parseRequest(message);
    return {auth: defaultEveAuth(ctx), clientContext: [], title: "GraphOS bounded static-web build"};
  },
});
