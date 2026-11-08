/**
 * WebviewViewProvider for the QA Assistant Chat Panel in VS Code.
 * Enforces strict Content Security Policy (CSP nonces) and mediates
 * user actions between the chat interface and the Python Engine.
 */

import * as vscode from "vscode";
import { EngineClient } from "./engineClient";
import { generateWebviewCSP } from "./security/csp";
import { ScopePayload } from "./rpc/protocol";

export class QAChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "qaHarness.chatView";
  private _view?: vscode.WebviewView;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly engineClient: EngineClient
  ) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);

    // Forward messages from Webview to EngineClient
    webviewView.webview.onDidReceiveMessage(async (data) => {
      // Check Workspace Trust before executing actions (T12)
      if (!vscode.workspace.isTrusted) {
        vscode.window.showErrorMessage(
          "QA Harness operations are disabled in Untrusted Workspaces."
        );
        return;
      }

      switch (data.command) {
        case "userPrompt": {
          const runId = `run-${Date.now()}`;
          try {
            await this.engineClient.startRun({
              runId,
              requirementText: data.text,
              startUrl: "https://staging.example.com",
              allowedDomains: ["staging.example.com"],
            });
            this.bindEngineEvents();
          } catch (e) {
            vscode.window.showErrorMessage(`Failed to start QA run: ${e}`);
          }
          break;
        }

        case "confirmScope": {
          try {
            const scope = data.scope as ScopePayload;
            await this.engineClient.confirmScope(scope);
          } catch (e) {
            vscode.window.showErrorMessage(`Failed to confirm scope: ${e}`);
          }
          break;
        }

        case "approveTestcases": {
          try {
            const version = data.version || 1;
            const hash = data.sha256_hash || "";
            await this.engineClient.approveTestcases(version, "engineer", hash);
          } catch (e) {
            vscode.window.showErrorMessage(`Failed to approve test cases: ${e}`);
          }
          break;
        }

        case "cancelRun": {
          await this.engineClient.cancel();
          break;
        }
      }
    });
  }

  public bindEngineEvents(): void {
    if (!this._view || !this.engineClient.isRunning) {
      return;
    }

    const rpc = this.engineClient.rpc;

    rpc.on("notify:stage.update", (params: Record<string, unknown>) => {
      this._view?.webview.postMessage({ type: "stage.update", ...params });
    });

    rpc.on("notify:message.stream", (params: Record<string, unknown>) => {
      this._view?.webview.postMessage({ type: "message.stream", ...params });
    });

    rpc.on("notify:card.show", (params: Record<string, unknown>) => {
      this._view?.webview.postMessage({ type: "card.show", ...params });
    });
  }

  private getHtmlForWebview(webview: vscode.Webview): string {
    const { nonce, metaHtml } = generateWebviewCSP(webview);

    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "webview", "main.js")
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "webview", "styles.css")
    );

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  ${metaHtml}
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="${styleUri}" rel="stylesheet" nonce="${nonce}">
  <title>QA Assistant</title>
</head>
<body>
  <div class="timeline-bar">
    <div>
      <span class="stage-badge" id="stageBadge">READY</span>
      <span style="font-size: 11px; margin-left: 6px; color: var(--text-muted);" id="stageDesc">Awaiting instructions</span>
    </div>
    <button class="btn-cancel" id="btnCancel">Cancel Run</button>
  </div>

  <div class="chat-container" id="chatContainer">
    <div class="message-bubble assistant">
      👋 Welcome to the <strong>AI QA Testing Harness</strong>.<br/>
      Describe your testing requirements and target URL below to begin.
    </div>
  </div>

  <div class="input-dock">
    <textarea id="txtPrompt" placeholder="Describe requirement or test goals..."></textarea>
    <button class="btn-primary" id="btnSend">Send</button>
  </div>

  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}

