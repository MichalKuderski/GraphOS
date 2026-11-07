import { Client, type ClientSession, type SessionStreamEvent } from "eve/client";
import { GeneratedSchema, type TaskRequest } from "./contracts.js";

export interface ModelDelivery {status: string; data?: unknown; sessionId: string; deliveryId: string}
export interface AgentSession {
  id: string;
  result(signal: AbortSignal): Promise<ModelDelivery>;
  events(signal: AbortSignal): Promise<readonly SessionStreamEvent[]>;
  cancel(signal: AbortSignal): Promise<void>;
  end(signal: AbortSignal): Promise<void>;
}
export interface AgentTransport { create(request: TaskRequest, signal: AbortSignal): Promise<AgentSession> }

/** The production implementation uses eve's documented public HTTP client. */
export function eveTransport(baseUrl: string, token: string): AgentTransport {
  const client = new Client({baseUrl, auth: {bearer: token}, redirect: "error"});
  return {
    async create(request, signal) {
      const {session, delivery} = await client.sessions.create({
        message: JSON.stringify(request), outputSchema: GeneratedSchema, signal, reconnect: false,
      });
      const settleControl = async (kind: "cancel" | "end", controlSignal: AbortSignal) => {
        const command = await (session as ClientSession)[kind]({signal: controlSignal});
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
