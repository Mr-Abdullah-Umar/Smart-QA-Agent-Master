/**
 * Secret management integration using VS Code SecretStorage (OS Keychain).
 * Enforces T6 controls: real credentials never leak into prompts, logs, or workspace files.
 *
 * Two kinds of secrets are kept:
 * - AI provider API keys            qa-harness:ai:apiKey:<provider>
 * - Test data secrets per suite     qa-harness:suite:<slug>:<NAME>
 *   (resolved only when the engine runs that suite, injected as QA_SECRET_<NAME> env vars)
 */

import * as vscode from "vscode";

export class HarnessSecretManager {
  private static readonly AI_PREFIX = "qa-harness:ai:apiKey:";
  private static readonly SUITE_PREFIX = "qa-harness:suite:";

  constructor(private readonly secrets: vscode.SecretStorage) {}

  public getApiKey(provider: string): Thenable<string | undefined> {
    return this.secrets.get(`${HarnessSecretManager.AI_PREFIX}${provider}`);
  }

  public setApiKey(provider: string, key: string): Thenable<void> {
    return this.secrets.store(`${HarnessSecretManager.AI_PREFIX}${provider}`, key);
  }

  public deleteApiKey(provider: string): Thenable<void> {
    return this.secrets.delete(`${HarnessSecretManager.AI_PREFIX}${provider}`);
  }

  private suiteKey(slug: string, name: string): string {
    return `${HarnessSecretManager.SUITE_PREFIX}${slug}:${name.toUpperCase()}`;
  }

  public getSuiteSecret(slug: string, name: string): Thenable<string | undefined> {
    return this.secrets.get(this.suiteKey(slug, name));
  }

  public setSuiteSecret(slug: string, name: string, value: string): Thenable<void> {
    return this.secrets.store(this.suiteKey(slug, name), value);
  }

  public deleteSuiteSecret(slug: string, name: string): Thenable<void> {
    return this.secrets.delete(this.suiteKey(slug, name));
  }
}
