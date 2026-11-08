/**
 * Approver identity from a GitHub account signed into VS Code.
 * Every human gate (scope, clarifications, approval, revisions, retest, regression) is
 * recorded in the audit trail under this account name.
 *
 * The chosen account is remembered per machine. Signing out only stops the QA Harness from
 * using the account; removing it from VS Code itself is done in the Accounts menu, because
 * extensions cannot delete another provider's sessions.
 */

import * as vscode from "vscode";

const PROVIDER = "github";
const SCOPES = ["read:user"];
const STATE_KEY = "qaHarness.approverAccount";

type StoredChoice = { id: string; label: string } | "signed-out" | undefined;

export class IdentityService {
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  public readonly onDidChange = this.changeEmitter.event;

  constructor(private readonly context: vscode.ExtensionContext) {
    context.subscriptions.push(
      this.changeEmitter,
      vscode.authentication.onDidChangeSessions((e) => {
        if (e.provider.id === PROVIDER) this.changeEmitter.fire();
      })
    );
  }

  private stored(): StoredChoice {
    return this.context.globalState.get<StoredChoice>(STATE_KEY);
  }

  private async remember(choice: StoredChoice): Promise<void> {
    await this.context.globalState.update(STATE_KEY, choice);
    this.changeEmitter.fire();
  }

  /** Approver account name, or undefined when signed out (never prompts). */
  public async current(): Promise<string | undefined> {
    const choice = this.stored();
    if (choice === "signed-out") return undefined;
    try {
      const session = await vscode.authentication.getSession(PROVIDER, SCOPES, {
        silent: true,
        ...(choice ? { account: choice } : {}),
      });
      return session?.account.label;
    } catch {
      return undefined;
    }
  }

  /** Approver account name, asking the user to choose or sign in when there is none. */
  public async require(): Promise<string> {
    const name = (await this.current()) ?? (await this.chooseAccount());
    if (!name) throw new Error("Sign in with GitHub to approve QA gates.");
    return name;
  }

  /**
   * Account menu: pick one of the GitHub accounts signed into VS Code, add another one, or
   * sign out. Returns the selected account name, or undefined when cancelled / signed out.
   */
  public async chooseAccount(): Promise<string | undefined> {
    const active = await this.current();
    const accounts = await vscode.authentication.getAccounts(PROVIDER);

    type Item = vscode.QuickPickItem & {
      action: "use" | "add" | "signOut";
      account?: vscode.AuthenticationSessionAccountInformation;
    };
    const items: Item[] = accounts.map((account) => ({
      label: `$(account) ${account.label}`,
      description: account.label === active ? "current approver" : undefined,
      action: "use",
      account,
    }));
    items.push({
      label: "$(add) Sign in with another GitHub account",
      detail: "Opens GitHub in your browser. Switch accounts on github.com first if needed.",
      action: "add",
    });
    if (active) {
      items.push({
        label: "$(sign-out) Sign out",
        description: `stop approving as ${active}`,
        action: "signOut",
      });
    }

    const pick = await vscode.window.showQuickPick(items, {
      title: "QA Harness approver (GitHub account)",
      placeHolder: active ? `Approving as ${active}` : "Choose the GitHub account that approves QA gates",
    });
    if (!pick) return undefined;
    if (pick.action === "signOut") {
      await this.signOut();
      return undefined;
    }
    return pick.action === "use" && pick.account
      ? this.useAccount(pick.account)
      : this.addAccount();
  }

  public async signOut(): Promise<void> {
    const active = await this.current();
    await this.remember("signed-out");
    const choice = await vscode.window.showInformationMessage(
      active
        ? `QA Harness signed out of ${active}. To remove the account from VS Code completely, ` +
            "use the Accounts menu (person icon, bottom left) and choose Sign Out."
        : "QA Harness is signed out.",
      "Choose another account"
    );
    if (choice) await this.chooseAccount();
  }

  private async useAccount(
    account: vscode.AuthenticationSessionAccountInformation
  ): Promise<string> {
    const session = await vscode.authentication.getSession(PROVIDER, SCOPES, {
      createIfNone: true,
      account,
    });
    await this.remember({ id: session.account.id, label: session.account.label });
    return session.account.label;
  }

  private async addAccount(): Promise<string> {
    const known = new Set((await vscode.authentication.getAccounts(PROVIDER)).map((a) => a.id));
    const session = await vscode.authentication.getSession(PROVIDER, SCOPES, {
      forceNewSession: {
        detail: "Sign in with the GitHub account that should approve QA gates.",
      },
      clearSessionPreference: true,
    });
    await this.remember({ id: session.account.id, label: session.account.label });
    if (known.has(session.account.id)) {
      void vscode.window.showWarningMessage(
        `GitHub signed you in as ${session.account.label} again. To use a different account, ` +
          "sign out on github.com (or switch accounts there) and choose 'Sign in with another " +
          "GitHub account' once more."
      );
    }
    return session.account.label;
  }
}
