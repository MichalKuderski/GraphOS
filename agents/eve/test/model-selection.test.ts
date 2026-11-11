import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import {CATALOG_SHA256, MODEL_ID, MODEL_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS} from "../src/contracts.js";

test("runtime model and context limits match the pinned catalog and selection", () => {
  const raw = readFileSync(new URL("../../model-catalog.json", import.meta.url));
  const selection = JSON.parse(readFileSync(new URL("../../model-selection.json", import.meta.url), "utf8"));
  const model = JSON.parse(raw.toString()).data.find((entry: {id: string}) => entry.id === MODEL_ID);
  assert.ok(model);
  assert.equal(createHash("sha256").update(raw).digest("hex"), CATALOG_SHA256);
  assert.equal(selection.catalog_sha256, CATALOG_SHA256);
  assert.equal(selection.model_id, MODEL_ID);
  assert.equal(model.context_window, MODEL_CONTEXT_TOKENS);
  assert.equal(selection.context_window, MODEL_CONTEXT_TOKENS);
  assert.ok(MAX_OUTPUT_TOKENS <= model.max_tokens);
  assert.ok(model.tags.includes("structured-output"));
  assert.equal(selection.access_evidence.availableToFreeTier, true);
});
