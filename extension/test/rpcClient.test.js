const test = require("node:test");
const assert = require("node:assert/strict");
const { PassThrough } = require("stream");
const { RPCClient } = require("../out/rpc/client");

function harness(timeoutMs = 1000) {
  const toEngine = new PassThrough();
  const fromEngine = new PassThrough();
  const sent = [];
  toEngine.on("data", (chunk) =>
    chunk
      .toString()
      .split("\n")
      .filter(Boolean)
      .forEach((line) => sent.push(JSON.parse(line)))
  );
  const client = new RPCClient(toEngine, fromEngine, timeoutMs);
  const reply = (msg) => fromEngine.write(JSON.stringify(msg) + "\n");
  return { client, sent, reply, fromEngine };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("resolves a request with the matching response", async () => {
  const { client, sent, reply } = harness();
  const pending = client.sendRequest("engine.info", { a: 1 });
  await tick();
  assert.equal(sent[0].method, "engine.info");
  assert.deepEqual(sent[0].params, { a: 1 });
  reply({ jsonrpc: "2.0", id: sent[0].id, result: { version: "x" } });
  assert.deepEqual(await pending, { version: "x" });
});

test("rejects with the engine error", async () => {
  const { client, sent, reply } = harness();
  const pending = client.sendRequest("suite.get", { slug: "missing" });
  await tick();
  reply({ jsonrpc: "2.0", id: sent[0].id, error: { code: -32000, message: "no such suite" } });
  await assert.rejects(pending, (e) => e.message === "no such suite");
});

test("reassembles responses split across chunks", async () => {
  const { client, sent, fromEngine } = harness();
  const pending = client.sendRequest("suite.list");
  await tick();
  const line = JSON.stringify({ jsonrpc: "2.0", id: sent[0].id, result: { suites: [] } }) + "\n";
  fromEngine.write(line.slice(0, 10));
  fromEngine.write(line.slice(10));
  assert.deepEqual(await pending, { suites: [] });
});

test("times out requests that never get a response", async () => {
  const { client } = harness(30);
  await assert.rejects(client.sendRequest("slow"), /timed out/);
});

test("rejects pending requests when the engine exits", async () => {
  const { client, fromEngine } = harness();
  const pending = client.sendRequest("run.start");
  fromEngine.end();
  await assert.rejects(pending, /closed/);
});

test("emits notifications by method", async () => {
  const { client, reply } = harness();
  const seen = new Promise((resolve) => client.on("notify:run.log", resolve));
  reply({ jsonrpc: "2.0", method: "run.log", params: { line: "hello" } });
  assert.deepEqual(await seen, { line: "hello" });
});

test("answers engine-to-extension requests through registered handlers", async () => {
  const { client, sent, reply } = harness();
  client.onRequest("llm.chat", async (params) => ({ content: `echo ${params.q}` }));
  reply({ jsonrpc: "2.0", id: "e1", method: "llm.chat", params: { q: "hi" } });
  reply({ jsonrpc: "2.0", id: "e2", method: "secrets.resolve", params: {} });
  reply({ jsonrpc: "2.0", id: "e3", method: "llm.chat", params: null });
  await tick();
  await tick();
  const byId = Object.fromEntries(sent.map((m) => [m.id, m]));
  assert.deepEqual(byId.e1.result, { content: "echo hi" });
  assert.equal(byId.e2.error.code, -32601);
  assert.deepEqual(byId.e3.result, { content: "echo undefined" });
});

test("reports handler failures as JSON-RPC errors", async () => {
  const { client, sent, reply } = harness();
  client.onRequest("secrets.resolve", async () => {
    throw new Error("user dismissed");
  });
  reply({ jsonrpc: "2.0", id: 7, method: "secrets.resolve", params: {} });
  await tick();
  await tick();
  assert.equal(sent[0].id, 7);
  assert.equal(sent[0].error.message, "user dismissed");
});
