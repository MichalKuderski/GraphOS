#!/usr/bin/env node
import { AdapterError, brokerSettings, MAX_REQUEST_BYTES, parseRequest } from "./contracts.js";
import { generate } from "./broker.js";
import { eveTransport } from "./transport.js";

try {
  const settings = brokerSettings();
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const part of process.stdin) {
    const chunk = Buffer.isBuffer(part) ? part : Buffer.from(part);
    total += chunk.length;
    if (total > MAX_REQUEST_BYTES) throw new AdapterError("request_too_large");
    chunks.push(chunk);
  }
  const request = parseRequest(Buffer.concat(chunks).toString("utf8"));
  const result = await generate(request, eveTransport(settings.baseUrl, settings.token));
  const encoded = JSON.stringify(result);
  if (Buffer.byteLength(encoded) > 256 * 1024) throw new AdapterError("response_too_large", true, result.usage.actual_cost_microdollars);
  process.stdout.write(encoded + "\n");
} catch (error) {
  const known = error instanceof AdapterError ? error : new AdapterError("unexpected_adapter_error");
  process.stderr.write(JSON.stringify({error: known.code, cost_known: known.costKnown,
    actual_cost_microdollars: known.actualCostMicrodollars,
    accounting: known.costKnown ? "provider_reported" : "consume_reservation_and_reconcile"}) + "\n");
  process.exitCode = 1;
}
