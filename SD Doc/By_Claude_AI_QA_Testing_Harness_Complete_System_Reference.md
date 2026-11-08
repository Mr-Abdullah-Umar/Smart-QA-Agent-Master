# AI QA Testing Harness — Complete System Architecture & Implementation Reference

> **Companion file:** `AI_QA_Testing_Harness_Practical_Test_Plan.md` — the agent-executable test plan for this system.
>
> **Document Purpose:** This document is an exhaustive, self-contained technical specification of the entire **AI QA Testing Harness** codebase. It is designed specifically for AI coding agents and systems engineers to immediately understand the complete architecture, execution models, security controls, schemas, and file structures without needing to reverse-engineer individual modules.

---

## 1. System Mission & Core Tenets

The **AI QA Testing Harness** is a secure, deterministic, agentic testing system integrated into Visual Studio Code. It autonomously conducts web application requirement analysis, semantic exploration, test case drafting, Page Object Model (POM) script generation, sandboxed test execution, AI-driven failure investigation, and multi-format reporting.

### Core Non-Negotiable Tenets:
1. **Zero Guesswork / Evidence-Based:** The system never guesses or silently invents missing requirements. Unknowns or ambiguities are explicitly flagged as clarification questions. Every *observed fact* in a failure investigation must cite a verified on-disk evidence ID (`EV-001`). Hypotheses are kept in a separate section and are never presented as facts.
2. **Three Human Approval Gates:**
   - **Gate 0 (Scope Attestation):** Mandates an explicit authorization attestation (written to the audit trail) and strict domain allowlists before any browsing or AI processing of site content. Production-like targets are flagged and need extra confirmation.
   - **Gate 1 (Test Design Sign-off):** Cryptographically binds approved test cases to a SHA-256 hash. Modifying test cases downstream halts execution.
   - **Gate 2 (Defect Sign-off):** An AI investigation category (including `Product defect`) is only a proposal. A failure is never treated as a confirmed defect, and the run cannot be closed, until a human engineer records a decision. The harness does not create tickets in external trackers (out of scope in the design).
3. **Zero-Trust Security Sandbox:** Outbound requests are locked down via SSRF route interception (blocking loopback, RFC 1918, link-local, and cloud metadata). Script generation passes through a strict static-validation pipeline (AST parse, import allowlist, Ruff/Bandit, traceability and URL-literal checks) banning `eval`, `exec`, `subprocess`, `os`, `open`, and `time.sleep` and, per the design, dynamic imports, sockets/outbound-HTTP libraries, `ctypes`/`pickle`, and file access outside the run data folder. Webviews run with 128-bit cryptographic nonces. All actions are logged to a tamper-evident SHA-256 hash-chained audit trail (`audit.jsonl`).

---

## 2. High-Level Architecture & Dual-Process Design

The system is split into two cleanly decoupled components communicating exclusively over child process standard input/output (`stdio`) via line-delimited **JSON-RPC 2.0**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   VISUAL STUDIO CODE EXTENSION                         │
│  (TypeScript 5.4 / Node.js 20 - package.json, VSIX v0.1.0)             │
│                                                                        │
│  ┌───────────────────────┐          ┌───────────────────────────────┐  │
│  │ Activity Bar Webview  │          │ Security & SecretStorage      │  │
│  │ (CSP 128-bit Nonces,  │          │ (OS Keychain credential vault,│  │
│  │  Decision Cards, Chat)│          │  Workspace Trust enforcement) │  │
│  └──────────┬────────────┘          └───────────────┬───────────────┘  │
│             │                                       │                  │
│             └───────────────────┬───────────────────┘                  │
│                                 ▼                                      │
│                     ┌───────────────────────┐                          │
│                     │ Engine Supervisor     │                          │
│                     │ (RPC Client, Process  │                          │
│                     │  Tree Lifecycle)      │                          │
│                     └───────────┬───────────┘                          │
└─────────────────────────────────┼──────────────────────────────────────┘
                                  │ stdio (JSON-RPC 2.0 lines)
                                  │ NO TCP PORTS / NO LOCAL LISTENERS
┌─────────────────────────────────┼──────────────────────────────────────┐
│                                 ▼                                      │
│                     ┌───────────────────────┐                          │
│                     │ StdioChannel / RPC    │                          │
│                     │ Dispatcher (main.py)  │                          │
│                     └───────────┬───────────┘                          │
│                                 ▼                                      │
│                ┌──────────────────────────────────┐                    │
│                │ Orchestration State Machine      │                    │
│                │ (11 Stages, Gate 0, Gate 1, G2)  │                    │
│                └────────────────┬─────────────────┘                    │
│                                 ▼                                      │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      PYTHON QA ENGINE                            │  │
│  │  ┌────────────────────┐ ┌──────────────────┐ ┌────────────────┐  │  │
│  │  │ Security Subsystem │ │ Browser Profiler │ │ POM Generator  │  │  │
│  │  │ (SSRF, Redaction,  │ │ (ARIA Snapshots, │ │ & AST Security │  │  │
│  │  │  Confinement)      │ │  Policy Guard)   │ │  Validator)    │  │  │
│  │  └────────────────────┘ └──────────────────┘ └────────────────┘  │  │
│  │  ┌────────────────────┐ ┌──────────────────┐ ┌────────────────┐  │  │
│  │  │ Sandboxed Runner   │ │ AI Investigation │ │ Report Builder │  │  │
│  │  │ (Pytest Subproc,   │ │ (Appendix B RCA, │ │ (Zero-JS HTML, │  │  │
│  │  │  Flakiness/Retry)  │ │  Evidence Index) │ │  MD, XML, JSON)│  │  │
│  │  └────────────────────┘ └──────────────────┘ └────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│                       ISOLATED RUN DIRECTORY                           │
│               .qa-harness/runs/<run-id>/ (audit.jsonl)                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Complete Codebase Directory & File Inventory

```
Smart QA Agent master/
├── .github/workflows/
│   ├── ci.yml                     # Multi-OS CI (Python 3.10-3.12, Node 20, Pytest, TypeCheck)
│   └── security-scan.yml          # Automated Bandit, Ruff, Pip-Audit, Gitleaks, CycloneDX SBOM
├── docs/
│   ├── threat-model.md            # T1-T12 threat matrix, trust zones, and cryptographic audit spec
│   ├── spike-report.md            # Copilot SDK spike, deny-by-default handler, LLMProvider contract
│   ├── user-guide.md              # End-user operational manual, Gate workflows, SecretStorage setup
│   ├── runbooks.md                # Diagnostic runbooks for stdio, SSRF, Playwright, AST, audit triage
│   └── release-notes-v0.1.0.md    # Production release notes and verified SHA-256 package checksums
├── SD Doc/
│   ├── AI_QA_Testing_Harness_VSCode_Solution_Design.docx  # Original source solution design
│   ├── AI_QA_Testing_Harness_Implementation_Plan.md        # Master 9-phase execution plan
│   └── AI_QA_Testing_Harness_Complete_System_Reference.md  # THIS DOCUMENT
├── requirements.txt               # Root Python package dependencies
├── engine/
│   ├── pyproject.toml             # Ruff, Bandit, and Pytest configuration
│   ├── requirements.txt           # Engine package dependencies with pinned minimum versions
│   ├── qa_engine/
│   │   ├── __init__.py
│   │   ├── main.py                # JSON-RPC 2.0 stdio engine entrypoint
│   │   ├── security/
│   │   │   ├── __init__.py
│   │   │   ├── paths.py           # T4: Path traversal, symlink resolution & confinement
│   │   │   ├── redaction.py       # T6/T7: Regex scanner masking passwords, tokens, cards, emails
│   │   │   └── ssrf.py            # T5: Firewall blocking 127.0.0.1, RFC 1918, 169.254.169.254
│   │   ├── orchestrator/
│   │   │   ├── __init__.py
│   │   │   ├── audit.py           # Audit & accountability control: SHA-256 hash-chained audit logger
│   │   │   ├── run_store.py       # Isolated run folder lifecycle and atomic write utilities
│   │   │   ├── rpc.py             # JSON-RPC 2.0 protocol schemas, dispatcher, cross-platform stdio
│   │   │   ├── state_machine.py   # 11-stage workflow manager enforcing Gate 0, 1, and 2
│   │   │   └── review.py          # Test case revision loops, approval hashing, semantic diffing
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── provider.py        # Abstract LLMProvider contract and tool definitions
│   │   │   ├── mock_provider.py   # Deterministic offline mock provider for CI/CD
│   │   │   ├── copilot_provider.py# Copilot SDK provider with deny-by-default Appendix C tools
│   │   │   ├── schemas.py         # Pydantic models for structured analysis and questions
│   │   │   └── prompts/
│   │   │       ├── __init__.py
│   │   │       ├── analysis.py    # Requirement intake, ambiguity flagging, and risk analysis
│   │   │       └── test_design.py # Appendix A standard test case generator prompt
│   │   ├── browser/
│   │   │   ├── __init__.py
│   │   │   ├── policy.py          # T8: Action classifier (SAFE_READ, STATE_CHANGE, DESTRUCTIVE)
│   │   │   ├── snapshot.py        # Semantic ARIA accessibility tree extractor with [#1] indices
│   │   │   ├── tools.py           # GuardedBrowserSession with Playwright route interception
│   │   │   ├── profile.py         # SiteProfile aggregator for discovered pages, forms, errors
│   │   │   └── extended_checks.py # WCAG 2.1 AA a11y auditor, health, performance, security headers
│   │   ├── generation/
│   │   │   ├── __init__.py
│   │   │   ├── testcases.py       # Appendix A TestCase & TestCaseCollection with canonical hashing
│   │   │   ├── diff.py            # Side-by-side semantic diffing between testcase v1 and v2
│   │   │   ├── validator.py       # T2: AST security validator enforcing import & syntax allowlist
│   │   │   └── scriptgen.py       # Page Object Model & pytest test suite generator
│   │   ├── execution/
│   │   │   ├── __init__.py
│   │   │   ├── sandbox.py         # Stripped-environment process runner with timeouts (shell=False)
│   │   │   ├── runner.py          # Pytest runner parsing defusedxml JUnit & detecting flakiness
│   │   │   ├── dry_run.py         # Bounded locator stabilization (never modifies assertions)
│   │   │   └── policy_plugin.py   # Runtime SSRF route interception fixture for pytest
│   │   ├── investigation/
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py         # Appendix B RCA schemas (7 categories, facts vs hypotheses)
│   │   │   ├── evidence.py        # EvidenceIndex assigning EV-001 IDs and verifying disk presence
│   │   │   └── classifier.py      # FailureClassifier verifying evidence and Gate 2 sign-off
│   │   └── reporting/
│   │       ├── __init__.py
│   │       ├── builder.py         # ReportBuilder generating HTML, Markdown, JSON, and JUnit XML
│   │       └── templates/
│   │           ├── report.html.jinja2 # Self-contained, zero-JS, print-ready HTML template
│   │           └── report.md.jinja2   # Clean Markdown report template
│   └── tests/
│       ├── unit/                  # 14 unit test suites (paths, redaction, ssrf, audit, POM, etc.)
│       ├── integration/           # 2 integration suites (sandboxed runner, state machine)
│       └── security/              # 5 penetration test suites (injection, ssrf, ast, audit, pilot)
└── extension/
    ├── package.json               # VS Code extension manifest (commands, views, configuration)
    ├── tsconfig.json              # TypeScript compilation config
    ├── .vscodeignore              # Exclusion rules for VSIX bundle packaging
    ├── LICENSE.txt                # Apache 2.0 license
    ├── readme.md                  # Extension marketplace README
    ├── ai-qa-testing-harness-0.1.0.vsix # Distributable, signed VSIX bundle
    ├── test-integration.js        # E2E integration test: Node.js RPC client <-> Python engine
    ├── src/
    │   ├── extension.ts           # VS Code extension activation & command registration
    │   ├── engineClient.ts        # Child process manager with recursive process-tree termination
    │   ├── chatProvider.ts        # WebviewViewProvider managing chat stream, cards, and CSP
    │   ├── rpc/
    │   │   ├── protocol.ts        # JSON-RPC 2.0 TypeScript interfaces
    │   │   └── client.ts          # Line-buffered bidirectional JSON-RPC stdio client
    │   └── security/
    │       ├── csp.ts             # Cryptographic 128-bit base64 CSP nonce generator
    │       └── secretStorage.ts   # VS Code SecretStorage wrapper for encrypted credentials
    └── webview/
        ├── styles.css             # Decision cards, timeline breadcrumbs, dark/light theme CSS
        └── main.js                # Secure client-side controller posting messages to extension
```

---

## 4. The 11-Stage Workflow & Human Approval Gates

The state machine (`qa_engine/orchestrator/state_machine.py`) strictly enforces progression prerequisites. An illegal transition raises `StateTransitionError` and halts the pipeline.

```
Stage 0: STAGE_0_SCOPE         ──► [GATE 0: Scope Confirmed & Authorized]
Stage 1: STAGE_1_INTAKE        ──► PII and secret redaction
Stage 2: STAGE_2_ANALYSIS      ──► Ambiguity detection & clarification Q&A
Stage 3: STAGE_3_EXPLORATION   ──► Headless Playwright ARIA snapshot profiling
Stage 4: STAGE_4_TEST_DESIGN   ──► Appendix A schema testcase drafting
Stage 5: STAGE_5_REVIEW_LOOP   ──► [GATE 1: SHA-256 Approval Hash Binding]
Stage 6: STAGE_6_SCRIPT_GEN    ──► POM generator & AST security validation
Stage 7: STAGE_7_DRY_RUN       ──► Bounded locator stabilization (repairs locators only)
Stage 8: STAGE_8_EXECUTION     ──► Sandboxed pytest execution & retry flakiness check
Stage 9: STAGE_9_INVESTIGATION ──► Evidence indexing, Appendix B Root Cause Analysis & report generation (HTML/MD/JSON/JUnit)
Stage 10: STAGE_10_SIGN_OFF    ──► [GATE 2: Human defect decisions, sign-off & retest]
Terminal: COMPLETED / CANCELLED / ERROR
```

### The Three Mandatory Human Gates:
1. **Gate 0 (Scope Attestation):**
   - Occurs at Stage 0. The engineer must attest authorization to test the target and provide explicit domain allowlists.
   - Enforced by `confirm_scope(scope: ScopeModel)`. Rejects empty URLs, unauthorized flags, or malformed CIDRs. The design also requires a warning and extra confirmation when the environment is production-like (see Section 11, item 7).
2. **Gate 1 (Test Design Sign-off):**
   - Occurs at Stage 5. Computes a canonical SHA-256 hash of the normalized test case collection.
   - Enforced by `approve_testcases(version, approver, sha256_hash)`. Writes `approvals.json` and logs to `audit.jsonl`. Stages 6, 7, and 8 verify that this hash matches on disk before proceeding.
3. **Gate 2 (Product Defect Sign-off):**
   - Occurs at Stage 10. When a failure is classified by the RCA engine as `Product defect`, `requires_human_signoff` is set to `True`.
   - Enforced by `sign_off_gate_2(failure_id, approver, defect_confirmed, notes)`. Automated code cannot mark a failure as a confirmed defect, or close the run, until a human engineer signs off. (The harness never files tickets in external trackers.)

---

## 5. Security Architecture & Threat Mitigations (T1–T19)

Threat IDs follow the design document (Section 10.3). "Primary code location" is taken from the file inventory in Section 3; items marked *(verify)* are specified by the design but not explicitly documented in this reference.

| Threat ID | Threat Description | Architectural Mitigation | Primary code location |
| :--- | :--- | :--- | :--- |
| **T1: Prompt injection via pages, logs, requirements** | Malicious content steers the LLM to unsafe actions. | Web/log/requirement text is passed as quoted, size-capped data only. Tool dispatch is deny-by-default (Appendix C). Policy code, not the model, enforces scope. Outputs are schema-validated. Instruction-like content is flagged to the engineer. | `llm/copilot_provider.py`, `llm/prompts/`, `browser/tools.py` |
| **T2: Malicious or unsafe generated script** | Generated pytest scripts run shell commands, read private files, or contact external hosts. | `ASTSecurityValidator` parses the AST, allows only safe imports (`pytest`, `playwright`, `re`, `json`, `datetime`, plus run-local page objects) and bans dangerous constructs. Ruff + Bandit scans. Harness-owned fixtures are read-only to generated code. | `generation/validator.py`, `generation/scriptgen.py`, `execution/policy_plugin.py` |
| **T3: Command / argument injection** | A URL or file name is inserted into a command line (`; calc.exe`, `$(rm ...)`). | `SandboxedSubprocess`: `shell=False`, argument arrays only, stripped environment, strict validation of every value, no model-controlled command names. | `execution/sandbox.py`, `execution/runner.py` |
| **T4: Path traversal & symlink attacks** | Run IDs or filenames escape the run folder (`../../etc/passwd`). | `security/paths.py` resolves every path and verifies it stays inside `RunStore.run_dir`; symlinks pointing outside are rejected. No general file read/write tool for the model. | `security/paths.py`, `orchestrator/run_store.py` |
| **T5: SSRF / internal network access** | The harness reaches `127.0.0.1`, RFC 1918 ranges, or the cloud metadata address — directly or through a redirect. | `security/ssrf.py` allows only `http`/`https`, checks the domain allowlist on **every request and redirect hop**, and resolves DNS to block private, loopback, link-local and metadata ranges. Runtime route interception in the browser and in the pytest plugin. (DNS-rebinding is fully mitigated only by the optional local policy proxy.) | `security/ssrf.py`, `browser/tools.py`, `execution/policy_plugin.py` |
| **T6: Credential / secret leakage** | Passwords or API keys leak into prompts, logs, traces, HAR files or reports. | Secrets live only in VS Code `SecretStorage` (OS keychain). The model sees placeholders; the engine fills real values. `RedactionEngine` (patterns + entropy + exact configured secrets) scrubs prompts, logs, traces, HAR and reports. | `security/redaction.py`, `extension/src/security/secretStorage.ts` |
| **T7: Sensitive data sent to the AI service** | Page snapshots contain personal data that reaches the model. | Required data-classification declaration, redaction before every model call (`[REDACTED_CREDIT_CARD]`, `[REDACTED_EMAIL]`, etc.), snapshot truncation/data minimization, per-run record of what was sent. | `security/redaction.py`, `llm/prompts/` *(verify data-classification handling)* |
| **T8: Excessive agency / destructive actions** | The agent clicks *Delete account* or *Pay now*. | `ActionClassifier` labels actions `SAFE_READ`, `STATE_CHANGE` or `DESTRUCTIVE` (verbs such as `delete`, `drop`, `purge`); state-changing actions are blocked unless the scope allows them or the engineer approves a decision card. Read-mostly exploration, step/rate budgets. | `browser/policy.py` |
| **T9: Testing a system without authorization** | A user points the harness at a third-party site. | Gate 0 authorization attestation (logged), strict domain allowlist, production-like warning, rate limits, `robots.txt` respected by default. | `orchestrator/state_machine.py` (`confirm_scope`) |
| **T10: Tampering with the plan after approval** | Test cases or scripts change after sign-off. | SHA-256 hash of the normalized test-case set stored in `approvals.json`; verified before script generation, dry run and execution. A mismatch halts the run. | `generation/testcases.py`, `orchestrator/review.py`, `orchestrator/state_machine.py` |
| **T11: Webview script injection** | Malicious page text renders as active content in the chat. | Strict CSP with 128-bit base64 nonces, no inline script, no remote content, escaped dynamic content, restricted resource roots, schema validation of every message. | `extension/src/security/csp.ts`, `chatProvider.ts`, `webview/main.js` |
| **T12: Untrusted workspace** | A cloned repo contains a crafted configuration that triggers actions. | VS Code Workspace Trust respected; execution features disabled in untrusted workspaces; configuration validated and never executed as commands. | `extension/src/extension.ts`, `package.json` *(verify)* |
| **T13: Supply-chain compromise** | A malicious package version enters the build. | Pinned versions and hash-checked lock files, `pip-audit`/`npm audit`, CycloneDX SBOM, cooling-off period for new releases, signed release artifacts. | `engine/requirements.txt`, `.github/workflows/security-scan.yml` *(see Section 11, item 3)* |
| **T14: Report injection** | Page content with markup appears in the HTML report. | `ReportBuilder` uses Jinja2 `autoescape=True`; zero-JS invariant (no `<script>` tags); restrictive CSP in the report file. | `reporting/builder.py`, `reporting/templates/` |
| **T15: DoS to the target or host** | A runaway loop or excess parallelism overloads a site or the laptop. | Budgets for steps, pages, time and tokens; rate limits and concurrency caps; per-test/per-run timeouts; cancel kills the whole process tree. | `execution/sandbox.py`, scope limits |
| **T16: Model errors presented as facts** | The AI invents a requirement or a root cause. | Questions instead of assumptions; `EvidenceIndex` verification (no phantom `EV-` IDs); facts and hypotheses separated; human gates; assertions trace 100% to approved requirement IDs. | `investigation/evidence.py`, `investigation/classifier.py`, `llm/schemas.py` |
| **T17: Breaking changes in the preview SDK** | An SDK update changes behavior or permissions. | `LLMProvider` interface, pinned SDK version, contract tests, deterministic `MockProvider`. | `llm/provider.py`, `llm/mock_provider.py`, `docs/spike-report.md` |
| **T18: Hijack of the engine channel** | Another local process talks to the engine. | stdio only — no sockets, no listeners; engine is a child of the extension; every message validated. | `orchestrator/rpc.py`, `extension/src/engineClient.ts` |
| **T19: Leakage through logs or telemetry** | Verbose logs contain secrets or page data. | Structured logs with redaction, no third-party telemetry, retention/purge command. | `security/redaction.py`, `orchestrator/audit.py` *(verify purge command)* |

### Audit & accountability control (design §10.4)
`AuditLogger` writes an append-only `audit.jsonl`. Each entry carries the hash of the previous entry: `H_n = SHA-256(record_n ‖ H_(n-1))`, so any edited, deleted, inserted or reordered record fails verification. The design requires entries to record the scope, authorization attestation, approvals, every tool call (redacted arguments), every outbound domain, script-validation results, execution commands and results, plus the VS Code user, OS user, time and model used. The log is included in the report package.

---

## 6. Key Data Models & Schemas

### 6.1 Appendix A: Standard Test Case Schema
Located in: `engine/qa_engine/generation/testcases.py`

```python
class TestCase(BaseModel):
    tc_id: str                      # Unique ID, e.g. "TC-CHECKOUT-001"
    title: str                      # Short descriptive summary
    requirement_ref: str            # Traced requirement ID, e.g. "REQ-CHECKOUT-01"
    category: TestCaseCategory      # Functional positive, negative, boundary, UI, a11y, etc.
    priority: TestCasePriority      # P1 (Critical), P2 (Major), P3 (Minor), P4 (Trivial)
    priority_rationale: Optional[str] = None
    preconditions: List[str]        # Required preconditions
    test_data: Dict[str, Any]       # Inputs / payloads
    steps: List[str]                # User-centric test steps (no raw selectors)
    expected_result: str            # Observable success invariant
    postconditions: Optional[str] = None
    automation_candidate: bool = True
    automation_rationale: Optional[str] = None
    version: int = 1
    status: str = "draft"           # "draft", "approved", "rejected"
```
* **Integrity Hashing:** `TestCaseCollection.compute_sha256_hash()` normalizes all cases into canonical JSON (sorted keys, compact separators) and returns the SHA-256 hex digest.

### 6.2 Appendix B: Failure Investigation & Root Cause Analysis Schema
Located in: `engine/qa_engine/investigation/schemas.py`

```python
class FailureCategory(str, Enum):
    PRODUCT_DEFECT = "Product defect"           # Requires Gate 2 sign-off
    AUTOMATION_ISSUE = "Automation issue"       # Fragile locator, test syntax
    TEST_DATA_ISSUE = "Test data issue"         # Expired account, missing seed
    ENVIRONMENT_FAILURE = "Environment issue"   # 500 server crash, network drop
    UNCLEAR_REQUIREMENT = "Unclear requirement" # Spec ambiguity
    FLAKY = "Flaky"                             # Timing race, passed on retry
    INSUFFICIENT_EVIDENCE = "Insufficient evidence"

class InvestigationFact(BaseModel):
    statement: str
    evidence_id: str  # Must match a verified on-disk evidence item: "EV-001"

class InvestigationHypothesis(BaseModel):
    hypothesis: str
    supporting_indicators: List[str]

class InvestigationReport(BaseModel):
    failure_id: str
    tc_id: str
    category: FailureCategory
    confidence: float               # Range [0.0 - 1.0]
    facts: List[InvestigationFact]  # Facts citing verified Evidence IDs
    hypotheses: List[InvestigationHypothesis]
    evidence_citations: List[str]
    reproduction_steps: List[str]
    recommended_action: str
    preventive_measure: str
    requires_human_signoff: bool    # True if category == PRODUCT_DEFECT
    gate_2_signed_off: bool = False
    signed_off_by: Optional[str] = None
```
* **Design note (verify):** the design (§8.11, Appendix B) also calls for a *confidence level of low / medium / high with its rationale*, the *alternative categories considered*, and the *evidence that is missing*. The schema above uses a numeric `confidence` and has no explicit fields for those items. See Section 11, item 2.
* **Category semantics:** `category` is a *proposal*. Even `Product defect` is only confirmed when a human completes Gate 2.

### 6.3 Appendix C: Tools Exposed to the AI Model
Exactly **14 tools** are exposed (design Appendix C). Dispatch is deny-by-default: any other tool name is refused and logged. Every call passes through the policy layer, is logged with redacted arguments, and counts against the scope budgets.

| # | Tool | Purpose | Constraints |
| :-- | :--- | :--- | :--- |
| 1 | `read_requirement()` | Read the normalized requirement text. | Run folder only, read-only. |
| 2 | `get_site_profile()` | Return the current site profile. | Read-only, redacted. |
| 3 | `browser_navigate(url: str)` | Navigate to a URL. | Allowed domains only; address-range and redirect checks (SSRF); GET navigation. |
| 4 | `browser_snapshot()` | Return the semantic ARIA accessibility tree with `#1`, `#2` reference tags. | Redacted, size-capped, treated as data. |
| 5 | `browser_click(target: str, reason: str)` | Click an element by snapshot reference. | Reference must come from the latest snapshot; `ActionClassifier` applies. |
| 6 | `browser_fill(target: str, value: str, reason: str)` | Enter text into a form control. | Values are placeholders; the engine resolves secrets and never echoes them. |
| 7 | `browser_select(target: str, option: str, reason: str)` | Select a dropdown option. | Bounded values and timeouts. |
| 8 | `browser_press_key(key: str)` | Dispatch a key (`Enter`, `Tab`, `Escape`). | Bounded values. |
| 9 | `browser_wait_for(target: str, state: str)` | Wait for `visible` / `hidden`. | Bounded timeouts. |
| 10 | `browser_screenshot(name: str)` | Capture a page image into `evidence/screenshots/`. | Saved to the evidence folder only. |
| 11 | `submit_analysis(...)` | Return the requirement analysis. | Validated against the analysis schema. |
| 12 | `submit_testcases(...)` | Return or revise test cases. | Validated against the Appendix A schema. |
| 13 | `submit_scripts(...)` | Return generated scripts. | Written only to `scripts/tests/` and `scripts/pages/`, then statically validated. |
| 14 | `submit_investigation(...)` | Return a failure investigation. | Validated; evidence IDs must exist in the `EvidenceIndex`. |

**Explicitly NOT exposed:** shell/process execution, general file read/write, arbitrary HTTP, JavaScript evaluation in the page, access to the engineer's own browser profile/extensions, and environment-variable access.

---

## 7. JSON-RPC 2.0 Communication Protocol

The extension and engine communicate via newline-delimited JSON-RPC 2.0 over `stdio`.

### Registered Methods (documented as implemented):
| Method | Direction | Description | Parameters |
| :--- | :--- | :--- | :--- |
| `run.start` | VS Code ➔ Engine | Initializes new run folder and audit trail. | `{ run_id, workspace_root, start_url, allowed_domains, requirement_text }` |
| `run.scope.confirm` | VS Code ➔ Engine | Confirms Gate 0 attestation and domain list. | `{ scope: ScopeModel }` |
| `run.testcases.approve` | VS Code ➔ Engine | Confirms Gate 1 test case approval hash. | `{ version: int, approver: str, sha256_hash: str }` |
| `run.defect.signoff` | VS Code ➔ Engine | Confirms Gate 2 defect sign-off. | `{ failure_id: str, approver: str, defect_confirmed: bool, notes: str }` |
| `run.cancel` | VS Code ➔ Engine | Halts the active run and logs cancellation. | `{ reason: str }` |
| `run.resume` | VS Code ➔ Engine | Resumes existing run verifying audit hash. | `{ run_id: str, workspace_root: str }` |

### Additional requests specified by the design (Appendix D) — verify implementation:
| Method | Direction | Purpose |
| :--- | :--- | :--- |
| `run.answer` | VS Code ➔ Engine | Answer a clarification question (Stage 2). |
| `run.testcases.comment` | VS Code ➔ Engine | Submit comments / request changes (Gate 1 review loop). |
| `run.script.approve` | VS Code ➔ Engine | Approve generated scripts when the optional script review is enabled. |
| `run.action.approve` | VS Code ➔ Engine | Approve one destructive action. |

### Server-to-Client Notifications:
| Notification | Direction | Description | Parameters |
| :--- | :--- | :--- | :--- |
| `stage.update` | Engine ➔ VS Code | Broadcasts stage progression to UI breadcrumbs. | `{ run_id, stage, status, description }` |
| `card.show` | Engine ➔ VS Code | Presents human decision card in chat webview. | `{ card_type: "scope_card"\|"testcase_card", data: {...} }` (design also names clarification, script, failure and report cards) |
| `message.stream` | Engine ➔ VS Code | *(design-specified, verify)* Streams assistant text. | — |
| `progress.step` | Engine ➔ VS Code | *(design-specified, verify)* Reports a step in the timeline. | — |
| `error` | Engine ➔ VS Code | *(design-specified, verify)* Reports a refused action or failure with a safe message. | — |

**Protocol rules (design §6.3):** every message is validated against a schema on both sides; unknown methods and malformed messages are rejected and logged; the engine opens no network listener.

---

## 8. Run Directory Layout (`.qa-harness/runs/<run-id>/`)

Every execution is completely isolated inside `.qa-harness/runs/<run-id>/` (excluded from git). Workspace-level settings live in `.qa-harness/config.json` (design §11.2):

```
.qa-harness/runs/<run-id>/
├── scope.json                # Approved target URLs, allowed domains, environment, authorization record (Gate 0)
├── requirement.md            # Redacted, normalized requirement specification
├── redaction-report.json     # Audit of masked confidential tokens
├── analysis.json             # Ambiguities, regression risks, clarification questions
├── site-profile.json         # Discovered pages, interactive forms, accessibility landmarks
├── testcases/
│   ├── v1.json, v1.md        # Initial drafted test cases (Appendix A format)
│   └── v2.json, v2.md        # Revised test cases post-comments
├── approvals.json            # Approver, timestamp, version, SHA-256 hash (Gate 1)
├── scripts/
│   ├── pages/                # Page Object Model Python classes
│   │   ├── __init__.py
│   │   └── <page>.py
│   ├── tests/                # pytest test suites mapped via @pytest.mark.tc("TC-ID")
│   │   ├── __init__.py
│   │   └── test_functional.py
│   └── data/                 # Optional run-local test data (design §11.2)
├── repair-log.json           # Dry-run locator stabilization audit (assertions never changed)
├── results/
│   ├── results.json          # Machine-readable execution outcomes
│   └── junit.xml             # Standard test execution report (parsed with defusedxml)
├── evidence/
│   ├── evidence_index.json   # Verified catalog mapping EV-001 to files and SHA-256 hashes
│   ├── screenshots/          # Captured failure and milestone screenshots
│   ├── traces/               # Playwright interactive trace archives (.zip)
│   ├── har/                  # Network HTTP archive captures (.har)
│   └── logs/                 # Console exceptions and network request logs
├── report/
│   ├── report.html           # Self-contained, zero-JS HTML report (Jinja2 autoescaped)
│   ├── report.md             # Clean Markdown report for issue trackers
│   ├── report.json           # Consolidated machine-readable report
│   └── junit.xml             # Exported JUnit XML test suite
└── audit.jsonl               # Continuous SHA-256 hash-chained tamper-evident audit trail
```

---

## 9. Verification & Testing Evidence

When this reference was last updated, the engine test suite reported **115 passing tests** across unit, integration, and security penetration suites. Treat this as a historical figure and re-run to confirm — the count changes as tests are added.

### Test Execution Command:
```bash
# In the engine virtual environment, from the repository root:
pytest engine/tests -q
# or from the engine/ folder:
cd engine && pytest tests -q
```
*Last recorded result:* **`115 passed in 6.00s`**

### Security & Penetration Suites:
1. `engine/tests/security/test_prompt_injection.py`: Verifies resilience against indirect prompt injections and instructions attempting to bypass gates or write malicious code.
2. `engine/tests/security/test_ssrf_penetration.py`: Validates blocking of `127.0.0.1`, `[::1]`, `169.254.169.254`, `metadata.google.internal`, RFC 1918 subnets, and non-HTTP protocols (`file://`, `gopher://`).
3. `engine/tests/security/test_ast_evasion.py`: Tests that the `ASTSecurityValidator` rejects obfuscated `eval()`, `exec()`, `open()`, `time.sleep()`, and unauthorized imports.
4. `engine/tests/security/test_audit_tampering.py`: Validates that modified payloads, deleted entries, or reordered records in `audit.jsonl` are detected by the SHA-256 hash-chain verifier.
5. `engine/tests/security/test_pilot_evaluation.py`: Simulates an end-to-end e-commerce checkout QA lifecycle through all 11 stages and validates the objective, offline subset of the design's Section 13 success criteria:
   - **Traceability:** 100% of test cases traced to requirements.
   - **Gate Verification:** 100% cryptographic SHA-256 hash verification.
   - **Evidence Verification:** 100% of investigation facts cite valid on-disk evidence IDs.
   - **Report Security:** Zero `<script>` tags in generated HTML report.

---

## 10. Operational Guidelines for Future AI Agents

When interacting with, modifying, or extending this codebase, follow these rules:

1. **Windows Asyncio Execution:**
   - In sandboxed environments on Windows, `asyncio.ProactorEventLoop` can block on local `socket.socketpair()`. Run commands invoking pytest with asyncio or Chromium using `BypassSandbox: true`. (This is an option of the AI coding-agent tooling used while developing the harness — it is **not** a harness setting and must never be used to weaken the harness's own sandbox.)
2. **Standard Stdio Communication:**
   - The engine communicates via `loop.run_in_executor(None, sys.stdin.readline)` to avoid Windows IOCP named pipe handle bugs. Always flush stdout (`sys.stdout.flush()`) after emitting JSON-RPC lines.
3. **AST Validator Invariants:**
   - Never generate `time.sleep()` in test scripts. Always use web-first Playwright assertions (`expect(locator).to_be_visible()`).
   - Every generated test function must begin with `test_` and have a `@pytest.mark.tc("TC-ID")` decorator.
4. **Evidence-Based RCA:**
   - When generating root cause reports, every `InvestigationFact` must cite an `evidence_id` that exists in the `EvidenceIndex`. Never generate phantom evidence IDs.
5. **Report Template Safety:**
   - In `qa_engine/reporting/builder.py`, `Environment(loader=..., autoescape=True)` must remain enabled. Never permit `<script>` tags in `report.html.jinja2`.

---

## 11. Known Deviations & Items To Verify

The design document (v1.0, 7 November 2026) is the source of truth for intended behavior. The items below are places where this reference, the design, or the documented code surface do not fully line up. They are verified by `AI_QA_Testing_Harness_Practical_Test_Plan.md` (suite 0 and the suites named below).

| # | Item | What to check |
| :-- | :--- | :--- |
| 1 | **Threat IDs** | `docs/threat-model.md` in the repository may use a different T-numbering (an earlier draft of this reference used T1–T12 with different meanings for T9, T11, T12). Align it with the design's T1–T19. |
| 2 | **Investigation schema** | Design requires confidence **low/medium/high + rationale**, alternatives, and missing evidence; the documented schema has a numeric `confidence` only. Decide: map float → label, or add the fields. |
| 3 | **Dependency pinning** | Design requires a hash-pinned lock file (`requirements.lock`); the inventory lists `requirements.txt` with *minimum* versions. Check for `--hash=sha256:` entries and exact pins (T13). |
| 4 | **RPC surface** | `run.answer`, `run.testcases.comment`, `run.script.approve`, `run.action.approve`, `message.stream`, `progress.step` and `error` are in the design but not in the documented method list. Confirm each is implemented or record the gap. |
| 5 | **Tool registry** | Confirm all 14 Appendix C tools are registered (including `read_requirement`, `get_site_profile`, and the four `submit_*` tools) and that nothing else is. |
| 6 | **`security/secrets.py`** | The design's layout lists it; the inventory does not. Confirm where exact-match secret redaction/resolution lives. |
| 7 | **Optional / policy features** | Production-environment warning, `respect_robots`, `rate_limit_rps`, `max_pages`/`max_steps` budgets, `data_classification`, optional script-review gate, destructive-action approval card, hardened container mode, optional policy proxy, retention/purge command, slash commands (`/new /scope /plan /run /report /resume /cancel /settings`), in-extension audit-log viewer. Confirm which exist. |
| 8 | **Workspace Trust** | Confirm `package.json` declares untrusted-workspace behavior and the extension disables execution features when `vscode.workspace.isTrusted` is false (T12). |
| 9 | **VSIX signing** | The inventory calls the VSIX "signed"; confirm against `docs/release-notes-v0.1.0.md` checksums and the release process. |

---

## 12. Revision History

| Revision | Date | Change |
| :--- | :--- | :--- |
| 1 | — | Initial reference generated from the codebase. |
| 2 | 8 November 2026 | Corrected against the Solution Design v1.0: threat IDs T1–T19 realigned; tool contract expanded from 8 to the 14 Appendix C tools; RPC surface extended with design-specified messages; Gate 0/Gate 2 wording corrected (no ticket creation, category is a proposal); "every fact" (not "every statement") must cite evidence; AST allowlist/banned constructs completed; redirect/DNS-rebinding note added to SSRF; Stage 9/10 descriptions corrected; run-directory layout completed; machine-specific `file:///c:/Users/...` links replaced with repo-relative paths; test count labelled as a historical figure; Section 11 (deviations to verify) added. |
