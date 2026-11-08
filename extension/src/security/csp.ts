/**
 * Content Security Policy (CSP) generator for VS Code Webview panels.
 * Enforces T11 controls: prevents active script injection from untrusted web content.
 */

import * as crypto from "crypto";
import * as vscode from "vscode";

export interface CSPContext {
  nonce: string;
  metaHtml: string;
}

export function generateWebviewCSP(webview: vscode.Webview): CSPContext {
  // Generate cryptographically secure 128-bit random nonce
  const nonce = crypto.randomBytes(16).toString("hex");

  // Strict CSP:
  // - default-src 'none' (blocks all unexpected resource loads)
  // - script-src 'nonce-<random>' (only scripts matching nonce can execute)
  // - style-src webview.cspSource 'nonce-<random>' (local extension styles only)
  // - img-src webview.cspSource data: (local assets and data URLs)
  // - font-src webview.cspSource
  const csp = [
    "default-src 'none'",
    `script-src 'nonce-${nonce}'`,
    `style-src ${webview.cspSource} 'nonce-${nonce}'`,
    `img-src ${webview.cspSource} data:`,
    `font-src ${webview.cspSource}`,
  ].join("; ");

  const metaHtml = `<meta http-equiv="Content-Security-Policy" content="${csp};">`;

  return { nonce, metaHtml };
}

/**
 * Escapes HTML characters to prevent XSS injection into webview DOM.
 */
export function escapeHtml(unsafeText: string): string {
  if (!unsafeText) {
    return "";
  }
  return unsafeText
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

