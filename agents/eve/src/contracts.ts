import { z } from "zod";

export const MODEL_ID = "openai/gpt-6-luna";
export const MAX_REQUEST_BYTES = 128 * 1024;
export const MAX_FILE_BYTES = 64 * 1024;
export const MAX_OUTPUT_TOKENS = 16_384;
export const MAX_PROMPT_BYTES = 220_000;
export const MAX_MODEL_CALLS = 3;
export const MIN_RESERVATION = 1_000_000;
export const TIMEOUT_MS = 120_000;
export const CATALOG_SHA256 = "530d1d56cd0a5bf0a56393f547f7609534f11b7905713a4d4736aa598a4e72ff";

const hash = z.string().regex(/^[0-9a-f]{64}$/);
const file = z.string().min(1).max(MAX_FILE_BYTES);
export const GeneratedSchema = z.object({
  files: z.object({ "index.html": file, "app.js": file, "styles.css": file }).strict(),
}).strict();
export type Generated = z.infer<typeof GeneratedSchema>;

const ClaimSchema = z.object({
  run_id: z.string().min(1).max(128), task_id: z.string().min(1).max(128),
  task_key: z.string().min(1).max(128), epoch: z.number().int().nonnegative(),
  revision: z.number().int().nonnegative(), input_hash: hash,
  objective: z.string().min(1).max(8_000),
  requirements: z.array(z.string().min(1).max(2_000)).max(40),
  profile: z.literal("static-web"), suite_hash: hash, policy_hash: hash,
  reservation: z.number().int().min(MIN_RESERVATION).max(100_000_000),
});
const ProfileSchema = z.object({
  id: z.literal("static-web"), status: z.literal("active"),
  required_files: z.array(z.enum(["index.html", "app.js", "styles.css"])).length(3),
  acceptance_criteria: z.array(z.string().max(2_000)).min(1).max(40),
  required_checks: z.array(z.string().max(200)).min(1).max(40),
  selector_contract: z.record(z.string(), z.union([z.string().max(2_000), z.array(z.string().max(200)).max(30)])),
  suite_hash: hash, policy_hash: hash,
});
export const RequestSchema = z.object({
  claim: ClaimSchema, profile: ProfileSchema,
  dependencies: z.array(z.object({candidate_hash: hash, files: GeneratedSchema.shape.files}).strict()).max(8).default([]),
}).strict().superRefine((value, ctx) => {
  if (value.claim.suite_hash !== value.profile.suite_hash || value.claim.policy_hash !== value.profile.policy_hash) {
    ctx.addIssue({code: "custom", message: "profile hashes do not match claimed task"});
  }
  if (new Set(value.profile.required_files).size !== 3) {
    ctx.addIssue({code: "custom", message: "required files must be distinct"});
  }
});
export type TaskRequest = z.infer<typeof RequestSchema>;

export class AdapterError extends Error {
  constructor(public readonly code: string, public readonly costKnown = false,
    public readonly actualCostMicrodollars?: number) { super(code); }
}

export function parseRequest(text: string): TaskRequest {
  if (Buffer.byteLength(text) > MAX_REQUEST_BYTES) throw new AdapterError("request_too_large");
  try { return RequestSchema.parse(JSON.parse(text)); }
  catch { throw new AdapterError("invalid_task_contract"); }
}

export function validateGenerated(value: unknown): Generated {
  const parsed = GeneratedSchema.safeParse(value);
  if (!parsed.success || Object.values(parsed.data.files).some(content => Buffer.byteLength(content) > MAX_FILE_BYTES)) {
    throw new AdapterError("invalid_generated_files");
  }
  return parsed.data;
}

export function assertGatewayAuth(env: NodeJS.ProcessEnv = process.env): void {
  if (!env.AI_GATEWAY_API_KEY?.trim() && !env.VERCEL_OIDC_TOKEN?.trim()) {
    throw new AdapterError("gateway_credentials_missing");
  }
}

export function assertLiveAuthorization(env: NodeJS.ProcessEnv = process.env): void {
  assertGatewayAuth(env);
  const budget = Number(env.GRAPHOS_GATEWAY_BUDGET_USD);
  if (env.GRAPHOS_LIVE_ENABLED !== "1" || !Number.isFinite(budget) || budget <= 0 || budget > 5) {
    throw new AdapterError("live_gateway_budget_not_confirmed");
  }
}

export function brokerSettings(env: NodeJS.ProcessEnv = process.env) {
  const token = env.GRAPHOS_EVE_TOKEN;
  if (!token || Buffer.byteLength(token) < 32) throw new AdapterError("eve_broker_token_missing");
  let url: URL;
  try { url = new URL(env.EVE_SERVER_URL ?? "http://127.0.0.1:3001"); }
  catch { throw new AdapterError("invalid_eve_server_url"); }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" ||
      (url.protocol !== "https:" && !(url.protocol === "http:" && loopback))) {
    throw new AdapterError("invalid_eve_server_url");
  }
  return {baseUrl: url.origin, token};
}
