# AI QA Testing Harness - User Guide (v0.5.1)

Write a requirement and its acceptance criteria, and the harness designs a **test suite** for that
module, lets you review and approve it, generates Playwright tests, runs them in a real browser, and
keeps the suite so you can **retest** it or include it in a **regression** run later.

Nothing is tied to a particular website: every target URL, allowed domain, module name, credential,
and AI model comes from you at run time.

---

## 1. Requirements

* VS Code `1.94` or newer.
* Python `3.10` to `3.12` on the PATH (only needed once, for **Set Up Engine**).
* Google Chrome or Microsoft Edge for headed runs (Playwright's Chromium is used as a fallback).
* An AI provider for requirement-driven design: GitHub Copilot in VS Code, or an API key.

## 2. Install and set up

1. Install the extension package:
   ```bash
   code --install-extension extension/ai-qa-testing-harness-0.5.1.vsix
   ```
2. Open the folder you want to keep test suites in (VS Code must trust the folder).
3. Click the **QA Harness** beaker in the Activity Bar.
4. If the panel shows *"Engine not set up"*, click **Set Up Engine**. It creates a private Python
   environment for the extension, installs the engine's dependencies, and downloads Playwright's Chromium.
   You only do this once per machine.

The extension looks for the engine in this order: the `qaHarness.enginePath` setting, an `engine/`
folder in the open workspace, then the copy bundled inside the extension. Python is resolved from the
`qaHarness.pythonPath` setting, `engine/.venv`, the workspace `.venv`, then the private environment.

### The panel at a glance

* **Agent steps.** While a run is active, the Assistant tab shows each step the agent takes:
  *reading* the requirement, *thinking* (every AI call: analysis, page choice, design, revision),
  *browsing* pages, *waiting* for you at a gate, *generating* tests, the *AST security gate*, the
  *dry run*, *running* tests (live `3/6 · 2 passed` progress with the pytest output attached),
  *investigating* failures, and *building reports*. Each step shows its result and duration. Groups of
  finished steps collapse to "Completed N steps"; click to expand.
* **Stage track.** The bar under the run title shows where the run is: Scope, Analyze, Explore,
  Design, Review, Dry run, Execute, Report. Retests and regressions skip the design stages.
* **Run history.** Every execution (new suite, suite update, retest, failed-case retest, regression)
  is its own entry in the history sidebar (the panel icon, top left). In a wide panel the history
  stays open as a column. Search, filter by type, and click an entry to replay its full transcript
  read-only (report and file buttons still work). The trash icon removes a finished entry from the
  history only; reports, evidence, and the audit trail stay in `.qa-harness`.

### The panel at a glance

* **Agent steps.** While a run is active, the Assistant tab shows each step the agent takes:
  *reading* the requirement, *thinking* (every AI call: analysis, page choice, design, revision),
  *browsing* pages, *waiting* for you at a gate, *generating* tests, the *AST security gate*, the
  *dry run*, *running* tests (live `3/6 · 2 passed` progress with the pytest output attached),
  *investigating* failures, and *building reports*. Each step shows its result and duration. Groups of
  finished steps collapse to "Completed N steps"; click to expand.
* **Stage track.** The bar under the run title shows where the run is: Scope, Analyze, Explore,
  Design, Review, Dry run, Execute, Report. Retests and regressions skip the design stages.
* **Run history.** Every execution (new suite, suite update, retest, failed-case retest, regression)
  is its own entry in the history sidebar (the panel icon, top left). In a wide panel the history
  stays open as a column. Search, filter by type, and click an entry to replay its full transcript
  read-only (report and file buttons still work). The trash icon removes a finished entry from the
  history only; reports, evidence, and the audit trail stay in `.qa-harness`.

## 3. Connect an AI provider (AI Provider tab)

| Provider | What you enter |
| :--- | :--- |
| GitHub Copilot (default) | Nothing. Uses your Copilot subscription through VS Code. Accept the consent prompt on first use. |
| OpenAI | API key |
| Azure OpenAI | Resource endpoint (`https://<resource>.openai.azure.com`), API key, deployment name as the model |
| Anthropic | API key |
| Google Gemini | API key |
| GitHub Models | Fine-grained GitHub token with **Models: read** permission; model IDs look like `openai/gpt-4.1` |
| OpenAI-compatible | HTTPS base URL and API key |
| None | Nothing. Only smoke suites built from page structure are available. |

1. Pick the provider, paste the key if one is needed, and click **Save**.
2. Click **Load models** to list the models your account can use, then pick one (leave empty for Copilot's default).
3. Click **Test** to confirm the connection.

Keys are stored in VS Code's encrypted SecretStorage (the OS keychain). They are never written to
files, logs, or prompts. Custom endpoints must use HTTPS. Models that do not accept a `temperature`
setting (some reasoning models) are retried automatically without it.

### AI cost controls

AI is used in two places:

* **Designing suites** (requirement analysis, page choice, design, revisions, dry-run repair): a handful
  of calls per suite version. These are **never limited**, because a half-designed suite would be worse
  than the cost. Retests and regressions do not redesign, so they make no design calls.
* **Analyzing failed tests** after a run: this is the part that grows with nightly or repeated runs, and
  the only part the limits apply to. Each failure is handled the cheapest way that is still correct:
  1. **Rules** first: flaky tests (passed on retry) and server or connection errors need no AI.
  2. **Same error in this run**: when several tests fail with the same specific error (for example the
     same missing button), one AI analysis is shared by all of them.
  3. **Same failure as an earlier run**: when the same test fails with the same error on the same
     approved suite version and target within 7 days, the earlier analysis is reused.
  4. **AI analysis**, highest-priority cases first, up to the per-run and daily limits.
  5. Beyond the limits, failures are classified by rules and the report says the limit was reached.

Limits never change results: pass/fail counts, retests, regressions, and Gate 2 (every product defect
needs your sign-off) work exactly the same. Reused analyses cite only evidence from the current run,
and every analysis in the report says how it was produced (AI, reused, earlier run, or rules).

Set the limits in the **AI cost controls** card of the AI Provider tab, which also shows today's usage:

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| Analyze failed tests with AI (`qaHarness.ai.investigateFailures`) | on | Off = rules only |
| Max AI analyses per run (`qaHarness.ai.maxInvestigationsPerRun`) | 5 | Distinct failures analyzed by AI per run |
| Max AI analyses per day (`qaHarness.ai.dailyInvestigationLimit`) | 50 | Shared by panel and CLI runs in the workspace |
| Reuse earlier analyses (`qaHarness.ai.reuseAnalyses`) | on | Off = always ask the AI |
| Failure-analysis model (`qaHarness.ai.investigationModel`) | empty | A cheaper model just for failure analysis. If it fails, the main model is used |

With GitHub Copilot, pick a model that your plan includes without premium requests as the
failure-analysis model, and keep the stronger model for design. Usage per day is kept in
`.qa-harness/ai-usage.json`; each run's usage is in its `ai_usage.json` and on the report card.

## 4. Approver identity

Approvals (scope, test cases, defects, retests, regressions) are recorded under your **GitHub account
name**. Click the user chip at the top of the panel, use the **GitHub account** card in the AI Provider tab,
or run `QA Harness: Sign In / Switch GitHub Account (Approver)`. The account menu lets you:

* pick any GitHub account already signed into VS Code,
* **Sign in with another GitHub account** (if GitHub signs you in as the same user again, switch accounts
  on github.com in your browser first),
* **Sign out**, which stops the QA Harness from using the account (also `QA Harness: Sign Out GitHub
  Account (Approver)`). To remove the account from VS Code completely, use the Accounts menu (person icon,
  bottom left) and choose Sign Out.

GitHub Copilot uses the account signed into the GitHub Copilot extension, which can be different from the
approver. Change the Copilot account from the VS Code Accounts menu.

## 5. Create a test suite (Suites tab, "New Suite")

Fill in:

* **Module**: the feature under test, e.g. `User Login`. It becomes the suite name and the test case ID
  prefix (`TC-USER-LOGIN-001`).
* **Start URL**: the page where testing begins. Localhost and private network addresses are blocked.
* **Allowed domains**: comma-separated hosts the browser may visit (defaults to the start URL's host).
* **Environment**: any name, e.g. `dev`, `test`, `staging`, `uat` (letters, digits, `.`, `_`, `-`).
* **Requirement** and **Acceptance criteria**: one criterion per line. They are numbered `AC-1`, `AC-2`, ...
* **Use AI**: on for requirement-driven design; off for a smoke suite from the page structure.
* **Dry run**: on by default. Every step is tried once on the live page before the real run (see step 5).

Then the workflow runs in the **Assistant** tab:

1. **Scope card (Gate 0)**: check the domains and environment, tick the authorization attestation, confirm.
2. **Clarifications**: the AI may ask up to 5 questions about the requirement. Answer or skip.
3. **Exploration**: the browser opens the start page and up to 4 relevant in-scope pages and records their
   accessibility tree (headed mode shows this live).
4. **Review card (Gate 1)**: each case shows its acceptance criterion, priority, test types (smoke, sanity,
   regression, functional, negative, boundary, ui, accessibility), steps, and its automation plan.
   The card also lists AC coverage, required secrets, and locators that were not seen on the explored pages.
   Use **Request changes** to have the AI revise (a new version with a diff), or **Approve**.
5. **Dry run (Stage 7)**: each approved case is replayed once in a fresh browser context. Every locator must
   exist on the live page and every click, fill, or navigation must succeed; assertions are not judged yet.
   If a step cannot be performed (element not found, index out of range, action failed, navigation blocked),
   a **Dry run** card lists each problem with a screenshot, and you choose:
   * **Fix with AI**: the AI repairs only the broken steps using the pages where they failed. Your Gate 1
     approval is withdrawn (recorded in the audit log) and the repaired version comes back for review.
   * **Run anyway**: execute the suite as approved; the broken steps will fail in the report.
   * **Cancel**: stop the run.
   Cases whose secrets are missing are skipped by the dry run and reported as blocked.
6. **Generation and execution**: approved cases are compiled into Page Object + pytest code, checked by the
   AST security gate, and run in the browser.
7. **Report card**: pass/fail/flaky/blocked counts, investigation of failures, and links to the HTML report.
   Failures that look like product defects need your sign-off (Gate 2) before they count as defects.

The approved suite is saved to `.qa-harness/suites/<module>/` in your workspace.

## 6. Updating or deleting a suite

* **Update** (suite card, or `QA Harness: Update Suite`) opens the form with the stored requirement, criteria,
  URL, and domains. Edit the requirement or criteria and submit. The AI revises the approved suite: cases
  that still apply keep their IDs, changed criteria get updated cases, new criteria get new cases, and
  removed criteria lose theirs. The review card shows the changes against the approved version, and the
  new version is saved only after you approve it (the run appears as an **update** in the history).
* **Delete** (suite card, or `QA Harness: Delete Suite`) asks for confirmation, then moves the suite and its
  run history to `.qa-harness/archive/suites/` (nothing is erased; `archive-log.json` records who deleted it
  and when) and removes the suite's stored secrets from the keychain. A suite cannot be deleted while it is
  running or being updated.

## 7. Retesting a module

On a suite card in the **Suites** tab:

* **Retest all** re-runs every case of the module.
* **Retest failed** re-runs only the cases that failed, were flaky, or were blocked in the last run.

You then pick the **environment**: the suite's default, an environment saved earlier, or **Another
environment** (a name plus the same start page on that environment's host, e.g.
`https://staging.your-app.example/login`). The new environment is saved on the suite for next time. The
approved scripts are not changed: the original host is mapped to the environment's host at run time, and the
browser is allowed only on that host plus the suite's other allowed domains. Localhost and private
addresses are refused here too.

Retests reuse the approved suite without redesigning it. Before each run, the stored test cases and scripts
are checked against their approved SHA-256 hashes and the scripts are re-validated; a modified suite is
refused. You confirm authorization for every retest.

## 8. Regression

In the **Suites** tab, choose a test-type filter (all cases, or only smoke, sanity, regression, functional,
negative, boundary, ui, or accessibility cases) and click **Run regression**. Then choose the environment:
each suite's default, or one environment name for all suites. Suites that do not have that environment are
listed as *not run* in the report instead of running somewhere else.

Every selected suite runs one after another, and a combined regression report is written to
`.qa-harness/regressions/<id>/` (HTML, Markdown, JSON). The report lists, for each module, which cases are
**newly failing** and which are **fixed** compared with the previous run.

## 9. Secrets for tests (logins, tokens)

When a test needs a credential, the AI writes a placeholder such as `{{secret.USERNAME}}` instead of a value.
Before a run, the extension asks for any missing values and stores them per suite in SecretStorage. Use the
**Secrets** button on a suite card (or `QA Harness: Manage Suite Secrets`) to change or remove them.

Values reach only the test process as `QA_SECRET_<NAME>` environment variables and are replaced with
`[MASKED-SECRET]` in logs and reports. A test whose secret is missing is reported as **BLOCKED**, not failed.

## 10. Command-line runner (no VS Code, CI)

From a workspace folder (Windows: `qa-harness.bat`, or `python -m qa_engine.cli` with the engine on `PYTHONPATH`).
`--workspace <dir>` goes before the command; `--approver` can come from the `QA_APPROVER` variable.

```bash
# Requirement-driven AI suite (needs the QA_AI_* variables below)
qa-harness suite --url https://your-app.example/login --module "User Login" --environment test \
  --requirement-file login.md --criteria-file login-ac.txt --approver your-github-name

qa-harness smoke --url https://your-app.example --module "Home page" --environment staging --approver your-github-name --yes
qa-harness list
qa-harness retest --module "User Login" --approver your-github-name --yes
qa-harness retest --module "User Login" --failed-only --environment uat --base-url https://uat.your-app.example/login --approver your-github-name --yes
qa-harness regression --tag smoke --environment uat --approver your-github-name --yes
qa-harness delete --module "Home page" --approver your-github-name --yes
```

`suite` shows the clarification questions, the designed cases, and any dry-run problems in the terminal and
asks you to approve, request changes, fix, or quit. With `--yes` it leaves the questions unanswered, approves
the first version, and runs anyway when the dry run finds problems (those steps then fail and the exit code
is `3`). Use `--yes` for `suite` only in CI for requirements you have reviewed before.

The CLI's AI provider is configured with environment variables (the key never goes into files or arguments):

| Variable | Value |
| :--- | :--- |
| `QA_AI_PROVIDER` | `openai`, `azure-openai`, `anthropic`, `gemini`, `github-models`, or `openai-compatible` |
| `QA_AI_API_KEY` | API key (`github-models` also accepts `GITHUB_TOKEN`, e.g. in GitHub Actions with `models: read`) |
| `QA_AI_MODEL` | Model ID (Azure: deployment name; GitHub Models: e.g. `openai/gpt-4.1`) |
| `QA_AI_BASE_URL` | HTTPS endpoint; required for `azure-openai` and `openai-compatible` |
| `QA_AI_AZURE_API_VERSION` | Azure REST api-version (default `2024-10-21`) |
| `QA_AI_INVESTIGATION_MODEL` | Optional cheaper model used only for failure analysis |

Cost controls (see [AI cost controls](#ai-cost-controls)): `--ai-investigations <n>` (per run, default 5,
`0` = rules only), `--ai-daily-limit <n>` (default 50), `--no-ai-reuse`.

Other options: `--domains`, `--headless`, `--slowmo <ms>`, `--channel chrome|msedge`, `--no-dry-run`.
`--yes` records your authorization attestation. Secrets come from `QA_SECRET_<NAME>` environment variables.
Exit codes: `0` all passed, `3` test failures, `2` error, `1` cancelled.

## 11. Settings

| Setting | Purpose |
| :--- | :--- |
| `qaHarness.ai.provider` / `ai.model` / `ai.baseUrl` / `ai.azureApiVersion` | AI provider (also editable in the AI Provider tab) |
| `qaHarness.headed` | Show the browser window (default on) |
| `qaHarness.slowMoMs` | Delay between browser actions in headed mode |
| `qaHarness.browserChannel` | `chrome`, `msedge`, or empty for bundled Chromium |
| `qaHarness.enginePath` / `qaHarness.pythonPath` | Override engine folder or interpreter |

## 12. Where things are stored

| Path | Contents |
| :--- | :--- |
| `.qa-harness/suites/<module>/` | Suite record (with saved environments), approved test case versions, approval, scripts, run history |
| `.qa-harness/runs/<run-id>/` | Per-run scripts, `dry_run.json`, evidence (screenshots, traces), `audit.jsonl`, and `report/` (HTML, MD, JSON, JUnit) |
| `.qa-harness/regressions/<id>/` | Combined regression reports |
| `.qa-harness/archive/suites/` | Deleted suites and `archive-log.json` |
| `.qa-harness/ai-usage.json` | AI calls per day (design and failure analysis), last 30 days |
| `.qa-harness/cache/investigations.json` | Reusable failure analyses (7 days, max 500) |
| `.qa-harness/history/` | Panel transcript of every run (messages, agent steps, cards, test output) for the history sidebar. Secret values never reach the panel, so they are never stored here |
| `.qa-harness/history/` | Panel transcript of every run (messages, agent steps, cards, test output) for the history sidebar. Secret values never reach the panel, so they are never stored here |
