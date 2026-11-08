# Plan: Requirement-Driven Test Suites, Retesting, Regression & LLM Providers

**Status:** Draft for approval — no code changed yet
**Date:** 2026-11-08

---

## 1. Goals (what the user asked for)

1. **Requirement → Test Suite.** The user enters a *requirement* and its *acceptance criteria*
   for a module (e.g. "Checkout", "User Login"). The harness analyses it, asks clarification
   questions when something is missing, drafts a **test suite** (multiple test cases) traced to
   every acceptance criterion, gets human approval (Gate 1), generates scripts, and runs them in
   visible Chrome — exactly like today's run flow.
2. **Retesting a module.** Later, the user can say "retest Checkout" and **all approved cases of
   that module's suite** run again — no regeneration, same approved scripts, new results.
   (Option: retest only the cases that failed last time.)
3. **Regression testing.** One action runs **all saved suites** of the project and produces one
   combined report that compares against the previous run (new failures, fixed, still failing).
4. **Everything dynamic.** No hard-coded websites, credentials, user names, environments,
   domains, or example data anywhere in production code. Everything comes from the user's input,
   the scope card, settings, or the explored site.
5. **Easy LLM connection.** A dedicated **"AI Provider" settings section** in the QA panel where
   the user either:
   - connects **GitHub Copilot** directly (no API key — uses the Copilot subscription already
     signed in to VS Code, or the GitHub Copilot SDK/CLI), or
   - picks an **API-key provider** (OpenAI, Azure OpenAI, Anthropic, Google Gemini, or any
     OpenAI-compatible endpoint such as Ollama / OpenRouter / Groq / LM Studio), enters key +
     model, and clicks **Test connection**.

---

## 2. Findings from the full system inspection

### 2.1 Hard-coded values / example dependencies (must be removed or made dynamic)

| Location | Hard-coded item | Fix |
| :--- | :--- | :--- |
| `engine/run_live_workflow.py` | herokuapp URL, `tomsmith` / `SuperSecretPassword!`, approver `Abdullah_Umar`, fixed run id, hand-written login tests & page object | Replace with a generic CLI runner (`python -m qa_engine.cli run --url … --requirement file.md`) driven entirely by arguments; delete the demo script |
| `run_live_visible.bat` | herokuapp URL and credentials in banner | Becomes a generic launcher that prompts for URL / requirement file, or is removed |
| `.qa-harness/runs/run-live-herokuapp-001` | Demo artifacts | Delete |
| `extension/webview/main.js` | Fallbacks `staging.example.com`, environment `"test"` | No fallbacks — card renders only engine data; missing data shows an error |
| `extension/src/chatProvider.ts`, `extension.ts` | herokuapp placeholder / welcome example, approver `"engineer"` | Neutral placeholder text; approver = configured name or signed-in GitHub account |
| `engine/qa_engine/main.py`, `state_machine.py`, `review.py` | actor/approver `"engineer"`, environment `"test"`, `page_name="main"` | Actor/approver from the request; environment chosen on the scope card; page names derived from explored pages |
| `generation/auto_design.py` | `REQ-SMOKE-001`, `TC-SMOKE-` prefix | IDs derived from the module and acceptance-criterion IDs |
| `run_store.ScopeModel` | defaults `environment="test"`, `browsers=["chromium"]` | Scope card supplies them; defaults only as UI suggestions |
| `extension/test-integration.js` | `staging.example.com` | Read URL from argument / env |
| `security/ssrf.py` | Always blocks `localhost` & private IPs | Keep as default, add an explicit, audited **"Allow local/private targets"** opt-in on the scope card so local dev apps can be tested |
| Scope allowlist | Only the URL's exact hostname | Scope card lets the user add extra domains (CDNs, auth providers) |
| `EngineClient` | Assumes the opened workspace *is* this repo (`<workspace>/engine`) | Resolve the engine from the extension install / `qaHarness.enginePath`, add **"QA Harness: Set Up Engine"** command (creates venv, installs requirements + Playwright browser). Then any project folder can be the workspace |
| `README.md` | Empty | Real quick-start |

Unit tests may keep RFC-2606 reserved hosts (`example.com`, `test.local`) — they are test fixtures,
not runtime dependencies.

### 2.2 Bugs / gaps found that block the new features

1. `CopilotLLMProvider` is a stub that returns empty strings — no real LLM is ever called.
2. `FailureClassifier._run_llm_investigation` calls the **async** `llm.chat()` without `await`
   — would crash as soon as a real provider is connected.
3. The requirement text is stored but **never used** for test design; `prompts/analysis.py` and
   `prompts/test_design.py` exist but nothing calls them.
4. No clarification-question card, no "Request changes" revision loop wired (the
   `ReviewManager` + `TestCaseDiffEngine` exist but are unused).
5. Scripts can only express "visible / fillable / title" checks — no click, submit, select,
   navigation or message assertions needed by real acceptance criteria.
6. No way to inject test credentials into running tests (the `credentials_ref` field exists, but
   nothing resolves it). Real login flows are impossible without hard-coding.
7. Every run is a throw-away folder under `.qa-harness/runs/` — there is no persistent suite
   library, so retesting and regression are impossible.
8. Exploration only snapshots the start page; multi-page flows (login → dashboard) are not mapped.

---

## 3. Target design

### 3.1 Concepts

| Concept | Meaning | Stored at |
| :--- | :--- | :--- |
| **Project** | The opened workspace (the app under test) | `.qa-harness/project.json` |
| **Module / Suite** | One feature area with its requirement + acceptance criteria and its approved test cases & scripts | `.qa-harness/suites/<module-slug>/` |
| **Suite version** | Each approved revision of the suite (hash-bound, Gate 1) | `suites/<slug>/versions/v<N>/` |
| **Run** | One execution (new design run, retest, or regression) | `.qa-harness/runs/<run-id>/` (unchanged) |
| **Test type tag** | `smoke`, `sanity`, `regression` per test case (LLM proposes, human approves) | inside each test case |

Suite folder layout:

```
.qa-harness/suites/checkout/
  suite.json            # module name, base URL, allowed domains, current approved version, hash
  requirement.md        # requirement + acceptance criteria (redacted), versioned
  versions/v1/
    testcases.json      # approved Appendix-A cases, each with ac_ref + test_type tags
    testcases.md
    scripts/pages/*.py  # generated page objects
    scripts/tests/test_<module>.py
    approval.json       # approver, timestamp, SHA-256
  history.json          # list of run ids + pass/fail per case (for retest & regression diff)
```

### 3.2 Workflows

**A. New requirement → new suite (or new version of an existing suite)**

```
Chat: module name + URL + requirement + acceptance criteria
 → Gate 0 scope card (URL, extra domains, environment, local-target opt-in, credential refs)
 → Stage 1  Intake + redaction
 → Stage 2  LLM analysis → clarification card if anything is missing (user answers in chat)
 → Stage 3  Guided exploration in visible Chrome (LLM uses Appendix-C browser tools,
            bounded by max_pages / max_steps, only allowed domains, no destructive clicks
            without approval) → snapshots of every page the flow touches
 → Stage 4  LLM test design: cases per acceptance criterion (positive, negative, boundary),
            coverage matrix, test-type tags
 → Stage 5  Gate 1 review card: approve, or "Request changes" with comments → LLM revision
            → v2 with diff shown → approve
 → Stage 6  Script generation (see 3.4) + AST security gate
 → Stage 7  Dry run with bounded locator/timing stabilisation (assertions never auto-changed)
 → Stage 8  Execution in visible Chrome with live log
 → Stage 9  Investigation (LLM RCA, evidence-cited), Gate 2 for product defects
 → Stage 10 Reports; suite saved/updated in the library
```

**B. Retest a module** — chat command or panel button "Retest ▸ <module>":
loads the suite's approved version, verifies its SHA-256 still matches the approval, runs **all**
its cases (or "failed only"), compares with that suite's previous run, produces a report.
No LLM is required for retesting.

**C. Regression** — "Run regression": runs every suite (optionally filtered by tag, e.g. only
`smoke`) sequentially, one combined report with per-module sections and a delta vs. the last
regression run (new failures / fixed / still failing / flaky).

**D. Smoke / sanity shortcuts** — same as regression but filtered by the `smoke` or `sanity` tag.

**E. No-LLM fallback** — if no provider is configured, workflow A falls back to the current
deterministic smoke designer and the UI clearly says requirement-driven design needs an AI
provider. Retest and regression always work without an LLM.

### 3.3 Chat & panel UX

- Panel gets three tabs: **Chat**, **Suites**, **AI Provider**.
- **Suites tab:** list of modules with last result, buttons *Retest*, *Retest failed*,
  *Open report*, *View cases*, *Delete*; a top bar with *Run regression* and a tag filter.
- **Chat** keeps the gate cards; new cards: *Clarification*, *Revision diff*, *Regression summary*.
- New requirement input: a structured form (Module name, Target URL, Requirement,
  Acceptance criteria list) plus free-text paste support.
- Commands: `QA Harness: New Suite from Requirement`, `Retest Module`, `Run Regression`,
  `Configure AI Provider`, `Set Up Engine`.

### 3.4 Script generation (safe and dynamic)

The LLM does **not** write free-form Python. It returns, per test case, a structured
**action plan** validated by Pydantic, built only from elements seen in the exploration snapshots:

```json
{"tc_id": "TC-CHECKOUT-003", "steps": [
  {"action": "goto", "path": "/cart"},
  {"action": "fill", "role": "textbox", "name": "Coupon code", "value": "{{data.invalid_coupon}}"},
  {"action": "click", "role": "button", "name": "Apply"},
  {"action": "expect_text", "role": "alert", "contains": "Coupon is not valid"}
]}
```

Allowed actions: `goto`, `click`, `fill`, `select`, `check`, `press`, `expect_visible`,
`expect_hidden`, `expect_text`, `expect_url`, `expect_title`, `expect_value`, `expect_count`.
A deterministic generator turns plans into Page Objects + pytest code, then the existing AST
validator runs. Benefits: no arbitrary code from the model, locators are always role-based,
and retests replay identical code.

### 3.5 Test data & credentials (no hard-coding)

- Test cases reference data as placeholders: `{{data.<key>}}` (non-secret, stored in the suite)
  and `{{secret.<name>}}` (secret).
- Secrets are stored with the existing `QA Harness: Store Test Credentials` command
  (OS keychain via VS Code SecretStorage).
- At execution the extension resolves the needed secrets and passes them **only** as
  environment variables to the sandboxed pytest process (`QA_SECRET_<NAME>`); the generated code
  reads them through a harness fixture. Secrets never enter prompts, files, logs or reports
  (redaction engine masks them in output).

---

## 4. AI Provider section (LLM + GitHub Copilot)

### 4.1 Provider options

| Provider | What the user does | How it works |
| :--- | :--- | :--- |
| **GitHub Copilot (VS Code)** — *recommended, no key* | Select it, pick a model from the dropdown, click *Test* | Extension uses the VS Code Language Model API (`vscode.lm.selectChatModels({ vendor: "copilot" })`) with the user's existing Copilot sign-in. The engine sends `llm.request` to the extension over the existing stdio JSON-RPC; the extension calls the model and returns the reply. |
| **GitHub Copilot SDK / CLI** | Select it, set CLI path if not on PATH, click *Test* | Engine-side `CopilotSdkProvider` using the `github-copilot-sdk` Python package (talks to the Copilot CLI). Optional dependency; the UI shows install/sign-in instructions when missing. |
| **OpenAI** | API key + model | `OpenAICompatibleProvider` (Chat Completions, JSON mode) |
| **Azure OpenAI** | Endpoint + deployment + API version + key | Same adapter with Azure URL/headers |
| **Anthropic (Claude)** | API key + model | `AnthropicProvider` |
| **Google Gemini** | API key + model | `GeminiProvider` |
| **OpenAI-compatible (Ollama, OpenRouter, Groq, LM Studio, vLLM…)** | Base URL + model (+ key if required) | `OpenAICompatibleProvider` with custom base URL |
| **None (offline)** | — | Deterministic smoke designer; retest/regression still work |

### 4.2 UI (AI Provider tab)

- Provider dropdown → only the fields that provider needs appear (key field masked).
- **Model**: free text + "Load models" button where the provider supports listing.
- Buttons: **Test connection** (sends a tiny structured prompt and shows latency + model name),
  **Save**, **Disconnect / delete key**.
- Status badge in the panel header: `AI: Copilot (gpt-…) ✓` or `AI: not connected`.

### 4.3 Security rules

- API keys stored only in VS Code **SecretStorage** (OS keychain) — never in `settings.json`,
  workspace files, logs, audit or reports.
- Keys are handed to the engine at spawn time through environment variables of the **engine**
  process only; the pytest sandbox never receives them (sandbox allowlist unchanged).
- Non-secret choices (provider, model, base URL) go in VS Code settings (`qaHarness.ai.*`).
- All providers implement the existing `LLMProvider` interface plus `chat_structured(schema)`
  with the 2-attempt schema-repair retry from the spike report; prompt-injection defences
  (untrusted-data fences) stay in every prompt.
- Copilot permission handling stays deny-by-default (Appendix C tool allowlist).

---

## 5. Implementation phases

| Phase | Scope | Exit check |
| :--- | :--- | :--- |
| **0. Cleanup & dynamic config** | Remove all items in §2.1, generic CLI runner, engine path resolution + `Set Up Engine` command, fix classifier `await` bug, README | Grep finds no example hosts/credentials/names in production code; extension works from any workspace folder |
| **1. LLM provider layer** | Provider registry, OpenAI-compatible / Azure / Anthropic / Gemini adapters, VS Code Copilot bridge (`llm.request` RPC), Copilot SDK adapter, structured output + retry, AI Provider tab, Test connection | Each provider passes a contract test (mocked HTTP) and a live "Test connection" |
| **2. Requirement-driven design** | Structured requirement form, analysis + clarification card, guided multi-page exploration with tools, LLM test design with AC traceability + coverage matrix + tags, revision loop with diff | A requirement with 3 ACs yields cases covering all 3, shown in the review card with coverage |
| **3. Action-plan scripts** | Action-plan schema, deterministic POM/test generator, secrets/data fixtures, dry-run stabiliser wired | Generated suite for a login-style requirement passes AST gate and runs headed |
| **4. Suite library, retest, regression** | `.qa-harness/suites/` store, save on Gate 1, Retest / Retest failed, Run regression with tag filter, history + delta reports, Suites tab | Retest replays identical scripts; regression report shows per-module results and deltas |
| **5. Hardening & docs** | Unit/integration tests for every new module, security tests (secret leakage, prompt injection, SSRF opt-in), updated user guide, rebuilt & reinstalled VSIX | Full test suite + ruff + tsc green; end-to-end run in VS Code on a user-provided site |

Each phase ends with a working build so it can be reviewed before the next one starts.

---

## 6. Decisions needed from the user

1. **Default AI provider** to optimise first: GitHub Copilot via VS Code (no key) or an API-key
   provider (which one)?
2. **Local apps:** should testing `localhost` / private-network apps be allowed behind the
   explicit opt-in?
3. **Demo script:** delete `run_live_workflow.py` + `.bat` entirely, or replace with the generic
   CLI runner?
4. **Approver identity:** use the signed-in GitHub account name, or a `qaHarness.approverName`
   setting?
