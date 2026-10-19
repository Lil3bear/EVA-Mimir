import { test } from "node:test";
import assert from "node:assert/strict";
import { translate } from "../server/translate.mjs";

test("translation uses the configured model, does not store input or return source edits", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "https://api.openai.com/v1/responses");
    const body = JSON.parse(options.body);
    assert.equal(body.model, "test-model");
    assert.equal(body.store, false);
    assert.equal(body.input, "A 16.0 pp increase.");
    assert.match(body.instructions, /untrusted DATA/);
    assert.deepEqual(body.text.format.schema.required, ["translation"]);
    return { ok: true, json: async () => ({ status: "completed", output: [{content: [{ type: "output_text", text: JSON.stringify({translation: "提高了 16.0 个百分点。"}) }]}] }) };
  });
  assert.deepEqual(await translate("A 16.0 pp increase.", {provider: "openai", apiKey: "test", model: "test-model"}), {translation: "提高了 16.0 个百分点。"});
});

test("translation rejects incomplete output and missing credentials", async (t) => {
  await assert.rejects(translate("text", {provider: "openai"}), /API Key/);
  t.mock.method(globalThis, "fetch", async () => ({ok: true, json: async () => ({status: "incomplete"})}));
  await assert.rejects(translate("text", {provider: "openai", apiKey: "test"}), /不完整/);
});
