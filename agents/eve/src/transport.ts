import { Client, type ClientSession, type SessionStreamEvent } from "eve/client";
import {setTimeout as delay} from "node:timers/promises";
import { GeneratedSchema, type TaskRequest } from "./contracts.js";
import {receiptHeaders,type ReceiptGrant} from "./receipts.js";

export interface ModelDelivery {status: string; data?: unknown; sessionId: string; deliveryId: string}
export interface AgentSession {
  id: string;
  result(signal: AbortSignal): Promise<ModelDelivery>;
  events(signal: AbortSignal): Promise<readonly SessionStreamEvent[]>;
  cancel(signal: AbortSignal): Promise<void>;
  end(signal: AbortSignal): Promise<void>;
}
export interface AgentTransport { create(request: TaskRequest, signal: AbortSignal): Promise<AgentSession> }

export async function waitForRetirement(
  session: {snapshot(options: {signal: AbortSignal}): Promise<{events: readonly SessionStreamEvent[]}>},
  deliveryId: string, signal: AbortSignal,
): Promise<void> {
  // eve 0.91 end receipts use a non-following stream. An immediate result read
  // can precede settlement. Require retained evidence for this exact delivery.
  while (!signal.aborted) {
    const {events} = await session.snapshot({signal});
    const settled = events.find(event => event.type === "delivery.settled" && event.data.deliveryId === deliveryId);
    const ended = events.find(event => event.type === "session.ended" &&
      event.data.cause && "deliveryId" in event.data.cause && event.data.cause.deliveryId === deliveryId);
    if (settled?.type === "delivery.settled" && settled.data.outcome !== "applied") {
      throw new Error("retirement_delivery_not_applied");
    }
    if (settled && ended?.type === "session.ended") {
      if (ended.data.outcome !== "completed") throw new Error("retirement_not_completed");
      return;
    }
    await delay(25, undefined, {signal});
  }
  throw signal.reason;
}

/** The production implementation uses eve's documented public HTTP client. */
export function eveTransport(baseUrl: string, token: string,receipt?:ReceiptGrant): AgentTransport {
  const client = new Client({baseUrl, auth: {bearer: token}, redirect: "error"});
  return {
    async create(request, signal) {
      const {session, delivery} = await client.sessions.create({
        // eve ends each HTTP stream lease after 60 seconds while the same turn
        // can still be running. Reconnect only its read-only stream GET from the
        // saved cursor; never create/send another paid turn. The caller's fixed
        // AbortSignal remains the deadline across every connection.
        message: JSON.stringify(request), outputSchema: GeneratedSchema, signal,
        ...(receipt?{headers:receiptHeaders(receipt)}:{}),
        reconnect: {maxAttempts: 3, baseDelayMs: 25, maxDelayMs: 250},
      });
      const settleControl = async (kind: "cancel" | "end", controlSignal: AbortSignal) => {
        const command = await (session as ClientSession)[kind]({signal: controlSignal});
        if (kind === "end") {
          await waitForRetirement(session, command.deliveryId, controlSignal);
          return;
        }
        const result = await command.result({signal: controlSignal});
        if (result.status === "failed" || result.status === "awaiting-input") throw new Error("control_not_settled");
      };
      return {
        id: session.id,
        result: readSignal => delivery.result({signal: readSignal}),
        events: async readSignal => (await session.snapshot({signal: readSignal})).events,
        cancel: controlSignal => settleControl("cancel", controlSignal),
        end: controlSignal => settleControl("end", controlSignal),
      };
    },
  };
}
