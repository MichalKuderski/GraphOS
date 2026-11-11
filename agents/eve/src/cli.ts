#!/usr/bin/env node
import { AdapterError, adapterErrorPayload, brokerSettings, MAX_REQUEST_BYTES } from "./contracts.js";
import { generate } from "./broker.js";
import { eveTransport } from "./transport.js";
import {parseEnvelope} from "./receipts.js";

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
  const {request,receipt} = parseEnvelope(Buffer.concat(chunks).toString("utf8"));
  const result = await generate(request, eveTransport(settings.baseUrl, settings.token,receipt));
  const encoded = JSON.stringify(result);
  if (Buffer.byteLength(encoded) > 256 * 1024) throw new AdapterError("response_too_large", true, result.usage.actual_cost_microdollars, result.usage);
  process.stdout.write(encoded + "\n");
} catch (error) {
  process.stderr.write(JSON.stringify(adapterErrorPayload(error)) + "\n");
  process.exitCode = 1;
}
