/**
 * End-to-end integration test validating TypeScript RPC Client
 * communicating with the Python QA Engine over child process stdio.
 */

const { spawn } = require("child_process");
const path = require("path");
const { RPCClient } = require("./out/rpc/client");

async function runIntegrationTest() {
  console.log("=== Starting TypeScript <-> Python Engine Integration Test ===");

  const workspaceRoot = path.resolve(__dirname, "..");
  const engineDir = path.join(workspaceRoot, "engine");
  const pythonPath = path.join(engineDir, ".venv", "Scripts", "python.exe");

  const child = spawn(pythonPath, ["-u", "-m", "qa_engine.main"], {
    cwd: engineDir,
    env: { ...process.env, PYTHONPATH: engineDir, PYTHONUNBUFFERED: "1" },
    shell: false,
    stdio: ["pipe", "pipe", "pipe"],
  });

  child.stderr.on("data", (d) => {
    console.warn(`[Engine stderr]: ${d.toString()}`);
  });

  const rpc = new RPCClient(child.stdin, child.stdout);
  let cardReceived = false;
  let stageUpdateReceived = false;

  rpc.on("notify:card.show", (params) => {
    console.log(`[Notification Received]: card.show -> type=${params.card_type}`);
    if (params.card_type === "scope_card") {
      cardReceived = true;
    }
  });

  rpc.on("notify:stage.update", (params) => {
    console.log(`[Notification Received]: stage.update -> stage=${params.stage}`);
    if (params.stage === "STAGE_1_INTAKE") {
      stageUpdateReceived = true;
    }
  });

  try {
    // 1. Send run.start
    console.log("Step 1: Sending run.start...");
    const startResult = await rpc.sendRequest("run.start", {
      run_id: "test-run-e2e-phase2",
      workspace_root: workspaceRoot,
      start_url: "https://staging.example.com",
      allowed_domains: ["staging.example.com"],
    });
    console.log("run.start response:", startResult);
    if (startResult.status !== "initialized") {
      throw new Error(`Unexpected start status: ${startResult.status}`);
    }

    // Give time for notification event dispatch
    await new Promise((r) => setTimeout(r, 200));
    if (!cardReceived) {
      throw new Error("Failed to receive 'scope_card' notification from engine.");
    }

    // 2. Send run.scope.confirm (Gate 0)
    console.log("Step 2: Sending run.scope.confirm (Gate 0)...");
    const scopeResult = await rpc.sendRequest("run.scope.confirm", {
      scope: {
        start_url: "https://staging.example.com",
        allowed_domains: ["staging.example.com"],
        environment: "test",
        authorized_attestation: true,
      },
    });
    console.log("run.scope.confirm response:", scopeResult);
    if (scopeResult.stage !== "STAGE_1_INTAKE") {
      throw new Error(`Unexpected stage after Gate 0: ${scopeResult.stage}`);
    }

    await new Promise((r) => setTimeout(r, 200));
    if (!stageUpdateReceived) {
      throw new Error("Failed to receive 'stage.update' notification for STAGE_1_INTAKE.");
    }

    // 3. Send run.cancel
    console.log("Step 3: Sending run.cancel...");
    const cancelResult = await rpc.sendRequest("run.cancel", {
      reason: "Integration test completed successfully",
    });
    console.log("run.cancel response:", cancelResult);

    console.log("=== Integration Test PASSED 100%! ===");
  } finally {
    child.kill("SIGTERM");
  }
}

runIntegrationTest().catch((err) => {
  console.error("Integration test failed:", err);
  process.exit(1);
});

