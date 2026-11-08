# AI QA Testing Harness — Complete System Architecture & Implementation Reference

> **Document Purpose:** This document is an exhaustive, self-contained technical specification of the entire **AI QA Testing Harness** codebase. It is designed specifically for AI coding agents and systems engineers to immediately understand the complete architecture, execution models, security controls, schemas, and file structures without needing to reverse-engineer individual modules.

---

## 1. System Mission & Core Tenets

The **AI QA Testing Harness** is a secure, deterministic, agentic testing system integrated into Visual Studio Code. It autonomously conducts web application requirement analysis, semantic exploration, test case drafting, Page Object Model (POM) script generation, sandboxed test execution, AI-driven failure investigation, and multi-format reporting.

### Core Non-Negotiable Tenets:
1. **Zero Guesswork / Evidence-Based:** The system never guesses or silently invents missing requirements. Unknowns or ambiguities are explicitly flagged as clarification questions. Every statement in a failure investigation must cite a verified on-disk evidence ID (`[EV-001]`).
2. **Three Human Approval Gates:**
   - **Gate 0 (Scope Attestation):** Mandates explicit legal authorization and strict domain allowlists before any network traffic is initiated.
   - **Gate 1 (Test Design Sign-off):** Cryptographically binds approved test cases to a SHA-256 hash. Modifying test cases downstream halts execution.
   - **Gate 2 (Defect Sign-off):** An AI investigation classification of `Product defect` cannot log a bug or finalize downstream state without human engineer confirmation.
3. **Zero-Trust Security Sandbox:** Outbound requests are locked down via SSRF route interception (blocking loopback, RFC 1918, link-local, and cloud metadata). Script generation passes through strict AST security pipelines banning `eval`, `exec`, `subprocess`, `os`, `open`, and `time.sleep`. Webviews run with 128-bit cryptographic nonces. All actions are logged to a tamper-evident SHA-256 hash-chained audit trail (`audit.jsonl`).

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
│   │   │   ├── audit.py           # T11/T12: SHA-256 continuous hash-chained audit logger
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
│   │   │   ├── validator.py       # T3: AST security validator enforcing import & syntax allowlist
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
Stage 9: STAGE_9_INVESTIGATION ──► Evidence indexing & Appendix B Root Cause Analysis
Stage 10: STAGE_10_SIGN_OFF    ──► [GATE 2: Human Sign-off on Product Defects]
Terminal: COMPLETED / CANCELLED / ERROR
```

### The Three Mandatory Human Gates:
1. **Gate 0 (Scope Attestation):**
   - Occurs at Stage 0. The engineer must attest authorization to test the target and provide explicit domain allowlists.
   - Enforced by `confirm_scope(scope: ScopeModel)`. Rejects empty URLs, unauthorized flags, or malformed CIDRs.
2. **Gate 1 (Test Design Sign-off):**
   - Occurs at Stage 5. Computes a canonical SHA-256 hash of the normalized test case collection.
   - Enforced by `approve_testcases(version, approver, sha256_hash)`. Writes `approvals.json` and logs to `audit.jsonl`. Stages 6, 7, and 8 verify that this hash matches on disk before proceeding.
3. **Gate 2 (Product Defect Sign-off):**
   - Occurs at Stage 10. When a failure is classified by the RCA engine as `Product defect`, `requires_human_signoff` is set to `True`.
   - Enforced by `sign_off_gate_2(failure_id, approver, defect_confirmed, notes)`. Automated systems cannot log bug tickets until a human engineer signs off.

---

## 5. Security Architecture & Threat Mitigations (T1–T12)

| Threat ID | Threat Description | Architectural Mitigation in Codebase |
| :--- | :--- | :--- |
| **T1: Prompt Injection from Targets** | Malicious site content steers LLM to unsafe actions. | Web content is treated strictly as data. Tool dispatch uses deny-by-default allowlist (`Appendix C`). |
| **T2: Malicious Code in Test Scripts** | Generated pytest scripts execute arbitrary shell/network calls. | `ASTSecurityValidator` parses AST, allows only safe modules (`pytest`, `playwright`, `json`), and bans dangerous constructs. |
| **T3: Command Injection via Runner** | Subprocess invocation executes shell commands (`calc.exe`, `rm`). | `SandboxedSubprocess` enforces `shell=False`, stripped environment variables, and strict argument arrays. |
| **T4: Path Traversal & Symlink Attacks** | Run IDs or filenames escape the run folder (`../../etc/passwd`). | `qa_engine/security/paths.py` verifies all paths resolve strictly within `RunStore.run_dir`. Symlinks targeting outside are blocked. |
| **T5: Server-Side Request Forgery (SSRF)** | Harness accesses internal resources (`127.0.0.1`, metadata IP). | `qa_engine/security/ssrf.py` validates schemes (`http`/`https` only), checks domain allowlists, and resolves DNS to block private IP ranges. |
| **T6: Credential / Secret Leakage** | Passwords or API keys leak into prompts, reports, or logs. | Secrets stored encrypted in OS keychain via `SecretStorage`. `RedactionEngine` scrubs high-entropy tokens and PII before LLM calls. |
| **T7: PII Exposure in Test Artifacts** | Customer names, emails, card numbers written to reports. | `RedactionEngine` replaces credit cards and emails with `[REDACTED_CREDIT_CARD]` and `[REDACTED_EMAIL]`. |
| **T8: Destructive Action Execution** | Agent deletes data or triggers irreversible state changes. | `ActionClassifier` flags destructive verbs (`delete`, `drop`, `purge`) as `DESTRUCTIVE`, blocking them unless approved by human decision card. |
| **T9: Hallucinated / Phantom Assertions** | Model generates assertions for unspecified behavior. | Strict Gate 1 sign-off binds tests to approved acceptance criteria. Assertions must trace 100% to requirement IDs. |
| **T10: Unauthorized Post-Approval Edits** | Test scripts or cases altered after engineer sign-off. | Cryptographic SHA-256 hash in `approvals.json` validated prior to execution. Discrepancy halts execution immediately. |
| **T11: Audit Trail Repudiation** | Attacker or rogue process alters logs to cover actions. | `AuditLogger` generates continuous SHA-256 hash-chain ($H_n = \text{SHA-256}(\text{record}_n \parallel H_{n-1})$). Any edits fail verification. |
| **T12: Webview Code Execution (XSS)** | Malicious report HTML executes script in VS Code context. | `ReportBuilder` enforces zero-JS invariant (zero `<script>` tags). Extension webview uses strict CSP with 128-bit base64 nonces. |

---

## 6. Key Data Models & Schemas

### 6.1 Appendix A: Standard Test Case Schema
Located in: [`engine/qa_engine/generation/testcases.py`](file:///c:/Users/Abdullah/Desktop/Smart%20QA%20Agent%20master/engine/qa_engine/generation/testcases.py)

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
Located in: [`engine/qa_engine/investigation/schemas.py`](file:///c:/Users/Abdullah/Desktop/Smart%20QA%20Agent%20master/engine/qa_engine/investigation/schemas.py)

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

### 6.3 Appendix C: Deterministic Browser Automation Tool Contract
The following 8 tools are exposed to the AI model with strict parameter schemas:
1. `browser_navigate(url: str)`: Navigates to approved URL, enforcing SSRF controls.
2. `browser_snapshot()`: Extracts semantic ARIA accessibility tree with `#1`, `#2` reference tags.
3. `browser_click(target: str, reason: str)`: Clicks an element by ARIA index or semantic role.
4. `browser_fill(target: str, value: str, reason: str)`: Enters text into form controls.
5. `browser_select(target: str, option: str, reason: str)`: Selects dropdown option.
6. `browser_press_key(key: str)`: Dispatches keyboard events (`Enter`, `Tab`, `Escape`).
7. `browser_wait_for(target: str, state: str)`: Waits for element state (`visible`, `hidden`).
8. `browser_screenshot(name: str)`: Captures page image into `evidence/screenshots/`.

---

## 7. JSON-RPC 2.0 Communication Protocol

The extension and engine communicate via newline-delimited JSON-RPC 2.0 over `stdio`.

### Registered Methods:
| Method | Direction | Description | Parameters |
| :--- | :--- | :--- | :--- |
| `run.start` | VS Code ➔ Engine | Initializes new run folder and audit trail. | `{ run_id, workspace_root, start_url, allowed_domains, requirement_text }` |
| `run.scope.confirm` | VS Code ➔ Engine | Confirms Gate 0 attestation and domain list. | `{ scope: ScopeModel }` |
| `run.testcases.approve` | VS Code ➔ Engine | Confirms Gate 1 test case approval hash. | `{ version: int, approver: str, sha256_hash: str }` |
| `run.defect.signoff` | VS Code ➔ Engine | Confirms Gate 2 defect sign-off. | `{ failure_id: str, approver: str, defect_confirmed: bool, notes: str }` |
| `run.cancel` | VS Code ➔ Engine | Halts the active run and logs cancellation. | `{ reason: str }` |
| `run.resume` | VS Code ➔ Engine | Resumes existing run verifying audit hash. | `{ run_id: str, workspace_root: str }` |

### Server-to-Client Notifications:
| Notification | Direction | Description | Parameters |
| :--- | :--- | :--- | :--- |
| `stage.update` | Engine ➔ VS Code | Broadcasts stage progression to UI breadcrumbs. | `{ run_id, stage, status, description }` |
| `card.show` | Engine ➔ VS Code | Presents human decision card in chat webview. | `{ card_type: "scope_card"\|"testcase_card", data: {...} }` |

---

## 8. Run Directory Layout (`.qa-harness/runs/<run-id>/`)

Every execution is completely isolated inside `.qa-harness/runs/<run-id>/` (excluded from git):

```
.qa-harness/runs/<run-id>/
├── scope.json                # Approved target URLs, allowed domains, environment (Gate 0)
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
│   └── tests/                # pytest test suites mapped via @pytest.mark.tc("TC-ID")
│       ├── __init__.py
│       └── test_functional.py
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

The test suite consists of **115 passing tests** across unit, integration, and security penetration suites.

### Test Execution Command:
```bash
# In engine virtual environment:
pytest engine/tests -q
```
*Result:* **`115 passed in 6.00s`**

### Security & Penetration Suites:
1. `engine/tests/security/test_prompt_injection.py`: Verifies resilience against indirect prompt injections and instructions attempting to bypass gates or write malicious code.
2. `engine/tests/security/test_ssrf_penetration.py`: Validates blocking of `127.0.0.1`, `[::1]`, `169.254.169.254`, `metadata.google.internal`, RFC 1918 subnets, and non-HTTP protocols (`file://`, `gopher://`).
3. `engine/tests/security/test_ast_evasion.py`: Tests that the `ASTSecurityValidator` rejects obfuscated `eval()`, `exec()`, `open()`, `time.sleep()`, and unauthorized imports.
4. `engine/tests/security/test_audit_tampering.py`: Validates that modified payloads, deleted entries, or reordered records in `audit.jsonl` are detected by the SHA-256 hash-chain verifier.
5. `engine/tests/security/test_pilot_evaluation.py`: Simulates an end-to-end e-commerce checkout QA lifecycle through all 11 stages and validates Section 13 benchmarks:
   - **Traceability:** 100% of test cases traced to requirements.
   - **Gate Verification:** 100% cryptographic SHA-256 hash verification.
   - **Evidence Verification:** 100% of investigation facts cite valid on-disk evidence IDs.
   - **Report Security:** Zero `<script>` tags in generated HTML report.

---

## 10. Operational Guidelines for Future AI Agents

When interacting with, modifying, or extending this codebase, follow these rules:

1. **Windows Asyncio Execution:**
   - In sandboxed environments on Windows, `asyncio.ProactorEventLoop` can block on local `socket.socketpair()`. Run commands invoking pytest with asyncio or Chromium using `BypassSandbox: true`.
2. **Standard Stdio Communication:**
   - The engine communicates via `loop.run_in_executor(None, sys.stdin.readline)` to avoid Windows IOCP named pipe handle bugs. Always flush stdout (`sys.stdout.flush()`) after emitting JSON-RPC lines.
3. **AST Validator Invariants:**
   - Never generate `time.sleep()` in test scripts. Always use web-first Playwright assertions (`expect(locator).to_be_visible()`).
   - Every generated test function must begin with `test_` and have a `@pytest.mark.tc("TC-ID")` decorator.
4. **Evidence-Based RCA:**
   - When generating root cause reports, every `InvestigationFact` must cite an `evidence_id` that exists in the `EvidenceIndex`. Never generate phantom evidence IDs.
5. **Report Template Safety:**
   - In `qa_engine/reporting/builder.py`, `Environment(loader=..., autoescape=True)` must remain enabled. Never permit `<script>` tags in `report.html.jinja2`.

