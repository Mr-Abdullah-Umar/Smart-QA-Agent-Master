/**
 * Extension entry point for the AI QA Testing Harness.
 */

import * as vscode from "vscode";
import { EngineClient } from "./engineClient";
import { QAChatViewProvider } from "./chatProvider";
import { HarnessSecretManager } from "./security/secretStorage";

let engineClient: EngineClient | null = null;

export function activate(context: vscode.ExtensionContext): void {
  const secretManager = new HarnessSecretManager(context.secrets);
  engineClient = new EngineClient(context);

  const chatProvider = new QAChatViewProvider(context.extensionUri, engineClient);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      QAChatViewProvider.viewType,
      chatProvider
    )
  );

  // Command: Start Run
  context.subscriptions.push(
    vscode.commands.registerCommand("qaHarness.startRun", async () => {
      if (!vscode.workspace.isTrusted) {
        vscode.window.showErrorMessage("Cannot run QA Harness in an untrusted workspace.");
        return;
      }

      const startUrl = await vscode.window.showInputBox({
        prompt: "Enter Target Application URL",
        placeHolder: "https://staging.example.com",
      });

      if (!startUrl) {
        return;
      }

      const runId = `run-${Date.now()}`;
      try {
        await engineClient?.startRun({
          runId,
          startUrl,
          allowedDomains: [new URL(startUrl).hostname],
        });
        chatProvider.bindEngineEvents();
        vscode.window.showInformationMessage(`QA Run initialized: ${runId}`);
      } catch (e) {
        vscode.window.showErrorMessage(`Failed to start QA run: ${e}`);
      }
    })
  );

  // Command: Cancel Run
  context.subscriptions.push(
    vscode.commands.registerCommand("qaHarness.cancelRun", async () => {
      await engineClient?.cancel();
      vscode.window.showInformationMessage("QA Run cancelled.");
    })
  );

  // Command: Store Credentials (SecretStorage)
  context.subscriptions.push(
    vscode.commands.registerCommand("qaHarness.setCredentials", async () => {
      const key = await vscode.window.showInputBox({
        prompt: "Enter a reference name for the test credential",
        placeHolder: "staging-admin",
      });
      if (!key) return;

      const secret = await vscode.window.showInputBox({
        prompt: "Enter secret value (password / API token)",
        password: true,
      });
      if (!secret) return;

      const ref = await secretManager.storeSecret(key, secret);
      vscode.window.showInformationMessage(
        `Stored credential securely in OS keychain. Use reference '${ref}' in scope configs.`
      );
    })
  );
}

export function deactivate(): void {
  if (engineClient) {
    engineClient.terminate();
    engineClient = null;
  }
}

