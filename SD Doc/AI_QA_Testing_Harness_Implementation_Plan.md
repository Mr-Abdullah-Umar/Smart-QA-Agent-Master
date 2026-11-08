# Advanced AI QA Testing Harness for Visual Studio Code
## Master Project Implementation Plan & Solution Analysis

**Document Reference:** `AI_QA_Testing_Harness_VSCode_Solution_Design.docx`  
**Target Architecture:** VS Code Extension (TypeScript) • Python QA Engine • GitHub Copilot SDK (Python) • Playwright • pytest  
**Approach:** Phased, Human-in-the-Loop, Zero-Trust Security by Design  
**Status:** Approved for Implementation Planning  

---

## 1. Executive Summary & Core Principles

The **Advanced AI QA Testing Harness** is a human-supervised, chat-driven testing companion delivered as a Visual Studio Code extension. A QA engineer interacts with the harness through a conversational chat panel and structured decision cards. The harness analyzes requirements, explores the web application using semantic browser tools, drafts standardized test cases, generates robust Python Playwright/pytest scripts, executes them in a local sandbox, investigates failures with root-cause analysis, and publishes self-contained multi-format reports.

### The Three Guiding Principles
1. **AI Proposes, Deterministic Tools Execute:** The Large Language Model (LLM) never directly executes shell commands, arbitrary HTTP requests, or unverified code. All actions are performed by deterministic, policy-enforced Python and Playwright tools.
2. **Humans Approve at Decisive Gates:** Explicit human approvals guard every critical boundary (Gate 0 for scope, Gate 1 for test cases, Gate 2 for defect sign-off, plus clarification and destructive-action approvals).
3. **Zero Trust for External Content:** Requirement text, target web pages, logs, and generated scripts are treated as untrusted. They are sanitized, size-capped, and checked against prompt-injection and security policies before processing.

---

## 2. High-Level Architecture & Process Model

The system is split into two cooperating tiers communicating over standard input/output (`stdin`/`stdout`):

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Visual Studio Code Extension Host                    │
│                                                                        │
│  ┌───────────────────────┐         ┌────────────────────────────────┐  │
│  │ Custom Chat Webview   │         │ Extension Controller (TS)      │  │
│  │ - Chat UI & Nonces    │◄───────►│ - Engine Process Lifecycle     │  │
│  │ - Decision Cards      │ (post-  │ - Workspace Trust & Settings   │  │
│  │ - Interactive Diffs   │  Msg)   │ - SecretStorage (OS Keychain)  │  │
│  └───────────────────────┘         └──────────────┬─────────────────┘  │
└───────────────────────────────────────────────────┼────────────────────┘
                                                    │ Standard Input/Output
                                                    │ (JSON-RPC 2.0 - No Network Socket)
┌───────────────────────────────────────────────────┼────────────────────┐
│ Python QA Engine (Isolated venv, Local Subprocess)│                    │
│                                                   ▼                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ RPC Dispatcher & State Machine (Orchestrator)                    │  │
│  │ - Run Store (JSON/MD)        - Hash-chained Audit Log (SHA-256)  │  │
│  └─────────────────┬───────────────────────────────┬────────────────┘  │
│                    │                               │                   │
│  ┌─────────────────▼──────────────┐  ┌─────────────▼────────────────┐  │
│  │ Policy & Guardrail Layer       │  │ AI Reasoning Layer           │  │
│  │ - Domain & SSRF Allowlist      │  │ - LLMProvider Interface      │  │
│  │ - Action Classifier            │  │ - GitHub Copilot SDK Python  │  │
│  │ - Redaction Engine             │  │ - Deny-by-default Handler    │  │
│  └─────────────────┬──────────────┘  └─────────────┬────────────────┘  │
│                    │                               │                   │
│  ┌─────────────────▼───────────────────────────────▼────────────────┐  │
│  │ Deterministic Tool Subsystems                                    │  │
│  │ - Browser Exploration: Playwright ARIA Tree Snapshots (No eval)  │  │
│  │ - Test Design: Standardized JSON/Markdown Test Cases             │  │
│  │ - Validation Pipeline: AST parser, Import Allowlist, Ruff/Bandit │  │
│  │ - Execution Sandbox: pytest-playwright with Clean Environment    │  │
│  │ - Evidence & Reporting: Traces, Screenshots, Jinja2 (Autoescape) │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Characteristics
* **Local Process Communication (No Network Sockets):** Extension and engine communicate strictly via JSON-RPC 2.0 over standard I/O streams. The engine opens no network listeners, preventing local network sniffing or unauthorized process access.
* **Pluggable LLM Layer (`LLMProvider`):** An internal abstraction insulates the codebase from upstream changes in the GitHub Copilot SDK (Python technical preview) and enables mocked providers for automated CI testing.
* **Strict Sandboxing:** Test execution runs in a stripped child process environment with strict per-test timeouts, process-tree termination on cancel, and restricted network egress.

---

## 3. End-to-End Workflow & Governance Gates

The system transitions through 11 discrete stages, guarded by human review gates:

| Stage | Name | Description | Human Gate / Key Artifact |
| :---: | :--- | :--- | :--- |
| **0** | **Authorization & Scope** | Engineer sets target URLs, allowed domains, environment type, credentials reference, limits, and confirms legal testing authorization. | **Gate 0 (Scope Confirmed)**<br>`scope.json`, `audit.jsonl` |
| **1** | **Requirement Intake** | Requirements accepted via chat or workspace files. High-entropy secrets and PII are redacted. | `requirement.md`<br>`redaction-report.json` |
| **2** | **AI Analysis & Clarification** | AI flags ambiguities, missing scenarios, contradictions, and regression risks. Unknowns become questions rather than assumptions. | `analysis.json`<br>*(Clarification Card)* |
| **3** | **Site Exploration** | Engine navigates allowed domains via Playwright. Computes semantic **ARIA accessibility trees** with element index references (`[#1]`, `[#2]`). State-changing actions are blocked or gated. | `site-profile.json`<br>Exploration screenshots |
| **4** | **Test Case Design** | Drafts test cases in the standardized schema (TC-ID, preconditions, numbered user-perspective steps, observable expected results). Traced 100% to requirements. | `testcases/v1.json`, `v1.md` |
| **5** | **Review Loop** | Engineer chooses **Approve**, **Request Changes** (with comments), or **Reject**. Revisions generate diffs. On approval, a SHA-256 content hash is recorded. | **Gate 1 (Test Cases Approved)**<br>`approvals.json` |
| **6** | **Script Generation** | Generates Python Playwright/pytest test functions and Page Object Model classes. Subject to static AST parsing, import allowlists, and Ruff/Bandit security scans. | `scripts/tests/`, `scripts/pages/`<br>*(Optional Script Review)* |
| **7** | **Dry Run & Stabilization** | Runs scripts once against live target with tracing. Self-repairs **locators and timing only** within strict retry limits. **Assertions are never modified automatically.** | `repair-log.json` |
| **8** | **Full Execution** | Pytest executes tests in clean subprocess across target browsers (Chromium default, Firefox, WebKit) and viewports. Retries detect flakiness. | Traces, screenshots, HAR logs, `junit.xml` |
| **9** | **Investigation & Reporting** | Failure packages assembled. AI classifies root cause (distinguishing observed facts citing stored evidence IDs from hypotheses). Generates 4 report formats. | `report/` (HTML, MD, JSON, JUnit XML) |
| **10** | **Review & Retest** | Engineer reviews failures, marks verified defects vs automation/environmental issues, signs off, and triggers retests. | **Gate 2 (Defect Sign-off)** |

---

## 4. Security Architecture & Threat Matrix (T1–T12)

| ID | Threat Vector | Primary Countermeasures |
| :--- | :--- | :--- |
| **T1** | **Prompt Injection** | Web content and logs treated as quoted data with size caps. Banned tools (no shell, no eval). Output schema validation. Instruction-like web content flagged. |
| **T2** | **Malicious Generated Script** | Python AST verification enforces strict import allowlist (`pytest`, `playwright`, `re`, `json`, `datetime`). Banned constructs (`eval`, `exec`, `subprocess`, `os.system`, `socket`, `pickle`, `ctypes`) rejected. Ruff and Bandit scans. |
| **T3** | **Command / Argument Injection** | Zero shell execution (`shell=False` everywhere). Arguments passed as validated arrays. |
| **T4** | **Path Traversal** | Canonical path resolution (`os.path.realpath`) and symlink rejection; operations restricted to run folder. |
| **T5** | **SSRF & Network Abuse** | Target domain allowlist checked on every request and redirect. Private/loopback ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`) and cloud metadata (`169.254.169.254`) blocked at connection time. |
| **T6** | **Credential Leakage** | Credentials stored exclusively in VS Code `SecretStorage`. AI model only sees placeholders (`{{TEST_USER}}`). Redaction engine masks secrets in prompts, logs, traces, and reports. |
| **T7** | **Sensitive Data Exfiltration** | Data classification declaration (synthetic vs sanitized). Snapshot truncation and data minimization. Per-run audit of transmitted payloads. |
| **T8** | **Destructive Actions** | Automated actions categorized into read vs write/destructive. Destructive actions blocked unless explicitly approved on a decision card. Step and rate budgets enforced. |
| **T9** | **Unauthorized Target Scanning** | Gate 0 mandatory attestation logged to tamper-evident audit trail. Target domain allowlist enforced. Production warning prompts. |
| **T10**| **Post-Approval Tampering** | Gate 1 approval binds test cases to a SHA-256 hash. The engine verifies this hash before generation and execution; mismatches halt the run. |
| **T11**| **Webview Script Injection** | Webview strictly enforces Content Security Policy (CSP) with dynamic per-render nonces, zero inline scripts, and HTML escaping of all model/target content. |
| **T12**| **Untrusted Workspace** | Adheres to VS Code Workspace Trust API; script generation and execution are locked out in untrusted workspaces. |

---

## 5. Master Implementation Roadmap (Phases 0 to 8)

### Phase 0: Foundation, Tooling, CI/CD & Feasibility Spike
* **Objective:** Establish the multi-root repository layout, configure CI/CD pipelines, configure static security scanners, and execute a technical feasibility spike on the GitHub Copilot SDK (Python edition).
* **Key Tasks:**
  1. Scaffold workspace: `extension/` (TypeScript), `engine/` (Python), `docs/`, `.github/workflows/`.
  2. Configure CI: ESLint, Prettier, Ruff, Bandit, Semgrep/CodeQL, `gitleaks`, `pip-audit`, `npm audit`, CycloneDX SBOM generator.
  3. Conduct Copilot SDK feasibility spike: verify session lifecycle, registration of custom tools (matching Appendix C), streaming responses, deny-by-default permission handling, and Pydantic schema validation.
  4. Write `docs/threat-model.md` and `docs/spike-report.md`.
* **Exit Criteria:** All CI static and security scans pass. Copilot SDK spike validates custom tools and deny-by-default permission handling.

### Phase 1: Python Engine Core & Orchestration Foundation
* **Objective:** Build the standalone Python engine with JSON-RPC stdio communication, state machine, tamper-evident audit logging, and the LLM provider abstraction.
* **Key Tasks:**
  1. Implement `qa_engine/main.py` and `qa_engine/orchestrator/rpc.py` handling JSON-RPC 2.0 over `sys.stdin`/`sys.stdout`.
  2. Implement `state_machine.py` managing stages 0 through 10.
  3. Implement `run_store.py` managing run directories (`scope.json`, `testcases/`, `approvals.json`, `scripts/`, `results/`, `evidence/`, `report/`).
  4. Implement `audit.py` writing append-only, SHA-256 hash-chained `audit.jsonl`.
  5. Implement `qa_engine/llm/provider.py` declaring `LLMProvider` interface; implement `copilot_provider.py` and `mock_provider.py`.
  6. Implement `qa_engine/security/{paths.py, redaction.py}` for path traversal prevention and token redaction.
* **Exit Criteria:** Headless engine runs via stdio, handles full mock cycles, and hash-chain audit logger detects simulated file modifications.

### Phase 2: VS Code Extension Shell & Interactive Webview
* **Objective:** Build the TypeScript extension providing the chat interface, interactive decision cards, engine lifecycle control, and secret management.
* **Key Tasks:**
  1. Implement `engineClient.ts` to spawn and manage the Python child process inside an isolated virtual environment.
  2. Implement `chatProvider.ts` registering the custom webview panel with strict CSP nonces and zero inline scripts.
  3. Build interactive decision cards:
     * **Gate 0 Scope Card:** Domains, environment, credential reference, legal authorization attestation.
     * **Clarification Card:** Ambiguity questions with selectable answers.
     * **Gate 1 Test Case Review Card:** Tabular test view, per-case comment boxes, version selector with visual diff viewer, Approve/Request Changes/Reject buttons.
     * **Script Preview Card, Failure Card, Report Card, and Progress Timeline.**
  4. Integrate `vscode.SecretStorage` for secure credential persistence.
  5. Integrate VS Code Workspace Trust API.
* **Exit Criteria:** Extension launches, renders cards in webview with zero CSP violations, exchanges JSON-RPC messages with the engine, and terminates engine process trees cleanly on cancellation.

### Phase 3: Requirement Intake, Guardrails & Site Exploration
* **Objective:** Implement requirement sanitization, network/SSRF guardrails, semantic browser exploration with ARIA accessibility trees, and AI requirement analysis.
* **Key Tasks:**
  1. Implement `qa_engine/security/ssrf.py` blocking loopback, private ranges, link-local, cloud metadata IPs, and open redirects.
  2. Implement Playwright browser exploration tools (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_fill`, `browser_select`, `browser_wait_for`, `browser_screenshot`).
  3. Implement semantic ARIA accessibility tree extraction with compact reference indexing (`[#1]`, `[#2]`).
  4. Implement action classification: block destructive actions unless approved via decision cards.
  5. Implement `site-profile.json` generator and AI requirement analysis prompt (flagging ambiguities and risks into questions).
* **Exit Criteria:** SSRF test suite blocks 100% of internal/metadata navigation attempts. Exploration produces robust ARIA site profiles without pixel guessing.

### Phase 4: Test Case Design & Review Loop
* **Objective:** Implement standardized test case drafting, coverage matrix mapping, and the interactive review/approval loop with SHA-256 approval hashing (Gate 1).
* **Key Tasks:**
  1. Implement Pydantic schema for Appendix A standard test cases (`tc_id`, `title`, `requirement_ref`, `category`, `priority`, `preconditions`, `test_data`, `steps`, `expected_result`, `postconditions`, `automation_candidate`, `version`, `status`).
  2. Implement AI test design prompt generating 100% traceable cases and `coverage_matrix.json`.
  3. Implement review loop: handle `run.testcases.comment` and `run.testcases.approve`.
  4. Compute side-by-side diffs between test-case versions (`v1` vs `v2`).
  5. On Gate 1 approval: calculate SHA-256 hash of approved test cases, record in `approvals.json`, and verify hash integrity before downstream stages.
* **Exit Criteria:** Test cases conform 100% to schema. Revision loop supports iterative comment updates. Modifying test cases post-approval halts downstream execution.

### Phase 5: Test Script Generation, AST Validation & Execution Sandbox
* **Objective:** Generate Python Playwright/pytest test scripts using the Page Object Model, validate them via strict AST security pipelines, stabilize them via dry runs, and execute them in a sandboxed runner.
* **Key Tasks:**
  1. Implement `scriptgen.py` generating Page Objects in `scripts/pages/` and pytest functions in `scripts/tests/` mapped with `@pytest.mark.tc("TC-ID")`.
  2. Implement `validator.py`:
     * AST parse check.
     * Import allowlist (`pytest`, `playwright`, `re`, `json`, `datetime`).
     * Banned construct rejection (`eval`, `exec`, `subprocess`, `os.system`, `socket`, `open` outside run data).
     * Programmatic Ruff and Bandit security scans.
  3. Implement dry-run stabilization: execute once with tracing; auto-repair locators and timing only (never change assertions/expected results); log to `repair-log.json`.
  4. Implement sandboxed pytest runner: stripped environment, process-tree timeouts, fresh browser context per test, retry logic marking retried passes as `flaky`.
* **Exit Criteria:** Validator rejects 100% of malicious script samples. Dry run repairs minor timing/locator issues. Execution produces traces, screenshots, and JUnit XML.

### Phase 6: Extended Coverage, Failure Investigation & Reporting
* **Objective:** Implement non-functional checks (accessibility, performance, console health, passive security), automated root-cause investigation with verified evidence citations, and multi-format reports.
* **Key Tasks:**
  1. Implement extended test coverage: `axe-core` accessibility audits, console error and network failure tracking, navigation timing metrics, passive security header checks.
  2. Implement `evidence.py` collecting and indexing screenshots, traces, HAR files, and logs with unique IDs (`[EV-001]`).
  3. Implement `classifier.py` for AI failure investigation (Appendix B format):
     * Segregate observed facts from hypotheses.
     * Programmatically verify cited evidence IDs exist on disk.
     * Classify into 7 mutually exclusive categories (*Product defect, Automation issue, Test data issue, Environment issue, Unclear requirement, Flaky, Insufficient evidence*).
     * Enforce human sign-off at Gate 2 before marking product defects.
  4. Implement `builder.py` generating reports in 4 formats: self-contained HTML (Jinja2 autoescape, zero JS), Markdown, JSON, and JUnit XML.
* **Exit Criteria:** Investigation engine correctly categorizes seeded failures with valid evidence links. HTML report renders cleanly with no embedded scripts.

### Phase 7: Security Hardening, Penetration Testing & Pilot Evaluation
* **Objective:** Execute the Appendix E pre-release security verification checklist, perform penetration testing, and pilot the harness against 3–5 representative web applications.
* **Key Tasks:**
  1. Execute Appendix E checklist: prompt injection test corpus, SSRF and DNS rebinding attacks, AST evasion attempts, CSP escape payloads, audit log verification.
  2. Pilot across 3–5 representative applications (e.g. Next.js SPA, traditional multi-page form app, enterprise dashboard with iframes, app with seeded defects).
  3. Measure Section 13 success criteria: test-case acceptance ($\ge 80\%$), traceability ($100\%$), investigation accuracy ($\ge 80\%$), outcome stability ($\ge 95\%$).
* **Exit Criteria:** Zero open Critical or High security findings. Pilot applications achieve or exceed all Section 13 target benchmarks.

### Phase 8: Packaging, Distribution & Documentation
* **Objective:** Package the extension into a distributable, signed VSIX package, package Python engine dependencies, and deliver user manuals and operational runbooks.
* **Key Tasks:**
  1. Bundle extension with `esbuild`/`webpack`.
  2. Package Python dependencies with verified SHA-256 hashes for offline installation.
  3. Generate signed `.vsix` package with checksums.
  4. Write `docs/user-guide.md`, `docs/runbooks.md`, and release notes.
* **Exit Criteria:** Clean installation and successful end-to-end execution verified on clean Windows, macOS, and Linux workstations. Signed off by Engineering and Security leads.

---

## 6. Technical Risk Management & Mitigation Matrix

| Identified Risk | Impact | Technical Mitigation in Architecture |
| :--- | :--- | :--- |
| **Incorrect Generated Expectations** | Tests assert behavior never specified. | Enforce Gate 1 approval. Trace tests 100% to approved criteria. Explicitly flag missing requirements as clarification questions instead of guessing. |
| **Flaky or Brittle Automation** | Fragile locators and timing cause false failures. | Use Playwright semantic role-and-name locators. Enforce web-first assertions. Ban `time.sleep()`. Classify retried tests as `flaky`. |
| **Sensitive Data Exposure** | Passwords or PII leak into prompts, logs, or reports. | Credentials kept exclusively in `SecretStorage`. The LLM only sees placeholders. Redaction scanner strips PII and high-entropy strings prior to LLM submission. |
| **Prompt Injection from Target Sites** | Malicious site content steers agent into unsafe actions. | Web content is treated strictly as data, never instructions. Tools cannot execute shell, run JS `eval`, or browse outside whitelisted domains. |
| **Upstream Copilot SDK Changes** | Technical preview SDK breaks existing engine code. | Isolate all LLM interactions behind internal `LLMProvider` interface. Pin SDK versions. Validate via automated contract tests in CI before upgrading. |
| **Unauthorized Testing** | Engineer inadvertently targets out-of-scope or third-party systems. | Gate 0 mandatory attestation. Domain allowlist enforced at network level. Target environment warnings (production flag). Hash-chained audit trail. |
| **Model Cost & Latency** | Expensive token usage or long exploration cycles. | Use compact ARIA accessibility snapshots instead of heavy screenshots. Implement step/token budgets and configurable depth limits. |

---

## 7. Run Folder Structure & Artifact Layout

Every run produces an isolated run folder inside the workspace (excluded from Git):

```
.qa-harness/runs/<run-id>/
    scope.json                  # Target URLs, allowed domains, environment, limits (Gate 0)
    requirement.md              # Normalized, redacted requirements
    redaction-report.json       # Masked tokens audit
    analysis.json               # Ambiguities, risks, clarification questions & answers
    site-profile.json           # Discovered pages, forms, interactive controls
    testcases/
        v1.json, v1.md          # Initial draft test cases (Appendix A format)
        v2.json, v2.md          # Revised test cases post-comments
    approvals.json              # Approver, timestamp, version, SHA-256 content hash (Gate 1)
    scripts/
        pages/                  # Page Object Model classes
        tests/                  # pytest Playwright test functions
    repair-log.json             # Dry-run locator/timing stabilization history
    results/
        results.json            # Structured execution results
        junit.xml               # Standard test execution report
    evidence/
        screenshots/            # Captured page states
        traces/                 # Playwright trace zip archives
        har/                    # Network HAR captures
        logs/                   # Console and network request logs
    report/
        report.html             # Self-contained HTML report (Jinja2 autoescaped, zero JS)
        report.md               # Markdown summary for issue trackers
        report.json             # Complete machine-readable report
    audit.jsonl                 # SHA-256 hash-chained tamper-evident audit trail
```

