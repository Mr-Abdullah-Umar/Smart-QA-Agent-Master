/**
 * Secret management integration using VS Code SecretStorage (OS Keychain).
 * Enforces T6 controls: real credentials never leak into prompts, logs, or workspace files.
 */

import * as vscode from "vscode";

export class HarnessSecretManager {
  private static readonly KEY_PREFIX = "qa-harness:secrets:";

  constructor(private readonly secrets: vscode.SecretStorage) {}

  public async storeSecret(key: string, secretValue: string): Promise<string> {
    const internalKey = `${HarnessSecretManager.KEY_PREFIX}${key}`;
    await this.secrets.store(internalKey, secretValue);
    // Return the safe URI reference that the user/model can use as a placeholder
    return `secret://qa-harness/${key}`;
  }

  public async getSecret(key: string): Promise<string | undefined> {
    const internalKey = `${HarnessSecretManager.KEY_PREFIX}${key}`;
    return this.secrets.get(internalKey);
  }

  public async deleteSecret(key: string): Promise<void> {
    const internalKey = `${HarnessSecretManager.KEY_PREFIX}${key}`;
    await this.secrets.delete(internalKey);
  }
}

