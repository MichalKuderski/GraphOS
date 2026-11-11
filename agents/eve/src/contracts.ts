import { z } from "zod";

export const MODEL_ID = "openai/gpt-5.1-codex-mini";
export const MODEL_CONTEXT_TOKENS = 400_000;
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
const profileId = z.enum(["static-web", "local-notes", "local-inventory"]);
export const GeneratedSchema = z.object({
  files: z.object({ "index.html": file, "app.js": file, "styles.css": file }).strict(),
}).strict();
export type Generated = z.infer<typeof GeneratedSchema>;

const ClaimSchema = z.object({
  run_id: z.string().min(1).max(128), task_id: z.string().min(1).max(128),
  attempt_id: z.string().regex(/^[A-Za-z0-9_-]{1,128}$/).optional(),
  task_key: z.string().min(1).max(128), epoch: z.number().int().nonnegative(),
  revision: z.number().int().nonnegative(), input_hash: hash,
  objective: z.string().min(1).max(8_000),
  requirements: z.array(z.string().min(1).max(2_000)).max(40),
  profile: profileId, suite_hash: hash, policy_hash: hash,
  reservation: z.number().int().min(MIN_RESERVATION).max(100_000_000),
});
const ProfileSchema = z.object({
  id: profileId, status: z.literal("active"),
  required_files: z.array(z.enum(["index.html", "app.js", "styles.css"])).length(3),
  acceptance_criteria: z.array(z.string().max(2_000)).min(1).max(40),
  required_checks: z.array(z.string().max(200)).min(1).max(40),
  selector_contract: z.record(z.string(), z.union([z.string().max(2_000), z.array(z.string().max(200)).max(30)])),
  suite_hash: hash, policy_hash: hash,
});
const RepairSchema = z.object({
  candidate_hash: hash, evidence_hash: hash,
  verifier_attempt_id: z.string().min(1).max(128),
  revision: z.number().int().nonnegative(), input_hash: hash,
  suite_hash: hash, policy_hash: hash,
  checks: z.array(z.object({name: z.string().min(1).max(128),
    passed: z.boolean(), detail: z.string().max(1024)}).strict()).max(32),
  truncated: z.boolean(), files: GeneratedSchema.shape.files,
}).strict();
export const RequestSchema = z.object({
  claim: ClaimSchema, profile: ProfileSchema,
  dependencies: z.array(z.object({candidate_hash: hash, files: GeneratedSchema.shape.files}).strict()).max(8).default([]),
  repair: RepairSchema.optional(),
}).strict().superRefine((value, ctx) => {
  if (value.claim.profile !== value.profile.id) {
    ctx.addIssue({code: "custom", message: "profile id does not match claimed task"});
  }
  if (value.claim.suite_hash !== value.profile.suite_hash || value.claim.policy_hash !== value.profile.policy_hash) {
    ctx.addIssue({code: "custom", message: "profile hashes do not match claimed task"});
  }
  if (new Set(value.profile.required_files).size !== 3) {
    ctx.addIssue({code: "custom", message: "required files must be distinct"});
  }
  if (value.repair && (value.repair.revision !== value.claim.revision ||
      value.repair.input_hash !== value.claim.input_hash ||
      value.repair.suite_hash !== value.claim.suite_hash ||
      value.repair.policy_hash !== value.claim.policy_hash ||
      !value.repair.checks.some(check => !check.passed))) {
    ctx.addIssue({code: "custom", message: "repair evidence does not match claimed task"});
  }
});
export type TaskRequest = z.infer<typeof RequestSchema>;

const safeCount = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const ModelUsageSchema = z.object({
  input_tokens: safeCount, output_tokens: safeCount,
  cache_read_tokens: safeCount, cache_write_tokens: safeCount,
  actual_cost_microdollars: safeCount, model_runs: safeCount.min(1),
  cost_source: z.literal("eve_gateway_usage_events"),
  generations: z.array(z.object({
    run_id: z.string().regex(/^[A-Za-z0-9_-]{1,128}$/),
    generation_id: z.string().regex(/^gen_[A-Za-z0-9_-]{1,508}$/).nullable(),
    finish_reason: z.string().regex(/^[A-Za-z0-9_-]{1,128}$/).nullable(),
  }).strict()).max(100),
}).strict().superRefine((value, ctx) => {
  const ids=value.generations.flatMap(g=>g.generation_id === null ? [] : [g.generation_id]);
  if (value.model_runs !== value.generations.length ||
      new Set(value.generations.map(g=>g.run_id)).size !== value.model_runs ||
      new Set(ids).size !== ids.length) {
    ctx.addIssue({code:"custom",message:"invalid usage identity binding"});
  }
});
export type ModelUsage = z.infer<typeof ModelUsageSchema>;

export class AdapterError extends Error {
  constructor(public readonly code: string, public readonly costKnown = false,
    public readonly actualCostMicrodollars?: number, public readonly usage?: ModelUsage) { super(code); }
}

export function adapterErrorPayload(error: unknown) {
  const known = error instanceof AdapterError ? error : new AdapterError("unexpected_adapter_error");
  const usage = ModelUsageSchema.safeParse(known.usage);
  return {error: known.code, cost_known: known.costKnown,
    actual_cost_microdollars: known.costKnown ? known.actualCostMicrodollars : undefined,
    accounting: known.costKnown ? "provider_reported" : "consume_reservation_and_reconcile",
    ...(known.costKnown && usage.success &&
      usage.data.actual_cost_microdollars === known.actualCostMicrodollars ? {usage: usage.data} : {}),
  };
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
