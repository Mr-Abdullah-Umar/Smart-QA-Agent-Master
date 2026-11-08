const test = require("node:test");
const assert = require("node:assert/strict");
const { settings, MemorySecrets } = require("./vscode-mock");
const { AIService, parseModelList, rejectsTemperature } = require("../out/ai/aiService");

const realFetch = global.fetch;
let calls = [];

function respond(handler) {
  calls = [];
  global.fetch = async (url, init = {}) => {
    const call = { url, init, body: init.body ? JSON.parse(init.body) : undefined };
    calls.push(call);
    const { status = 200, json } = handler(call, calls.length);
    return { ok: status < 400, status, text: async () => JSON.stringify(json) };
  };
}

async function service(provider, extra = {}) {
  settings.clear();
  settings.set("qaHarness.ai.provider", provider);
  settings.set("qaHarness.ai.model", extra.model ?? "m-1");
  settings.set("qaHarness.ai.baseUrl", extra.baseUrl ?? "");
  const secrets = new MemorySecrets();
  if (extra.key !== null) await secrets.setApiKey(provider, extra.key ?? "sk-test");
  return new AIService(secrets);
}

test.after(() => {
  global.fetch = realFetch;
});

test("parseModelList handles OpenAI, Gemini and GitHub catalog shapes", () => {
  assert.deepEqual(parseModelList({ data: [{ id: "b" }, { id: "a" }, { id: "a" }] }), [
    { id: "a", name: "a" },
    { id: "b", name: "b" },
  ]);
  assert.deepEqual(parseModelList({ models: [{ name: "models/gemini-x", display_name: "Gemini X" }] }), [
    { id: "gemini-x", name: "Gemini X" },
  ]);
  assert.deepEqual(parseModelList([{ id: "openai/gpt-x", name: "GPT X" }]), [
    { id: "openai/gpt-x", name: "GPT X (openai/gpt-x)" },
  ]);
  assert.deepEqual(parseModelList(null), []);
});

test("rejectsTemperature only matches HTTP 400 temperature errors", () => {
  assert.ok(rejectsTemperature(new Error("AI provider HTTP 400: Unsupported value: 'temperature'")));
  assert.ok(!rejectsTemperature(new Error("AI provider HTTP 401: bad key")));
  assert.ok(!rejectsTemperature(new Error("AI provider HTTP 400: max_tokens too large")));
});

test("OpenAI chat sends model, key and temperature", async () => {
  const ai = await service("openai");
  respond(() => ({ json: { choices: [{ message: { content: "OK" } }] } }));
  const reply = await ai.chat([{ role: "user", content: "hi" }], 0.2);
  assert.equal(reply.content, "OK");
  assert.equal(reply.model, "openai/m-1");
  assert.equal(calls[0].url, "https://api.openai.com/v1/chat/completions");
  assert.equal(calls[0].init.headers.Authorization, "Bearer sk-test");
  assert.equal(calls[0].body.model, "m-1");
  assert.equal(calls[0].body.temperature, 0.2);
});

test("retries once without temperature when the model rejects it", async () => {
  const ai = await service("openai");
  respond((call) =>
    "temperature" in call.body
      ? { status: 400, json: { error: { message: "Unsupported parameter: 'temperature'" } } }
      : { json: { choices: [{ message: { content: "OK" } }] } }
  );
  const reply = await ai.chat([{ role: "user", content: "hi" }], 0.2);
  assert.equal(reply.content, "OK");
  assert.equal(calls.length, 2);
  assert.ok(!("temperature" in calls[1].body));
});

test("does not retry other HTTP errors", async () => {
  const ai = await service("openai");
  respond(() => ({ status: 401, json: { error: "bad key" } }));
  await assert.rejects(ai.chat([{ role: "user", content: "hi" }]), /HTTP 401/);
  assert.equal(calls.length, 1);
});

test("Anthropic chat moves system prompts and retries without temperature", async () => {
  const ai = await service("anthropic");
  respond((call) =>
    "temperature" in call.body
      ? { status: 400, json: { error: "temperature is not supported" } }
      : { json: { content: [{ type: "text", text: "OK" }] } }
  );
  const reply = await ai.chat(
    [
      { role: "system", content: "rules" },
      { role: "user", content: "hi" },
    ],
    0.2
  );
  assert.equal(reply.content, "OK");
  assert.equal(calls[1].body.system, "rules");
  assert.deepEqual(calls[1].body.messages, [{ role: "user", content: "hi" }]);
  assert.equal(calls[1].init.headers["x-api-key"], "sk-test");
});

test("Azure OpenAI uses the deployment URL and api-key header", async () => {
  const ai = await service("azure-openai", { model: "my deploy", baseUrl: "https://res.openai.azure.com" });
  respond(() => ({ json: { choices: [{ message: { content: "OK" } }] } }));
  await ai.chat([{ role: "user", content: "hi" }]);
  assert.match(calls[0].url, /^https:\/\/res\.openai\.azure\.com\/openai\/deployments\/my%20deploy\/chat\/completions\?api-version=/);
  assert.equal(calls[0].init.headers["api-key"], "sk-test");
  assert.ok(!("model" in calls[0].body));
});

test("GitHub Models chats on the inference endpoint and lists the catalog", async () => {
  const ai = await service("github-models", { model: "openai/gpt-x" });
  respond((call) =>
    call.url.endsWith("/catalog/models")
      ? { json: [{ id: "openai/gpt-x", name: "GPT X" }] }
      : { json: { choices: [{ message: { content: "OK" } }] } }
  );
  await ai.chat([{ role: "user", content: "hi" }]);
  assert.equal(calls[0].url, "https://models.github.ai/inference/chat/completions");
  const models = await ai.listModels();
  assert.equal(calls[1].url, "https://models.github.ai/catalog/models");
  assert.deepEqual(models.map((m) => m.id), ["openai/gpt-x"]);
});

test("refuses non-HTTPS endpoints before sending the key", async () => {
  const ai = await service("openai-compatible", { baseUrl: "http://insecure.example" });
  respond(() => ({ json: {} }));
  await assert.rejects(ai.chat([{ role: "user", content: "hi" }]), /https/);
  assert.equal(calls.length, 0);
});

test("status explains what is missing", async () => {
  assert.match((await (await service("openai", { key: null })).status()).detail, /API key/);
  assert.match((await (await service("openai", { model: "" })).status()).detail, /Choose a model/);
  assert.equal((await (await service("openai")).status()).ready, true);
  assert.equal((await (await service("none")).status()).ready, false);
  assert.equal((await (await service("copilot")).status()).ready, false);
});
