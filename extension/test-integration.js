/**
 * End-to-end integration test: TypeScript RPC client <-> Python engine over stdio.
 *
 * Plays the extension's role for engine -> extension requests (`llm.chat` with scripted
 * replies, `secrets.resolve`) and walks the full workflow: AI suite design with
 * clarifications, revision, Gate 1 approval, execution, retest, and regression.
 *
 * Usage: node test-integration.js <target-url> [--headed]
 *        (or set QA_TARGET_URL). Artifacts go to a temporary workspace.
 */

const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { RPCClient } = require("./out/rpc/client");

const targetUrl = process.argv.find((a) => /^https?:\/\//.test(a)) || process.env.QA_TARGET_URL;
const headed = process.argv.includes("--headed");
if (!targetUrl) {
  console.error("Usage: node test-integration.js <target-url> [--headed]");
  process.exit(2);
}
const host = new URL(targetUrl).hostname;

const MISSING_BUTTON = "QA harness missing element 7f3a";

function testcase(ac, i, titleSuffix, id, broken = false) {
  return {
    tc_id: id || null,
    title: `${ac} check ${titleSuffix}`,
    ac_ref: ac,
    priority: i === 0 ? "P1" : "P2",
    priority_rationale: i === 0 ? "Entry point" : null,
    test_types: i === 0 ? ["smoke", "sanity"] : ["functional"],
    steps: ["Open the start page", "Observe the address bar"],
    expected_result: `The browser stays on ${host}`,
    actions: [
      { action: "goto", value: "" },
      ...(broken ? [{ action: "click", target: { by: "role", role: "button", value: MISSING_BUTTON } }] : []),
      { action: "expect_url", value: host },
    ],
  };
}

/** Two valid cases; `extra` appends more AC-2 cases (default one), optionally with a broken locator. */
function designReply(titleSuffix, keepIds = [], extra = null) {
  const testcases = ["AC-1", "AC-2"].map((ac, i) => testcase(ac, i, titleSuffix, keepIds[i]));
  for (let n = 0; extra && n < (extra.count || 1); n++) {
    testcases.push(testcase("AC-2", 1, `${titleSuffix} extra ${n + 1}`, keepIds[2 + n], extra.broken));
  }
  return JSON.stringify({ testcases });
}

function investigationReply() {
  return JSON.stringify({
    failure_id: "x",
    tc_id: "x",
    category: "Automation issue",
    confidence: 0.8,
    facts: [{ statement: "The button was not found", evidence_id: "EV-001" }],
    hypotheses: [{ hypothesis: "The locator does not exist on the page", supporting_indicators: [] }],
    evidence_citations: ["EV-001"],
    reproduction_steps: ["Open the start page"],
    recommended_action: "Fix the locator",
    preventive_measure: "Use the dry run",
  });
}

function scriptedLlm(params) {
  const prompt = (params.messages || []).map((m) => m.content).join("\n");
  if (prompt.includes("Investigate test failure for")) return investigationReply();
  if (prompt.includes("Ask at most 5 clarification questions")) {
    return JSON.stringify({
      summary: "Start page must load and stay on the domain.",
      clarification_questions: [
        { question_id: "Q-1", question_text: "Which browser matters most?", context: "Scope" },
      ],
    });
  }
  if (prompt.includes("BEGIN UNTRUSTED LINK LIST")) return JSON.stringify({ urls: [] });
  if (prompt.includes("BEGIN REVIEWER COMMENTS")) {
    const current = prompt.match(/Current test cases \(JSON\):\n(.*)\n/);
    const ids = current ? JSON.parse(current[1]).map((tc) => tc.tc_id) : [];
    if (prompt.includes("The dry run could not execute")) {
      return designReply("(repaired)", ids, { broken: false });
    }
    if (prompt.includes("were updated")) return designReply("(updated)", ids);
    if (prompt.includes("TWO BROKEN")) return designReply("(costly)", ids, { broken: true, count: 2 });
    return designReply("(revised)", ids, { broken: true });
  }
  return designReply("(v1)");
}

async function main() {
  const workspaceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "qa-ext-e2e-"));
  const engineDir = path.resolve(__dirname, "..", "engine");
  const pythonPath = path.join(
    engineDir,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python"
  );
  console.log(`Workspace: ${workspaceRoot}\nTarget: ${targetUrl}`);

  const child = spawn(pythonPath, ["-u", "-m", "qa_engine.main"], {
    cwd: engineDir,
    env: { ...process.env, PYTHONPATH: engineDir, PYTHONUNBUFFERED: "1" },
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stderr.on("data", (d) => process.stderr.write(`[engine] ${d}`));

  const rpc = new RPCClient(child.stdin, child.stdout, 120000);
  let llmCalls = 0;
  const purposes = { design: 0, investigation: 0 };
  rpc.onRequest("llm.chat", async (params) => {
    llmCalls += 1;
    purposes[params.purpose] = (purposes[params.purpose] || 0) + 1;
    return { content: scriptedLlm(params), model: "scripted/test" };
  });
  rpc.onRequest("secrets.resolve", async () => ({ values: {} }));

  const waiters = [];
  rpc.on("notify:card.show", (p) => {
    console.log(`  card: ${p.card_type}`);
    const idx = waiters.findIndex((w) => w.type === p.card_type);
    if (idx >= 0) waiters.splice(idx, 1)[0].resolve(p.data);
  });
  rpc.on("notify:stage.update", (p) => console.log(`  stage: ${p.stage} - ${p.description}`));
  rpc.on("notify:message.stream", (p) => {
    if (p.style !== "log" && p.chunk) console.log(`  say: ${p.chunk}`);
    if (/Run failed/.test(p.chunk || "")) waiters.splice(0).forEach((w) => w.reject(new Error(p.chunk)));
  });
  const waitCard = (type) =>
    new Promise((resolve, reject) => {
      waiters.push({ type, resolve, reject });
      setTimeout(() => reject(new Error(`Timed out waiting for ${type}`)), 600000).unref();
    });
  const call = (method, params) => rpc.sendRequest(method, { workspace_root: workspaceRoot, ...params });
  const options = { headed, slowmo_ms: headed ? 300 : 0, browser_channel: "chrome", ai_enabled: true };
  const approver = "integration-tester";

  try {
    const scope = waitCard("scope_card");
    await call("run.start", {
      module: "Integration Module",
      start_url: targetUrl,
      environment: "test",
      requirement_text: "The start page is reachable.",
      acceptance_criteria: "Start page loads\nUser stays on the domain",
      design_mode: "ai",
      ...options,
    });
    const scopeData = await scope;

    const clarify = waitCard("clarification_card");
    await call("run.scope.confirm", {
      approver,
      scope: { ...scopeData, environment: "test", authorized_attestation: true },
    });
    const questions = await clarify;
    const review1 = waitCard("review_card");
    await call("run.clarifications.answer", {
      approver,
      answers: { [questions.questions[0].question_id]: "Chrome" },
    });
    const v1 = await review1;

    // v2 adds a case whose click target does not exist: the dry run must catch it.
    const review2 = waitCard("review_card");
    await call("run.testcases.revise", { approver, comments: "Add one more AC-2 case." });
    const v2 = await review2;
    if (v2.version !== 2 || !v2.diff_summary) throw new Error("Revision did not produce v2");
    const dryRun = waitCard("dry_run_card");
    await call("run.testcases.approve", { approver, version: v2.version, sha256_hash: v2.sha256_hash });
    const dryRunData = await dryRun;

    const review3 = waitCard("review_card");
    await call("run.dryrun.decide", { approver, decision: "fix" });
    const v3 = await review3;
    const report = waitCard("report_card");
    await call("run.testcases.approve", { approver, version: v3.version, sha256_hash: v3.sha256_hash });
    const initial = await report;
    console.log(`Initial run: ${initial.passed}/${initial.total} passed`);

    const list = await call("suites.list", {});
    const slug = list.suites[0].slug;
    const stored = await call("suite.get", { slug });

    // Update: same module, edited requirement -> AI revises the approved suite (keeps IDs).
    const updScope = waitCard("scope_card");
    await call("run.start", {
      module: "Integration Module",
      start_url: targetUrl,
      environment: "test",
      requirement_text: "The start page is reachable (edited).",
      acceptance_criteria: "Start page loads\nUser stays on the domain",
      design_mode: "ai",
      ...options,
    });
    const updScopeData = await updScope;
    const updClarify = waitCard("clarification_card");
    await call("run.scope.confirm", {
      approver,
      scope: { ...updScopeData, environment: "test", authorized_attestation: true },
    });
    const updQuestions = await updClarify;
    const updReview = waitCard("review_card");
    await call("run.clarifications.answer", {
      approver,
      answers: { [updQuestions.questions[0].question_id]: "Chrome" },
    });
    const updated = await updReview;
    const updReport = waitCard("report_card");
    await call("run.testcases.approve", { approver, version: updated.version, sha256_hash: updated.sha256_hash });
    const updRun = await updReport;

    const retest = waitCard("report_card");
    await call("suite.retest", {
      slug,
      approver,
      authorized_attestation: true,
      environment: "staging",
      base_url: targetUrl,
      ...options,
    });
    const retestData = await retest;
    const afterRetest = (await call("suites.list", {})).suites[0];

    const regression = waitCard("regression_card");
    await call("regression.run", {
      approver,
      authorized_attestation: true,
      tag: "smoke",
      environment: "staging",
      ...options,
    });
    const reg = await regression;

    // Cost controls: two cases fail with the same error -> one AI analysis, one reuse;
    // retesting them reuses the stored analyses -> no AI call.
    const costScope = waitCard("scope_card");
    await call("run.start", {
      module: "Cost Module",
      start_url: targetUrl,
      environment: "test",
      requirement_text: "The start page is reachable.",
      acceptance_criteria: "Start page loads\nUser stays on the domain",
      design_mode: "ai",
      ...options,
    });
    const costScopeData = await costScope;
    const costClarify = waitCard("clarification_card");
    await call("run.scope.confirm", {
      approver,
      scope: { ...costScopeData, environment: "test", authorized_attestation: true },
    });
    const costQuestions = await costClarify;
    const costReview1 = waitCard("review_card");
    await call("run.clarifications.answer", {
      approver,
      answers: { [costQuestions.questions[0].question_id]: "Chrome" },
    });
    await costReview1;
    const costReview2 = waitCard("review_card");
    await call("run.testcases.revise", { approver, comments: "Add TWO BROKEN cases." });
    const costV2 = await costReview2;
    const costDry = waitCard("dry_run_card");
    await call("run.testcases.approve", { approver, version: costV2.version, sha256_hash: costV2.sha256_hash });
    const costDryData = await costDry;
    const investigationsBefore = purposes.investigation;
    const costReport = waitCard("report_card");
    await call("run.dryrun.decide", { approver, decision: "run" });
    const costRun = await costReport;
    const firstRunInvestigations = purposes.investigation - investigationsBefore;
    const costSlug = (await call("suites.list", {})).suites.find((s) => s.module === "Cost Module").slug;
    const costRetest = waitCard("report_card");
    await call("suite.retest", {
      slug: costSlug,
      approver,
      failed_only: true,
      authorized_attestation: true,
      ...options,
    });
    const costRetestData = await costRetest;
    const retestInvestigations = purposes.investigation - investigationsBefore - firstRunInvestigations;
    const usage = await call("ai.usage", {});
    const costHtml = fs.readFileSync(costRun.report_html, "utf-8");
    await call("suite.delete", { slug: costSlug, approver });

    const deleted = await call("suite.delete", { slug, approver });
    const afterDelete = await call("suites.list", {});

    const checks = {
      "design produced 2 cases": v1.testcases.length === 2,
      "revision kept case IDs":
        JSON.stringify(v2.testcases.slice(0, 2).map((t) => t.tc_id)) ===
        JSON.stringify(v1.testcases.map((t) => t.tc_id)),
      "dry run flagged only the missing element":
        dryRunData.issues.length === 1 &&
        dryRunData.issues[0].kind === "not_found" &&
        dryRunData.issues[0].tc_id === v2.testcases[2].tc_id,
      "dry-run fix went back to review as v3": v3.version === 3 && v3.testcases.length === 3,
      "initial run executed the 3 repaired cases": initial.total === 3 && initial.failed === 0,
      "suite.get returns the stored requirement": stored.requirement_text === "The start page is reachable.",
      "update kept IDs and dropped the extra case":
        updated.testcases.length === 2 &&
        updated.testcases.every((t, i) => t.tc_id === v1.testcases[i].tc_id) &&
        /Changes against approved suite/.test(updated.diff_summary || ""),
      "updated suite ran as an update": updRun.total === 2 && updRun.run_type === "update",
      "retest ran on the staging environment":
        retestData.run_type === "retest" && retestData.environment === "staging",
      "staging environment was saved": afterRetest.environments.staging === targetUrl,
      "smoke regression on staging ran only the 1 smoke case":
        reg.totals.total === 1 && reg.environment === "staging",
      "dry run flagged both broken cases": costDryData.issues.length === 2,
      "run anyway: broken cases failed, valid cases passed": costRun.failed === 2 && costRun.passed === 2,
      "same error twice -> 1 AI analysis + 1 reuse":
        firstRunInvestigations === 1 &&
        costRun.ai_usage.investigations.ai === 1 &&
        costRun.ai_usage.investigations.reused === 1,
      "report shows how each failure was analyzed": /Analysis:\s*AI \(reused in this run\)/.test(costHtml),
      "retest of the same failures used no AI":
        retestInvestigations === 0 &&
        costRetestData.failed === 2 &&
        costRetestData.ai_usage.investigations.cached === 2,
      "usage ledger counted design and investigation calls":
        usage.today.investigation === 1 && usage.today.design >= 5,
      "design calls are tagged as design": purposes.design === llmCalls - purposes.investigation,
      "delete archived the suite": deleted.status === "archived" && afterDelete.suites.length === 0,
      "AI used for analysis, design, revision and repair": llmCalls >= 5,
    };
    for (const [name, passed] of Object.entries(checks)) {
      console.log(`  [${passed ? "ok" : "FAIL"}] ${name}`);
    }
    const ok = Object.values(checks).every(Boolean);
    console.log(`\nLLM calls: ${llmCalls}; regression report: ${reg.report_html}`);
    console.log(ok ? "=== INTEGRATION TEST PASSED ===" : "=== INTEGRATION TEST FAILED ===");
    process.exitCode = ok ? 0 : 1;
  } catch (e) {
    console.error("=== INTEGRATION TEST FAILED ===", e);
    process.exitCode = 1;
  } finally {
    child.stdin.end();
    child.kill();
  }
}

main();
