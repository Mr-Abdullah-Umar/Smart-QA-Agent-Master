const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { RunHistory } = require("../out/history");

function workspace() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "qa-history-"));
  return { root, history: new RunHistory(() => root), dir: path.join(root, ".qa-harness", "history") };
}

const step = (id, phase, extra) => ({ type: "activity", id, phase, ...extra });

test("records a suite run until its report card and persists it", () => {
  const { history, dir } = workspace();
  const session = history.start("suite", "Login", "example.com · test");
  history.record({ type: "user", text: "https://example.com login" });
  history.record(step("step-1", "start", { kind: "read", title: "Reading requirement" }));
  history.record(step("step-1", "end", { status: "done", detail: "3 criteria", duration_ms: 12 }));
  history.record({ type: "card.show", card_type: "review_card", data: {} });
  assert.equal(history.list()[0].status, "waiting");
  history.record({ type: "stage.update", stage: "STAGE_8_EXECUTION" });
  assert.equal(history.list()[0].status, "running");
  history.record({ type: "card.show", card_type: "report_card", data: { total: 5, passed: 4, failed: 1, blocked: 0 } });

  const [summary] = history.list();
  assert.equal(summary.id, session.id);
  assert.equal(summary.status, "failed");
  assert.deepEqual(summary.result, { total: 5, passed: 4, failed: 1 });
  assert.equal(summary.steps, 1);
  assert.ok(summary.endedAt);

  const stored = JSON.parse(fs.readFileSync(path.join(dir, `${session.id}.json`), "utf8"));
  assert.equal(stored.events.length, 6);
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, "index.json"), "utf8"))[0].id, session.id);
  // Once finished, later panel messages are not attached to the old run.
  assert.equal(history.record({ type: "message.stream", chunk: "unrelated", complete: true }), false);
});

test("coalesces log chunks and step progress", () => {
  const { history } = workspace();
  const session = history.start("retest", "Login", "all cases");
  history.record(step("s1", "start", { kind: "run", title: "Running 3 test(s)" }));
  for (let i = 0; i < 50; i++) {
    history.record({ type: "message.stream", chunk: `line ${i}\n`, complete: false, style: "log" });
    history.record(step("s1", "update", { detail: `${i}/50` }));
  }
  const events = history.open(session.id).events;
  assert.ok(events.length < 110, `expected coalescing, got ${events.length} events`);
  const logs = events.filter((e) => e.style === "log").map((e) => e.chunk).join("");
  assert.equal(logs.split("\n").filter(Boolean).length, 50);
});

test("regression ends on the regression card, not on each suite's COMPLETED stage", () => {
  const { history } = workspace();
  history.start("regression", "Regression", "2 suite(s)");
  history.record({ type: "stage.update", stage: "COMPLETED" });
  assert.equal(history.list()[0].status, "running");
  history.record({
    type: "card.show",
    card_type: "regression_card",
    data: { totals: { total: 8, passed: 8, failed: 0, blocked: 0 }, suites: [{ status: "passed" }] },
  });
  assert.equal(history.list()[0].status, "passed");
});

test("cancel, error, and a new run all close the previous session", () => {
  const { history } = workspace();
  const first = history.start("suite", "A", "");
  history.record({ type: "stage.update", stage: "CANCELLED" });
  const second = history.start("suite", "B", "");
  const third = history.start("retest", "C", "");
  history.end("error");
  const byId = Object.fromEntries(history.list().map((s) => [s.id, s.status]));
  assert.equal(byId[first.id], "cancelled");
  assert.equal(byId[second.id], "cancelled");
  assert.equal(byId[third.id], "error");
});

test("scope card for an existing suite marks the run as an update", () => {
  const { history } = workspace();
  history.start("suite", "Login", "");
  history.record({ type: "card.show", card_type: "scope_card", data: { updates_existing_suite: true } });
  assert.equal(history.list()[0].kind, "update");
});

test("delete removes a finished run and refuses unsafe ids or live runs", () => {
  const { history, dir } = workspace();
  const done = history.start("suite", "Old", "");
  history.end("passed");
  const live = history.start("retest", "Live", "");
  assert.equal(history.delete(live.id), false);
  assert.equal(history.delete("../../etc/passwd"), false);
  assert.equal(history.delete(done.id), true);
  assert.equal(fs.existsSync(path.join(dir, `${done.id}.json`)), false);
  assert.deepEqual(history.list().map((s) => s.id), [live.id]);
  assert.equal(history.open("../index"), undefined);
});

test("history survives a restart", () => {
  const { root, history } = workspace();
  const session = history.start("suite", "Persisted", "");
  history.record({ type: "message.stream", chunk: "hello", complete: true });
  history.end("passed");
  const reloaded = new RunHistory(() => root);
  assert.equal(reloaded.list()[0].id, session.id);
  assert.equal(reloaded.open(session.id).events[0].chunk, "hello");
});
