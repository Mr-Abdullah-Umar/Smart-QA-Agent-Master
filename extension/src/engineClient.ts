/**
 * Python Engine child process supervisor and JSON-RPC lifecycle manager.
 *
 * Engine code location (first match wins):
 *   1. setting qaHarness.enginePath
 *   2. <workspace>/engine            (when developing the harness itself)
 *   3. <extension>/engine            (bundled copy shipped inside the VSIX)
 * Python interpreter (first match wins):
 *   1. setting qaHarness.pythonPath
 *   2. <engine>/.venv, <workspace>/.venv
 *   3. private venv created by "QA Harness: Set Up Engine" in extension global storage
 */

import { ChildProcess, spawn } from "child_process";
import * as path from "path";
import * as fs from "fs";
import * as vscode from "vscode";
import { RequestHandler, RPCClient } from "./rpc/client";

const IS_WINDOWS = process.platform === "win32";

function venvPython(dir: string): string {
  return IS_WINDOWS ? path.join(dir, "Scripts", "python.exe") : path.join(dir, "bin", "python");
}

/** Failure-investigation limits sent with every run (design calls are never limited). */
export function aiCostOptions(config: { get<T>(key: string, fallback: T): T }): Record<string, unknown> {
  const max = Math.max(0, Math.floor(config.get<number>("ai.maxInvestigationsPerRun", 5)));
  return {
    ai_investigation: config.get<boolean>("ai.investigateFailures", true) && max > 0,
    ai_max_investigations: max,
    ai_daily_investigation_limit: Math.max(0, Math.floor(config.get<number>("ai.dailyInvestigationLimit", 50))),
    ai_reuse_analyses: config.get<boolean>("ai.reuseAnalyses", true),
  };
}

export class EngineClient {
  private process: ChildProcess | null = null;
  private rpcClient: RPCClient | null = null;
  private isTerminating = false;
  private readonly output: vscode.OutputChannel;
  private readonly exitEmitter = new vscode.EventEmitter<number | null>();
  private readonly startEmitter = new vscode.EventEmitter<RPCClient>();
  private readonly requestHandlers = new Map<string, RequestHandler>();
  public readonly onDidExit = this.exitEmitter.event;
  public readonly onDidStart = this.startEmitter.event;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.output = vscode.window.createOutputChannel("QA Harness Engine");
    context.subscriptions.push(this.output, this.exitEmitter, this.startEmitter);
  }

  public get isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }

  public get rpc(): RPCClient {
    if (!this.rpcClient) {
      throw new Error("Engine process is not started.");
    }
    return this.rpcClient;
  }

  /** Register a handler for engine -> extension requests (kept across engine restarts). */
  public handleRequest(method: string, handler: RequestHandler): void {
    this.requestHandlers.set(method, handler);
    this.rpcClient?.onRequest(method, handler);
  }

  public workspaceRoot(): string {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
      throw new Error("Open a project folder first: suites and reports are stored inside it.");
    }
    return folders[0].uri.fsPath;
  }

  private hasEngine(dir: string): boolean {
    return fs.existsSync(path.join(dir, "qa_engine", "main.py"));
  }

  public resolveEngineDir(): string {
    const configured = vscode.workspace.getConfiguration("qaHarness").get<string>("enginePath", "");
    const candidates = [
      configured,
      vscode.workspace.workspaceFolders?.[0]
        ? path.join(vscode.workspace.workspaceFolders[0].uri.fsPath, "engine")
        : "",
      path.join(this.context.extensionPath, "engine"),
    ].filter(Boolean);
    const found = candidates.find((dir) => this.hasEngine(dir));
    if (!found) {
      throw new Error("QA engine files not found. Reinstall the extension or set qaHarness.enginePath.");
    }
    return found;
  }

  private privateVenvDir(): string {
    return path.join(this.context.globalStorageUri.fsPath, "engine-venv");
  }

  public resolvePythonPath(engineDir: string): string | undefined {
    const configured = vscode.workspace.getConfiguration("qaHarness").get<string>("pythonPath", "");
    if (configured && fs.existsSync(configured)) {
      return configured;
    }
    const candidates = [venvPython(path.join(engineDir, ".venv")), this.privateVenvPython()];
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (folder) {
      candidates.splice(1, 0, venvPython(path.join(folder.uri.fsPath, ".venv")));
    }
    return candidates.find((p) => fs.existsSync(p));
  }

  private privateVenvPython(): string {
    return venvPython(this.privateVenvDir());
  }

  public isSetUp(): boolean {
    try {
      return Boolean(this.resolvePythonPath(this.resolveEngineDir()));
    } catch {
      return false;
    }
  }

  public async start(): Promise<void> {
    if (this.isRunning) {
      return;
    }
    const engineDir = this.resolveEngineDir();
    const pythonPath = this.resolvePythonPath(engineDir);
    if (!pythonPath) {
      throw new Error('The QA engine is not set up yet. Run "QA Harness: Set Up Engine" first.');
    }
    this.output.appendLine(`Starting engine: ${pythonPath} -m qa_engine.main (cwd ${engineDir})`);

    this.process = spawn(pythonPath, ["-u", "-m", "qa_engine.main"], {
      cwd: engineDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONUTF8: "1", PYTHONPATH: engineDir },
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });

    if (!this.process.stdin || !this.process.stdout || !this.process.stderr) {
      throw new Error("Failed to capture standard I/O pipes from Python engine process.");
    }

    const client = new RPCClient(this.process.stdin, this.process.stdout);
    for (const [method, handler] of this.requestHandlers) {
      client.onRequest(method, handler);
    }
    this.rpcClient = client;

    this.process.stderr.on("data", (chunk: Buffer) => {
      this.output.append(chunk.toString("utf-8"));
    });

    const proc = this.process;
    proc.on("error", (err) => {
      this.output.appendLine(`Failed to launch engine: ${err.message}`);
    });

    proc.on("exit", (code, signal) => {
      this.output.appendLine(`Python engine exited with code: ${code}, signal: ${signal}`);
      if (this.process !== proc) {
        return;
      }
      this.rpcClient?.rejectAllPending(new Error(`Engine process exited (${code})`));
      this.process = null;
      this.rpcClient = null;
      this.exitEmitter.fire(code);
    });
    this.startEmitter.fire(client);
  }

  /** Send a request to the engine, starting it first if needed. */
  public async request<T = Record<string, unknown>>(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = 60_000
  ): Promise<T> {
    await this.start();
    return this.rpc.sendRequest<T>(
      method,
      { workspace_root: this.workspaceRoot(), ...params },
      timeoutMs
    );
  }

  public browserOptions(): Record<string, unknown> {
    const config = vscode.workspace.getConfiguration("qaHarness");
    return {
      headed: config.get<boolean>("headed", true),
      slowmo_ms: config.get<number>("slowMoMs", 500),
      browser_channel: config.get<string>("browserChannel", "chrome"),
      ...aiCostOptions(config),
    };
  }

  public async cancel(approver?: string): Promise<void> {
    if (!this.isRunning) {
      return;
    }
    try {
      await this.rpc.sendRequest(
        "run.cancel",
        { reason: "User cancelled in VS Code", approver: approver || "" },
        5000
      );
    } catch (e) {
      this.output.appendLine(`Graceful cancel failed, stopping engine: ${e}`);
      this.terminate();
    }
  }

  public terminate(): void {
    if (!this.process || this.isTerminating) {
      return;
    }
    this.isTerminating = true;
    try {
      if (IS_WINDOWS && this.process.pid) {
        const taskkill = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "taskkill.exe");
        spawn(taskkill, ["/pid", this.process.pid.toString(), "/f", "/t"]);
      } else {
        this.process.kill("SIGTERM");
      }
    } catch (e) {
      this.output.appendLine(`Error stopping engine process: ${e}`);
    } finally {
      this.process = null;
      this.rpcClient = null;
      this.isTerminating = false;
    }
  }

  // ---------------------------------------------------------------- one-click setup

  private run(cmd: string, args: string[], cwd?: string): Promise<number> {
    this.output.appendLine(`> ${cmd} ${args.join(" ")}`);
    return new Promise((resolve) => {
      const child = spawn(cmd, args, { cwd, shell: false, env: { ...process.env, PYTHONUTF8: "1" } });
      child.stdout?.on("data", (d: Buffer) => this.output.append(d.toString("utf-8")));
      child.stderr?.on("data", (d: Buffer) => this.output.append(d.toString("utf-8")));
      child.on("error", (err) => {
        this.output.appendLine(err.message);
        resolve(-1);
      });
      child.on("exit", (code) => resolve(code ?? -1));
    });
  }

  private async findSystemPython(): Promise<string[] | undefined> {
    const candidates: string[][] = IS_WINDOWS
      ? [["py", "-3"], ["python"], ["python3"]]
      : [["python3"], ["python"]];
    for (const candidate of candidates) {
      const code = await this.run(candidate[0], [
        ...candidate.slice(1),
        "-c",
        "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)",
      ]);
      if (code === 0) return candidate;
    }
    return undefined;
  }

  /** Create a private venv, install engine requirements, and download Playwright Chromium. */
  public async setUp(): Promise<void> {
    const engineDir = this.resolveEngineDir();
    const requirements = path.join(engineDir, "requirements.txt");
    this.output.show(true);
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "QA Harness: setting up the engine",
        cancellable: false,
      },
      async (progress) => {
        let python = this.resolvePythonPath(engineDir);
        if (!python) {
          progress.report({ message: "Finding Python 3.10+ ..." });
          const system = await this.findSystemPython();
          if (!system) {
            throw new Error("Python 3.10 or newer was not found. Install it from python.org first.");
          }
          progress.report({ message: "Creating a private virtual environment ..." });
          fs.mkdirSync(this.context.globalStorageUri.fsPath, { recursive: true });
          const code = await this.run(system[0], [...system.slice(1), "-m", "venv", this.privateVenvDir()]);
          if (code !== 0) throw new Error("Could not create the virtual environment.");
          python = this.privateVenvPython();
        }
        progress.report({ message: "Installing engine packages (pip) ..." });
        if ((await this.run(python, ["-m", "pip", "install", "--upgrade", "pip"])) !== 0) {
          this.output.appendLine("pip self-upgrade failed; continuing.");
        }
        if ((await this.run(python, ["-m", "pip", "install", "-r", requirements])) !== 0) {
          throw new Error("Installing engine packages failed. See the QA Harness Engine output.");
        }
        progress.report({ message: "Downloading the Playwright Chromium browser ..." });
        if ((await this.run(python, ["-m", "playwright", "install", "chromium"])) !== 0) {
          throw new Error("Installing the Playwright browser failed. See the output channel.");
        }
      }
    );
    this.terminate();
  }
}
