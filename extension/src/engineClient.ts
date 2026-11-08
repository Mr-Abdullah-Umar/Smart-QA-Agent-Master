/**
 * Python Engine child process supervisor and JSON-RPC lifecycle manager.
 */

import { ChildProcess, spawn } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as vscode from "vscode";
import { RPCClient } from "./rpc/client";
import { ScopePayload } from "./rpc/protocol";

export class EngineClient {
  private process: ChildProcess | null = null;
  private rpcClient: RPCClient | null = null;
  private isTerminating = false;

  constructor(private readonly context: vscode.ExtensionContext) {}

  public get isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }

  public get rpc(): RPCClient {
    if (!this.rpcClient) {
      throw new Error("Engine process is not started.");
    }
    return this.rpcClient;
  }

  public async start(): Promise<void> {
    if (this.isRunning) {
      return;
    }

    const pythonPath = this.resolvePythonPath();
    const workspaceRoot = this.getWorkspaceRoot();
    const engineDir = path.join(workspaceRoot, "engine");

    const env = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      PYTHONPATH: engineDir,
    };

    this.process = spawn(pythonPath, ["-u", "-m", "qa_engine.main"], {
      cwd: engineDir,
      env,
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });

    if (!this.process.stdin || !this.process.stdout || !this.process.stderr) {
      throw new Error("Failed to capture standard I/O pipes from Python engine process.");
    }

    this.rpcClient = new RPCClient(this.process.stdin, this.process.stdout);

    this.process.stderr.on("data", (chunk: Buffer) => {
      const errText = chunk.toString("utf-8");
      console.warn(`[Python Engine stderr]: ${errText}`);
    });

    this.process.on("exit", (code, signal) => {
      console.log(`Python engine exited with code: ${code}, signal: ${signal}`);
      this.rpcClient?.rejectAllPending(new Error(`Engine process exited (${code})`));
      this.process = null;
      this.rpcClient = null;
    });
  }

  public resolvePythonPath(): string {
    const configPath = vscode.workspace.getConfiguration("qaHarness").get<string>("pythonPath");
    if (configPath && fs.existsSync(configPath)) {
      return configPath;
    }

    const workspaceRoot = this.getWorkspaceRoot();
    const isWindows = process.platform === "win32";

    // Check engine/.venv
    const venvPython = isWindows
      ? path.join(workspaceRoot, "engine", ".venv", "Scripts", "python.exe")
      : path.join(workspaceRoot, "engine", ".venv", "bin", "python");

    if (fs.existsSync(venvPython)) {
      return venvPython;
    }

    // Check workspace root .venv
    const rootVenvPython = isWindows
      ? path.join(workspaceRoot, ".venv", "Scripts", "python.exe")
      : path.join(workspaceRoot, ".venv", "bin", "python");

    if (fs.existsSync(rootVenvPython)) {
      return rootVenvPython;
    }

    return isWindows ? "python.exe" : "python";
  }

  private getWorkspaceRoot(): string {
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
      return folders[0].uri.fsPath;
    }
    return process.cwd();
  }

  public async startRun(params: {
    runId: string;
    requirementText?: string;
    startUrl?: string;
    allowedDomains?: string[];
  }): Promise<Record<string, unknown>> {
    await this.start();
    return this.rpc.sendRequest("run.start", {
      run_id: params.runId,
      workspace_root: this.getWorkspaceRoot(),
      requirement_text: params.requirementText || "",
      start_url: params.startUrl || "",
      allowed_domains: params.allowedDomains || [],
    });
  }

  public async confirmScope(scope: ScopePayload): Promise<Record<string, unknown>> {
    return this.rpc.sendRequest("run.scope.confirm", { scope });
  }

  public async approveTestcases(version: number, approver: string, sha256Hash: string): Promise<Record<string, unknown>> {
    return this.rpc.sendRequest("run.testcases.approve", {
      version,
      approver,
      sha256_hash: sha256Hash,
    });
  }

  public async cancel(): Promise<void> {
    if (!this.isRunning) {
      return;
    }

    try {
      await this.rpc.sendRequest("run.cancel", { reason: "User cancelled in VS Code" }, 3000);
    } catch (e) {
      console.warn("Graceful cancel request failed, forcing process termination:", e);
    } finally {
      this.terminate();
    }
  }

  public terminate(): void {
    if (!this.process || this.isTerminating) {
      return;
    }
    this.isTerminating = true;

    try {
      if (process.platform === "win32" && this.process.pid) {
        // Force-kill process tree on Windows
        spawn("taskkill", ["/pid", this.process.pid.toString(), "/f", "/t"]);
      } else {
        this.process.kill("SIGTERM");
      }
    } catch (e) {
      console.error("Error killing engine process:", e);
    } finally {
      this.process = null;
      this.rpcClient = null;
      this.isTerminating = false;
    }
  }
}

