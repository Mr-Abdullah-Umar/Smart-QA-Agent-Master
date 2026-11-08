/**
 * Extension entry point for the AI QA Testing Harness.
 */

import * as vscode from "vscode";
import { AIService, ChatMessage } from "./ai/aiService";
import { QAChatViewProvider, TEST_TYPES } from "./chatProvider";
import { EngineClient } from "./engineClient";
import { IdentityService } from "./identity";
import { HarnessSecretManager } from "./security/secretStorage";

let engineClient: EngineClient | null = null;

export function activate(context: vscode.ExtensionContext): void {
  const secrets = new HarnessSecretManager(context.secrets);
  const ai = new AIService(secrets);
  const identity = new IdentityService(context);
  engineClient = new EngineClient(context);
  const engine = engineClient;
  const panel = new QAChatViewProvider(context.extensionUri, engine, ai, identity, secrets);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(QAChatViewProvider.viewType, panel, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  engine.handleRequest("llm.chat", async (params) => {
    const messages = (params.messages as ChatMessage[]) || [];
    const temperature = typeof params.temperature === "number" ? params.temperature : 0.2;
    return ai.chat(messages, temperature);
  });
  engine.handleRequest("secrets.resolve", (params) => panel.resolveSecrets(params));

  const requireTrust = (): boolean => {
    if (!vscode.workspace.isTrusted) {
      vscode.window.showErrorMessage("QA Harness is disabled in untrusted workspaces.");
      return false;
    }
    return true;
  };

  const reveal = async (): Promise<void> => {
    await vscode.commands.executeCommand(`${QAChatViewProvider.viewType}.focus`);
  };

  const guarded =
    (fn: () => Promise<void>) =>
    async (): Promise<void> => {
      if (!requireTrust()) return;
      try {
        await fn();
      } catch (e) {
        const msg = e && typeof e === "object" && "message" in e ? String(e.message) : String(e);
        vscode.window.showErrorMessage(msg.replace(/^Internal error executing '[^']+': /, ""));
      }
    };

  const register = (id: string, fn: () => Promise<void>): void => {
    context.subscriptions.push(vscode.commands.registerCommand(id, guarded(fn)));
  };

  register("qaHarness.newSuite", async () => {
    await reveal();
    panel.focusNewSuite();
  });
  register("qaHarness.startRun", async () => {
    await reveal();
    panel.focusNewSuite();
  });
  register("qaHarness.retestModule", async () => {
    const suite = await panel.pickSuite("Suite (module) to retest");
    if (!suite) return;
    const mode = await vscode.window.showQuickPick(
      [
        { label: "All cases", failedOnly: false },
        { label: "Only failed cases", failedOnly: true },
      ],
      { placeHolder: `Retest ${suite.module}` }
    );
    if (!mode) return;
    await reveal();
    await panel.retest(suite.slug, mode.failedOnly);
  });
  register("qaHarness.updateSuite", async () => {
    const suite = await panel.pickSuite("Suite to update");
    if (!suite) return;
    await reveal();
    await panel.updateSuite(suite.slug);
  });
  register("qaHarness.deleteSuite", async () => {
    const suite = await panel.pickSuite("Suite to delete");
    if (suite) await panel.deleteSuite(suite.slug);
  });
  register("qaHarness.runRegression", async () => {
    const pick = await vscode.window.showQuickPick(
      ["", ...TEST_TYPES].map((tag) => ({
        label: tag ? `Only '${tag}' cases` : "All cases of all suites",
        tag,
      })),
      { placeHolder: "Regression scope" }
    );
    if (!pick) return;
    await reveal();
    await panel.regression(pick.tag);
  });
  register("qaHarness.configureAi", async () => {
    await reveal();
    panel.focusTab("ai");
  });
  register("qaHarness.setupEngine", async () => {
    await engine.setUp();
    vscode.window.showInformationMessage("QA Harness engine is ready.");
    await panel.pushState();
    await panel.refreshSuites(true);
  });
  register("qaHarness.signIn", async () => {
    const name = await identity.chooseAccount();
    if (name) vscode.window.showInformationMessage(`QA gates will be approved as ${name}.`);
  });
  register("qaHarness.signOut", async () => {
    await identity.signOut();
  });
  register("qaHarness.setCredentials", async () => {
    await panel.manageSecrets("");
  });
  register("qaHarness.cancelRun", async () => {
    await engine.cancel(await identity.current());
    vscode.window.showInformationMessage("QA run cancelled.");
  });

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("qaHarness")) void panel.pushState();
    })
  );
}

export function deactivate(): void {
  if (engineClient) {
    engineClient.terminate();
    engineClient = null;
  }
}
