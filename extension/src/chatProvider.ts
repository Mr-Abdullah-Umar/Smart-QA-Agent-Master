/**
 * WebviewViewProvider for the QA Harness panel (Assistant, Suites, AI Provider tabs).
 * Enforces strict Content Security Policy (CSP nonces) and mediates user actions between
 * the webview and the Python engine. Every human gate is signed with the GitHub account.
 */

import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { AIService, PROVIDERS, ProviderId } from "./ai/aiService";
import { EngineClient } from "./engineClient";
import { RunHistory, SessionKind } from "./history";
import { IdentityService } from "./identity";
import { RPCClient } from "./rpc/client";
import { generateWebviewCSP } from "./security/csp";
import { HarnessSecretManager } from "./security/secretStorage";

const URL_PATTERN = /https?:\/\/[^\s"'<>]+/i;
const ENV_NAME = /^[A-Za-z0-9_.-]{1,32}$/;

/** Test types the engine tags cases with (engine `TEST_TYPES`). */
export const TEST_TYPES = [
  "smoke",
  "sanity",
  "regression",
  "functional",
  "negative",
  "boundary",
  "ui",
  "accessibility",
] as const;

interface SuiteSummary {
  slug: string;
  module: string;
  start_url: string;
  allowed_domains: string[];
  environment: string;
  environments: Record<string, string>;
  total_cases: number;
  failed_count: number;
  required_secrets: string[];
  test_types: string[];
  testcases_md: string;
}

interface TargetChoice {
  environment: string;
  baseUrl?: string;
  url: string;
}

export class QAChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "qaHarness.chatView";
  private view?: vscode.WebviewView;
  private boundRpc?: RPCClient;
  private suites: SuiteSummary[] = [];
  private readonly history = new RunHistory(() => vscode.workspace.workspaceFolders?.[0]?.uri.fsPath);
  private historyTimer?: NodeJS.Timeout;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly engine: EngineClient,
    private readonly ai: AIService,
    private readonly identity: IdentityService,
    private readonly secrets: HarnessSecretManager
  ) {
    this.history.onDidChange(() => {
      if (this.historyTimer) return;
      this.historyTimer = setTimeout(() => {
        this.historyTimer = undefined;
        this.pushHistory();
      }, 300);
    });
    engine.onDidStart((rpc) => this.bindEngineEvents(rpc));
    engine.onDidExit((code) => {
      this.boundRpc = undefined;
      this.history.end("error");
      if (code !== 0 && code !== null) {
        this.say(
          `QA engine stopped (exit code ${code}). See the "QA Harness Engine" output channel.`
        );
      }
    });
    ai.onDidChange(() => void this.pushState());
    identity.onDidChange(() => void this.pushState());
  }

  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    webviewView.webview.options = { enableScripts: true, localResourceRoots: [this.extensionUri] };
    webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);
    webviewView.webview.onDidReceiveMessage((data) => void this.onMessage(data));
  }

  // ------------------------------------------------------------------ webview -> extension

  private async onMessage(data: Record<string, unknown>): Promise<void> {
    const command = String(data.command || "");
    if (command === "ready") {
      await this.pushState();
      this.pushHistory();
      await this.refreshSuites(true);
      return;
    }
    if (!vscode.workspace.isTrusted) {
      vscode.window.showErrorMessage("QA Harness operations are disabled in untrusted workspaces.");
      return;
    }
    try {
      switch (command) {
        case "userPrompt":
          await this.handlePrompt(String(data.text || ""));
          break;
        case "newSuite":
          await this.startSuite(data);
          break;
        case "confirmScope":
          await this.engine.request("run.scope.confirm", {
            scope: data.scope as Record<string, unknown>,
            approver: await this.identity.require(),
          });
          break;
        case "answerClarifications":
          await this.engine.request("run.clarifications.answer", {
            answers: data.answers as Record<string, unknown>,
            approver: await this.identity.require(),
          });
          break;
        case "reviseTestcases":
          await this.engine.request("run.testcases.revise", {
            comments: String(data.comments || ""),
            approver: await this.identity.require(),
          });
          break;
        case "approveTestcases":
          await this.engine.request("run.testcases.approve", {
            version: data.version,
            sha256_hash: data.sha256_hash,
            approver: await this.identity.require(),
          });
          break;
        case "retest":
          await this.retest(String(data.slug || ""), Boolean(data.failed_only));
          break;
        case "regression":
          await this.regression(String(data.tag || ""));
          break;
        case "refreshSuites":
          await this.refreshSuites(false);
          break;
        case "manageSecrets":
          await this.manageSecrets(String(data.slug || ""));
          break;
        case "updateSuite":
          await this.updateSuite(String(data.slug || ""));
          break;
        case "deleteSuite":
          await this.deleteSuite(String(data.slug || ""));
          break;
        case "dryRunDecide":
          await this.engine.request("run.dryrun.decide", {
            decision: String(data.decision || ""),
            approver: await this.identity.require(),
          });
          break;
        case "openReport":
          if (data.path) await vscode.env.openExternal(vscode.Uri.file(String(data.path)));
          break;
        case "openFile":
          if (data.path) {
            await vscode.window.showTextDocument(vscode.Uri.file(String(data.path)), {
              preview: true,
            });
          }
          break;
        case "cancelRun":
          await this.engine.cancel(await this.identity.current());
          break;
        case "signIn":
          await this.identity.chooseAccount();
          break;
        case "signOut":
          await this.identity.signOut();
          break;
        case "setupEngine":
          await vscode.commands.executeCommand("qaHarness.setupEngine");
          break;
        case "ai.save":
          await this.ai.saveSettings({
            provider: data.provider as ProviderId,
            model: String(data.model ?? ""),
            baseUrl: String(data.baseUrl ?? ""),
            azureApiVersion: String(data.azureApiVersion ?? ""),
            investigationModel: String(data.investigationModel ?? ""),
          });
          break;
        case "ai.costSave": {
          const cfg = vscode.workspace.getConfiguration("qaHarness.ai");
          const target = vscode.ConfigurationTarget.Global;
          const int = (v: unknown, fallback: number, max: number) => {
            const n = Math.floor(Number(v));
            return Number.isFinite(n) ? Math.max(0, Math.min(max, n)) : fallback;
          };
          await cfg.update("investigateFailures", data.investigate !== false, target);
          await cfg.update("reuseAnalyses", data.reuse !== false, target);
          await cfg.update("maxInvestigationsPerRun", int(data.perRun, 5, 100), target);
          await cfg.update("dailyInvestigationLimit", int(data.daily, 50, 100000), target);
          await this.pushState();
          this.post({ type: "notice", level: "info", text: "AI cost limits saved." });
          break;
        }
        case "ai.setKey":
          await this.promptApiKey();
          break;
        case "ai.clearKey":
          await this.ai.clearApiKey(this.ai.settings().provider);
          break;
        case "ai.models":
          this.post({ type: "ai.models", models: await this.ai.listModels() });
          break;
        case "ai.test":
          this.post({ type: "ai.testResult", ok: true, text: await this.ai.testConnection() });
          break;
        case "history.list":
          this.pushHistory();
          break;
        case "history.open": {
          const session = this.history.open(String(data.id || ""));
          if (!session) throw new Error("That run is no longer in the history.");
          this.post({ type: "history.session", session, live: session.id === this.history.activeId() });
          break;
        }
        case "history.delete":
          await this.deleteHistory(String(data.id || ""));
          break;
      }
    } catch (e) {
      const message = this.describe(e);
      if (command === "ai.test" || command === "ai.models") {
        this.post({ type: "ai.testResult", ok: false, text: message });
      } else {
        this.post({ type: "notice", level: "error", text: message });
      }
    }
  }

  // ------------------------------------------------------------------ suite design

  public focusNewSuite(): void {
    this.post({ type: "switchTab", tab: "suites", openForm: true });
  }

  public focusTab(tab: string): void {
    this.post({ type: "switchTab", tab });
  }

  private async handlePrompt(text: string): Promise<void> {
    const url = text.match(URL_PATTERN)?.[0];
    if (!url) {
      this.post({ type: "user", text });
      this.say(
        "Include the target URL to start a quick suite, or open the Suites tab and use " +
          "New Suite to enter a requirement with acceptance criteria."
      );
      return;
    }
    const host = new URL(url).hostname;
    const requirement = text.replace(url, "").trim();
    const status = await this.ai.status();
    const module = await vscode.window.showInputBox({
      title: "Suite (module) name",
      prompt: "Suites are stored per module so you can retest them later.",
      value: requirement && status.ready ? host : `${host} smoke`,
      ignoreFocusOut: true,
    });
    if (!module) return;
    await this.startSuite({
      module,
      url,
      domains: "",
      environment: "",
      requirement,
      criteria: "",
      useAi: status.ready && requirement.length > 0,
      prompt: text,
    });
  }

  /** Begin a history session for one execution, then run `start` (which calls the engine). */
  private async beginSession(
    kind: SessionKind,
    title: string,
    subtitle: string,
    start: () => Promise<unknown>,
    prompt?: string
  ): Promise<void> {
    const session = this.history.start(kind, title, subtitle);
    this.post({
      type: "session.start",
      session: { ...session, events: undefined },
    });
    if (prompt) this.post({ type: "user", text: prompt });
    try {
      await start();
    } catch (e) {
      this.history.record({ type: "notice", level: "error", text: this.describe(e) });
      this.history.end("error");
      throw e;
    }
  }

  private pushHistory(): void {
    this.post({ type: "history", sessions: this.history.list(), activeId: this.history.activeId() });
  }

  private async deleteHistory(id: string): Promise<void> {
    const session = this.history.list().find((s) => s.id === id);
    if (!session) return;
    if (session.status === "running" || session.status === "waiting") {
      throw new Error("Cancel the run before removing it from the history.");
    }
    const choice = await vscode.window.showWarningMessage(
      `Remove "${session.title}" from the run history?`,
      {
        modal: true,
        detail:
          "Only the panel transcript is removed. Reports, evidence, the audit trail, and the suite " +
          "itself stay in .qa-harness.",
      },
      "Remove"
    );
    if (choice !== "Remove") return;
    this.history.delete(id);
    this.post({ type: "history.deleted", id });
  }

  public dispose(): void {
    this.history.flush();
  }

  public async startSuite(data: Record<string, unknown>): Promise<void> {
    const url = String(data.url || "").trim();
    if (!URL_PATTERN.test(url)) {
      throw new Error("Enter a valid http(s) start URL.");
    }
    const status = await this.ai.status();
    const useAi = Boolean(data.useAi) && status.ready;
    if (data.useAi && !status.ready) {
      throw new Error(`AI provider not ready: ${status.detail}`);
    }
    const domains = String(data.domains || "")
      .split(/[\s,]+/)
      .map((d) => d.trim())
      .filter(Boolean);
    this.post({ type: "switchTab", tab: "assistant" });
    const module = String(data.module || "") || new URL(url).hostname;
    const exists = this.suites.some((s) => s.module.toLowerCase() === module.toLowerCase());
    await this.beginSession(
      exists ? "update" : "suite",
      module,
      `${new URL(url).hostname}${data.environment ? ` · ${data.environment}` : ""}`,
      async () => {
        this.say(
          `Starting suite **${module}** ` +
            (useAi ? `with ${status.providerLabel} (${status.model}).` : "using smoke design (no AI).")
        );
        await this.engine.request("run.start", {
          module: String(data.module || ""),
          start_url: url,
          allowed_domains: domains,
          environment: String(data.environment || ""),
          requirement_text: String(data.requirement || ""),
          acceptance_criteria: String(data.criteria || ""),
          design_mode: useAi ? "ai" : "smoke",
          ai_enabled: useAi,
          dry_run: data.dryRun !== false,
          approver: (await this.identity.current()) || "",
          ...this.engine.browserOptions(),
        });
      },
      data.prompt ? String(data.prompt) : undefined
    );
  }

  public async updateSuite(slug: string): Promise<void> {
    const suite = await this.engine.request<Record<string, unknown>>("suite.get", { slug });
    this.post({ type: "suiteForm", suite });
  }

  public async deleteSuite(slug: string): Promise<void> {
    const suite = this.suites.find((s) => s.slug === slug) || (await this.pickSuite("Suite to delete"));
    if (!suite) return;
    const choice = await vscode.window.showWarningMessage(
      `Delete suite "${suite.module}"?`,
      {
        modal: true,
        detail:
          `${suite.total_cases} approved case(s) and the run history move to ` +
          ".qa-harness/archive/suites/ (nothing is erased). Its stored secrets are removed " +
          "from the OS keychain.",
      },
      "Delete Suite"
    );
    if (choice !== "Delete Suite") return;
    await this.engine.request("suite.delete", { slug: suite.slug, approver: await this.identity.require() });
    for (const name of suite.required_secrets || []) {
      await this.secrets.deleteSuiteSecret(suite.slug, name);
    }
    vscode.window.showInformationMessage(`Suite "${suite.module}" was archived.`);
    await this.refreshSuites(false);
  }

  /** Default, saved, or new environment for re-running a stored suite. */
  private async pickTarget(suite: SuiteSummary): Promise<TargetChoice | undefined> {
    type Item = vscode.QuickPickItem & { choice?: TargetChoice };
    const items: Item[] = [
      {
        label: suite.environment,
        description: "default",
        detail: suite.start_url,
        choice: { environment: suite.environment, url: suite.start_url },
      },
      ...Object.entries(suite.environments || {}).map(([name, url]) => ({
        label: name,
        detail: url,
        choice: { environment: name, url },
      })),
      { label: "$(add) Another environment ...", detail: "Give it a name and its start URL" },
    ];
    const pick = await vscode.window.showQuickPick(items, {
      title: `Environment for "${suite.module}"`,
      placeHolder: "Where should the approved suite run?",
    });
    if (!pick) return undefined;
    if (pick.choice) return pick.choice;

    const environment = await vscode.window.showInputBox({
      title: "Environment name",
      prompt: "e.g. qa, uat, preprod",
      validateInput: (v) =>
        ENV_NAME.test(v.trim()) ? undefined : "1-32 letters, digits, '.', '_' or '-'",
    });
    if (!environment) return undefined;
    const sample = new URL(suite.start_url);
    const baseUrl = await vscode.window.showInputBox({
      title: `Start URL on ${environment.trim()}`,
      prompt: `Same page as ${suite.start_url}, on the ${environment.trim()} host.`,
      value: `${sample.protocol}//${sample.host}${sample.pathname}`,
      validateInput: (v) => (/^https?:\/\/[^\s]+$/i.test(v.trim()) ? undefined : "Enter an http(s) URL"),
    });
    if (!baseUrl) return undefined;
    return { environment: environment.trim(), baseUrl: baseUrl.trim(), url: baseUrl.trim() };
  }

  // ------------------------------------------------------------------ library

  public async refreshSuites(silent: boolean): Promise<SuiteSummary[]> {
    if (!this.engine.isSetUp()) {
      this.post({ type: "suites", suites: [], engineReady: false });
      return [];
    }
    try {
      const result = await this.engine.request<{ suites: SuiteSummary[] }>("suites.list");
      this.suites = result.suites || [];
      this.post({ type: "suites", suites: this.suites, engineReady: true });
    } catch (e) {
      if (!silent) throw e;
    }
    return this.suites;
  }

  public async pickSuite(placeHolder: string): Promise<SuiteSummary | undefined> {
    const suites = await this.refreshSuites(false);
    if (!suites.length) {
      vscode.window.showInformationMessage("No suites yet. Create one with QA Harness: New Suite.");
      return undefined;
    }
    const pick = await vscode.window.showQuickPick(
      suites.map((s) => ({
        label: s.module,
        description: `${s.total_cases} case(s), ${s.failed_count} failing`,
        detail: s.start_url,
        suite: s,
      })),
      { placeHolder }
    );
    return pick?.suite;
  }

  public async retest(slug: string, failedOnly: boolean): Promise<void> {
    const suite = this.suites.find((s) => s.slug === slug) || (await this.pickSuite("Suite to retest"));
    if (!suite) return;
    const scope = failedOnly ? `${suite.failed_count} failed case(s)` : `all ${suite.total_cases} case(s)`;
    const target = await this.pickTarget(suite);
    if (!target) return;
    const host = new URL(target.url).hostname;
    const originalHost = new URL(suite.start_url).hostname;
    const domains = suite.allowed_domains.map((d) => (d === originalHost ? host : d));
    const choice = await vscode.window.showWarningMessage(
      `Retest ${scope} of "${suite.module}" on ${target.environment}?`,
      {
        modal: true,
        detail:
          `Target: ${target.url}\nAllowed domains: ${[...new Set([host, ...domains])].join(", ")}\n\n` +
          "By continuing you confirm you are authorized to test this target.",
      },
      "Run Retest"
    );
    if (choice !== "Run Retest") return;
    const approver = await this.identity.require();
    const aiReady = (await this.ai.status()).ready;
    this.post({ type: "switchTab", tab: "assistant" });
    await this.beginSession(
      failedOnly ? "retest-failed" : "retest",
      suite.module,
      `${scope} · ${target.environment}`,
      () =>
        this.engine.request("suite.retest", {
          slug: suite.slug,
          failed_only: failedOnly,
          environment: target.environment,
          base_url: target.baseUrl,
          authorized_attestation: true,
          approver,
          ai_enabled: aiReady,
          ...this.engine.browserOptions(),
        })
    );
  }

  public async regression(tag: string): Promise<void> {
    const suites = await this.refreshSuites(false);
    const matching = tag ? suites.filter((s) => s.test_types.includes(tag)) : suites;
    if (!matching.length) {
      throw new Error(tag ? `No suites contain '${tag}' cases.` : "No suites yet. Create one first.");
    }
    const names = new Map<string, string[]>();
    for (const s of matching) {
      for (const env of [s.environment, ...Object.keys(s.environments || {})]) {
        names.set(env, [...(names.get(env) || []), s.module]);
      }
    }
    const envPick = await vscode.window.showQuickPick(
      [
        { label: "Default environments", description: "each suite on its own default", env: "" },
        ...[...names.entries()].map(([env, modules]) => ({
          label: env,
          description:
            modules.length === matching.length
              ? "all suites"
              : `${modules.length} of ${matching.length} suites (others are reported as not run)`,
          env,
        })),
      ],
      { title: "Regression environment", placeHolder: "Where should the suites run?" }
    );
    if (!envPick) return;
    const environment = envPick.env;
    const targets = matching.map((s) => {
      const url = !environment ? s.start_url : environment === s.environment ? s.start_url : s.environments?.[environment];
      return `${s.module}: ${url || "no URL for this environment"}`;
    });
    const choice = await vscode.window.showWarningMessage(
      `Run regression across ${matching.length} suite(s)${tag ? ` (only '${tag}' cases)` : ""}` +
        `${environment ? ` on ${environment}` : ""}?`,
      {
        modal: true,
        detail:
          `${targets.join("\n")}\n\n` +
          "By continuing you confirm you are authorized to test these targets.",
      },
      "Run Regression"
    );
    if (choice !== "Run Regression") return;
    const approver = await this.identity.require();
    const aiReady = (await this.ai.status()).ready;
    this.post({ type: "switchTab", tab: "assistant" });
    await this.beginSession(
      "regression",
      `Regression${tag ? ` · ${tag}` : ""}`,
      `${matching.length} suite(s)${environment ? ` · ${environment}` : " · default environments"}`,
      () =>
        this.engine.request("regression.run", {
          tag,
          environment: environment || undefined,
          authorized_attestation: true,
          approver,
          ai_enabled: aiReady,
          ...this.engine.browserOptions(),
        })
    );
  }

  public async manageSecrets(slug: string): Promise<void> {
    const suite =
      this.suites.find((s) => s.slug === slug) || (await this.pickSuite("Suite whose secrets to set"));
    if (!suite) return;
    const known = suite.required_secrets || [];
    const pick = await vscode.window.showQuickPick(
      [
        ...known.map((name) => ({ label: name, description: "used by this suite" })),
        { label: "$(add) Other secret name ..." , description: "" },
      ],
      { placeHolder: `Secrets for ${suite.module} (stored in the OS keychain)` }
    );
    if (!pick) return;
    let name = pick.label;
    if (name.startsWith("$(add)")) {
      name =
        (await vscode.window.showInputBox({
          prompt: "Secret name (UPPER_SNAKE_CASE, referenced as {{secret.NAME}})",
          validateInput: (v) => (/^[A-Za-z0-9_]+$/.test(v) ? undefined : "Letters, digits, _"),
        })) || "";
      if (!name) return;
    }
    const value = await vscode.window.showInputBox({
      prompt: `Value for ${name.toUpperCase()} (${suite.module})`,
      password: true,
      ignoreFocusOut: true,
    });
    if (value === undefined) return;
    if (value === "") {
      await this.secrets.deleteSuiteSecret(suite.slug, name);
      vscode.window.showInformationMessage(`Removed secret ${name.toUpperCase()}.`);
    } else {
      await this.secrets.setSuiteSecret(suite.slug, name, value);
      vscode.window.showInformationMessage(`Stored ${name.toUpperCase()} in the OS keychain.`);
    }
  }

  /** Engine request `secrets.resolve`: return stored values, asking for missing ones. */
  public async resolveSecrets(params: Record<string, unknown>): Promise<unknown> {
    const slug = String(params.suite || "");
    const module = String(params.module || slug);
    const values: Record<string, string> = {};
    for (const raw of (params.names as string[]) || []) {
      const name = String(raw).toUpperCase();
      let value = await this.secrets.getSuiteSecret(slug, name);
      if (!value) {
        value = await vscode.window.showInputBox({
          title: `Secret needed by suite "${module}"`,
          prompt: `Enter ${name}. It is stored in the OS keychain, never in files or logs.`,
          password: true,
          ignoreFocusOut: true,
        });
        if (value) await this.secrets.setSuiteSecret(slug, name, value);
      }
      if (value) values[name] = value;
    }
    return { values };
  }

  // ------------------------------------------------------------------ AI provider

  private async promptApiKey(): Promise<void> {
    const s = this.ai.settings();
    const info = PROVIDERS.find((p) => p.id === s.provider);
    if (!info?.needsKey) return;
    const key = await vscode.window.showInputBox({
      title: `${info.label} API key`,
      prompt: `${info.keyHelp} Stored in the OS keychain only.`,
      password: true,
      ignoreFocusOut: true,
    });
    if (key) await this.ai.setApiKey(s.provider, key.trim());
  }

  public async pushState(): Promise<void> {
    this.post({
      type: "state",
      identity: (await this.identity.current()) || null,
      ai: await this.ai.status(),
      settings: this.ai.settings(),
      providers: PROVIDERS,
      engineReady: this.engine.isSetUp(),
      cost: this.costState(),
    });
  }

  private costState(): Record<string, unknown> {
    const cfg = vscode.workspace.getConfiguration("qaHarness.ai");
    let today: Record<string, number> = {};
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (root) {
      try {
        const file = path.join(root, ".qa-harness", "ai-usage.json");
        const days = JSON.parse(fs.readFileSync(file, "utf-8")).days || {};
        today = days[new Date().toISOString().slice(0, 10)] || {};
      } catch {
        today = {};
      }
    }
    return {
      investigate: cfg.get<boolean>("investigateFailures", true),
      reuse: cfg.get<boolean>("reuseAnalyses", true),
      perRun: cfg.get<number>("maxInvestigationsPerRun", 5),
      daily: cfg.get<number>("dailyInvestigationLimit", 50),
      today: { design: today.design || 0, investigation: today.investigation || 0 },
    };
  }

  // ------------------------------------------------------------------ engine -> webview

  private bindEngineEvents(rpc: RPCClient): void {
    if (this.boundRpc === rpc) return;
    this.boundRpc = rpc;
    rpc.on("notify:stage.update", (params: Record<string, unknown>) => {
      this.post({ type: "stage.update", ...params });
    });
    rpc.on("notify:message.stream", (params: Record<string, unknown>) => {
      this.post({ type: "message.stream", ...params });
    });
    rpc.on("notify:activity", (params: Record<string, unknown>) => {
      this.post({ type: "activity", ...params });
    });
    rpc.on("notify:card.show", (params: Record<string, unknown>) => {
      this.post({ type: "card.show", ...params });
      if (params.card_type === "report_card" || params.card_type === "regression_card") {
        void this.refreshSuites(true);
        void this.pushState();
      }
    });
  }

  private say(text: string): void {
    this.post({ type: "message.stream", chunk: text, complete: true });
  }

  private post(message: Record<string, unknown>): void {
    if (message.type !== "notice" || message.level === "error") this.history.record(message);
    void this.view?.webview.postMessage(message);
  }

  private describe(e: unknown): string {
    const raw =
      e && typeof e === "object" && "message" in e
        ? String((e as { message: unknown }).message)
        : String(e);
    return raw.replace(/^Internal error executing '[^']+': /, "");
  }

  private getHtmlForWebview(webview: vscode.Webview): string {
    const { nonce, metaHtml } = generateWebviewCSP(webview);
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "webview", "main.js"));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "webview", "styles.css"));

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  ${metaHtml}
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="${styleUri}" rel="stylesheet" nonce="${nonce}">
  <title>QA Harness</title>
</head>
<body>
<div class="app" id="app">
  <aside class="history" id="history" aria-label="Run history">
    <div class="history-head">
      <span class="history-title"><span class="i" data-icon="history"></span>Run history</span>
      <button class="icon-btn" id="btnHistoryClose" title="Close history"><span class="i" data-icon="x"></span></button>
    </div>
    <div class="history-search">
      <span class="i" data-icon="search"></span>
      <input id="historySearch" type="search" placeholder="Search runs" aria-label="Search runs" />
    </div>
    <div class="history-filters" id="historyFilters" role="tablist">
      <button class="filter active" data-filter="all">All</button>
      <button class="filter" data-filter="suite">Suites</button>
      <button class="filter" data-filter="retest">Retests</button>
      <button class="filter" data-filter="regression">Regression</button>
    </div>
    <div class="history-list" id="historyList"></div>
  </aside>
  <div class="scrim" id="scrim"></div>

  <main class="main">
    <header class="top-bar">
      <button class="icon-btn" id="btnHistory" title="Run history"><span class="i" data-icon="panel"></span></button>
      <div class="brand"><span class="brand-mark"><span class="i" data-icon="beaker"></span></span><span class="brand-name">QA Harness</span></div>
      <div class="status-chips">
        <button class="chip" id="chipAi" title="AI provider"><span class="dot"></span><span class="chip-text">AI</span></button>
        <button class="chip" id="chipUser" title="Approver identity"><span class="i" data-icon="user"></span><span class="chip-text">Sign in</span></button>
      </div>
    </header>

    <nav class="tabs" role="tablist">
      <button class="tab active" data-tab="assistant" role="tab"><span class="i" data-icon="spark"></span>Assistant</button>
      <button class="tab" data-tab="suites" role="tab"><span class="i" data-icon="layers"></span>Suites</button>
      <button class="tab" data-tab="ai" role="tab"><span class="i" data-icon="cpu"></span>AI Provider</button>
      <span class="tab-indicator" id="tabIndicator"></span>
    </nav>

    <div class="engine-banner" id="engineBanner" hidden>
      <span class="i" data-icon="alert"></span>
      <span>The QA engine is not set up yet.</span>
      <button class="btn-primary" id="btnSetup">Set Up Engine</button>
    </div>

    <section class="panel" id="panel-assistant">
      <div class="run-header" id="runHeader" data-state="idle">
        <span class="run-dot" id="runDot"></span>
        <div class="run-info">
          <div class="run-title" id="runTitle">Ready</div>
          <div class="run-desc" id="stageDesc">Awaiting instructions</div>
        </div>
        <span class="stage-badge" id="stageBadge">READY</span>
        <button class="btn-cancel" id="btnCancel" title="Cancel the current run"><span class="i" data-icon="stop"></span>Cancel</button>
      </div>
      <div class="stage-track" id="stageTrack" aria-hidden="true"></div>
      <div class="replay-banner" id="replayBanner" hidden>
        <span class="i" data-icon="history"></span>
        <span id="replayText">Viewing a past run (read-only)</span>
        <button class="btn-secondary btn-sm" id="btnBackLive">Back to live</button>
      </div>
      <div class="chat-container" id="chatContainer">
        <div class="welcome" id="welcome">
          <div class="welcome-orb"><span class="i" data-icon="beaker"></span></div>
          <h2>AI QA Testing Harness</h2>
          <p>Design suites from requirements, approve them at every gate, and follow each agent
            step live: thinking, browsing, running, and investigating.</p>
          <div class="quick-actions">
            <button class="quick" data-quick="newSuite"><span class="i" data-icon="plus"></span><span><strong>New suite</strong><small>Requirement + acceptance criteria</small></span></button>
            <button class="quick" data-quick="suites"><span class="i" data-icon="refresh"></span><span><strong>Retest a module</strong><small>Run an approved suite again</small></span></button>
            <button class="quick" data-quick="regression"><span class="i" data-icon="layers"></span><span><strong>Regression</strong><small>Every stored suite</small></span></button>
            <button class="quick" data-quick="history"><span class="i" data-icon="history"></span><span><strong>History</strong><small>Replay any past run</small></span></button>
          </div>
          <p class="hint">Or paste your application URL below for a quick suite.</p>
        </div>
      </div>
      <div class="chat-container replay" id="replayContainer" hidden></div>
      <div class="input-dock" id="inputDock">
        <div class="composer">
          <textarea id="txtPrompt" rows="1" placeholder="Paste your app URL, optionally with what to test ..."></textarea>
          <button class="send-btn" id="btnSend" title="Send (Enter)"><span class="i" data-icon="send"></span></button>
        </div>
        <div class="composer-hint">Enter to send &middot; Shift+Enter for a new line</div>
      </div>
    </section>

    <section class="panel" id="panel-suites" hidden>
    <div class="panel-scroll">
      <div class="toolbar">
        <button class="btn-primary" id="btnNewSuite"><span class="i" data-icon="plus"></span>New Suite</button>
        <button class="btn-secondary" id="btnRefresh"><span class="i" data-icon="refresh"></span>Refresh</button>
      </div>

      <form class="decision-card form-card" id="suiteForm" hidden>
        <h3 id="formTitle">New test suite</h3>
        <p class="muted small" id="formNote" hidden>The AI updates the approved cases to the edited
          requirement: unchanged cases keep their IDs. You review and approve the new version.</p>
        <label class="card-label" for="fModule">Module / suite name</label>
        <input id="fModule" required placeholder="e.g. Login, Checkout, User profile" />
        <label class="card-label" for="fUrl">Start URL</label>
        <input id="fUrl" required placeholder="https://your-application/page" />
        <label class="card-label" for="fDomains">Extra allowed domains (optional)</label>
        <input id="fDomains" placeholder="auth.your-application, cdn.your-application" />
        <label class="card-label" for="fEnv">Environment</label>
        <input id="fEnv" list="envSuggestions" value="test" placeholder="e.g. test, staging, uat" />
        <datalist id="envSuggestions">
          <option value="dev"></option>
          <option value="test"></option>
          <option value="qa"></option>
          <option value="staging"></option>
          <option value="uat"></option>
          <option value="production"></option>
        </datalist>
        <label class="card-label" for="fReq">Requirement</label>
        <textarea id="fReq" rows="4" placeholder="Describe the feature or user story ..."></textarea>
        <label class="card-label" for="fAc">Acceptance criteria (one per line)</label>
        <textarea id="fAc" rows="5" placeholder="Given ... when ... then ..."></textarea>
        <label class="inline-check"><input type="checkbox" id="fAi" checked /> Design with AI provider</label>
        <label class="inline-check"><input type="checkbox" id="fDryRun" checked /> Dry run every
          step once before executing (recommended)</label>
        <div class="card-error" id="formError" hidden></div>
        <div class="action-buttons">
          <button class="btn-primary" type="submit" id="btnSubmitSuite">Create &amp; Design</button>
          <button class="btn-secondary" type="button" id="btnCancelForm">Close</button>
        </div>
      </form>

      <div class="decision-card" data-accent="run">
        <h3><span class="card-icon"><span class="i" data-icon="layers"></span></span>Regression</h3>
        <p class="muted">Run every stored suite, optionally limited to one test type. You choose
          the environment when you start it.</p>
        <div class="row">
          <select id="regTag">
            <option value="">All cases</option>
            ${TEST_TYPES.map((t) => `<option value="${t}">${t} only</option>`).join("")}
          </select>
          <button class="btn-primary" id="btnRegression">Run Regression</button>
        </div>
      </div>

      <div id="suiteList"></div>
    </div>
  </section>

  <section class="panel" id="panel-ai" hidden>
    <div class="panel-scroll">
      <div class="decision-card" data-accent="think">
        <h3><span class="card-icon"><span class="i" data-icon="cpu"></span></span>AI provider</h3>
        <p class="muted" id="aiHelp"></p>
        <label class="card-label" for="aiProvider">Provider</label>
        <select id="aiProvider"></select>
        <div id="aiKeyRow">
          <label class="card-label">API key</label>
          <div class="row">
            <span class="chip" id="aiKeyState">not set</span>
            <button class="btn-secondary" id="btnSetKey" type="button">Set key</button>
            <button class="btn-secondary" id="btnClearKey" type="button">Remove</button>
          </div>
        </div>
        <div id="aiBaseRow">
          <label class="card-label" for="aiBaseUrl">Endpoint URL</label>
          <input id="aiBaseUrl" placeholder="https://..." />
        </div>
        <div id="aiAzureRow">
          <label class="card-label" for="aiAzureVersion">Azure API version</label>
          <input id="aiAzureVersion" />
        </div>
        <label class="card-label" for="aiModel">Model</label>
        <div class="row">
          <input id="aiModel" list="aiModelList" placeholder="Load models or type a model / deployment name" />
          <datalist id="aiModelList"></datalist>
          <button class="btn-secondary" id="btnLoadModels" type="button">Load models</button>
        </div>
        <div id="aiInvestigationModelRow">
          <label class="card-label" for="aiInvestigationModel">Failure-analysis model (optional)</label>
          <input id="aiInvestigationModel" list="aiModelList"
            placeholder="Empty = same model. Pick a cheaper one to save quota." />
        </div>
        <div class="action-buttons">
          <button class="btn-primary" id="btnSaveAi" type="button">Save</button>
          <button class="btn-secondary" id="btnTestAi" type="button">Test connection</button>
        </div>
        <div class="ai-status" id="aiStatus"></div>
      </div>

      <div class="decision-card" data-accent="check">
        <h3><span class="card-icon"><span class="i" data-icon="gauge"></span></span>AI cost controls</h3>
        <p class="muted small">Designing, revising, and repairing suites always uses AI (never
          limited). Limits apply only to analyzing failed tests during runs; when a limit is reached,
          failures are classified by rules instead. Pass/fail results and defect sign-off are not
          affected.</p>
        <label class="inline-check"><input type="checkbox" id="costInvestigate" /> Analyze failed
          tests with AI</label>
        <label class="inline-check"><input type="checkbox" id="costReuse" /> Reuse an earlier analysis
          when the same test fails the same way (same approved suite and target, 7 days)</label>
        <div class="row">
          <label class="card-label" for="costPerRun">Max AI analyses per run</label>
          <input id="costPerRun" type="number" min="0" max="100" />
        </div>
        <div class="row">
          <label class="card-label" for="costDaily">Max AI analyses per day</label>
          <input id="costDaily" type="number" min="0" max="100000" />
        </div>
        <div class="action-buttons">
          <button class="btn-primary" id="btnSaveCost" type="button">Save limits</button>
        </div>
        <div class="ai-status" id="costUsage"></div>
      </div>

      <div class="decision-card" data-accent="save">
        <h3><span class="card-icon"><span class="i" data-icon="user"></span></span>GitHub account (approver)</h3>
        <p class="muted">Scope confirmations, test case approvals, defect sign-offs, retests, and
          regressions are recorded under this account.</p>
        <div class="row">
          <span class="chip" id="acctState">Not signed in</span>
        </div>
        <div class="action-buttons">
          <button class="btn-primary" id="btnAcctSwitch" type="button">Sign in</button>
          <button class="btn-secondary" id="btnAcctSignOut" type="button">Sign out</button>
        </div>
        <p class="muted small">GitHub Copilot uses the account signed into the GitHub Copilot
          extension, which can differ from the approver. Change it from the VS Code Accounts menu
          (person icon, bottom left).</p>
      </div>
    </div>
  </section>
  </main>
</div>
<div class="toast-host" id="toastHost" aria-live="polite"></div>

  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}
