import { timingSafeEqual } from "node:crypto";
import { eveChannel, defaultEveAuth } from "eve/channels/eve";
import { AdapterError, assertLiveAuthorization, parseRequest } from "../../src/contracts.js";
import {receiptFromHeaders,receiptAttributes,receiptTaskFromClaim,receiptFromAttributes,receiptApiOrigin} from "../../src/receipts.js";
import {journaledReceiptSender} from "../../src/receipt-journal.js";

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
  events: {
    async "session.ended"(event,ctx) {
      // Eve 0.91's terminal publisher invokes channel handlers but skips hooks.
      // An idle diagnostic session has no paid task or receipt capability.
      if(!ctx.session.auth.initiator?.attributes["graphos.receipt.attempt_id"])return;
      await journaledReceiptSender(receiptApiOrigin())(receiptFromAttributes(ctx.session.auth.initiator.attributes),{
        kind:"session_terminal",event_id:"session_terminal",session_id:ctx.session.id,outcome:event.data.outcome});
    },
  },
  onMessage(ctx, message) {
    if (ctx.eve.sessionId || typeof message !== "string") throw new AdapterError("one_task_per_session_required");
    assertLiveAuthorization();
    const request=parseRequest(message),grant=receiptFromHeaders(ctx.eve.request.headers),auth=defaultEveAuth(ctx);
    if(!auth||grant.run_id!==request.claim.run_id||grant.attempt_id!==request.claim.attempt_id)
      throw new AdapterError("invalid_receipt_grant");
    return {auth:{...auth,attributes:{...auth.attributes,...receiptAttributes(grant,receiptTaskFromClaim(request.claim))}},
      clientContext: [], title: "GraphOS bounded static-web build"};
  },
});
