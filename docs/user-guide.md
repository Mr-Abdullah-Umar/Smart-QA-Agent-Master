# AI QA Testing Harness - User Guide

The **AI QA Testing Harness** is an enterprise-grade extension for Visual Studio Code paired with a deterministic, policy-guarded Python automation engine. It automates web application exploratory testing, test case design, Page Object Model (POM) script generation, sandboxed execution, root-cause investigation, and reporting without pixel guessing, brittle locators, or unauthorized testing.

---

## 1. System Requirements & Prerequisites

* **Operating System:** Windows 10/11, macOS 12+, or modern Linux (Ubuntu 20.04+).
* **Visual Studio Code:** Version `^1.88.0` or higher.
* **Python Runtime:** Python `3.10`, `3.11`, or `3.12`.
* **Playwright Chromium:** Headless browser binaries installed via Playwright CLI.

---

## 2. Installation & Quick Start

### Step 1: Install the VS Code Extension
Install the pre-built `.vsix` package:
```bash
code --install-extension extension/ai-qa-testing-harness-0.1.0.vsix
```

### Step 2: Configure the Python Engine Virtual Environment
From the repository root or `engine/` folder:
```bash
cd engine
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### Step 3: Configure Extension Settings (Optional)
In VS Code Settings (`Ctrl+,` or `Cmd+,`), search for **QA Harness**:
* `qaHarness.pythonPath`: Custom absolute path to Python interpreter (defaults automatically to `.venv/Scripts/python.exe` or `.venv/bin/python`).
* `qaHarness.requireScriptApproval`: Set to `true` if you wish to inspect and approve generated pytest code before test execution.

---

## 3. Workflow & The Three Human Approval Gates

The QA Harness executes an 11-stage deterministic workflow governed by three strict Human Approval Gates:

```
[Stage 0: Scope Card] --> [GATE 0: Human Attestation]
         │
[Stage 1: Intake & PII Redaction]
         │
[Stage 2: Analysis & Clarifications]
         │
[Stage 3: ARIA Semantic Exploration]
         │
[Stage 4: Appendix A Test Design]
         │
[Stage 5: Review Loop] --> [GATE 1: SHA-256 Approval Hash]
         │
[Stage 6: POM Script Gen & AST Validation]
         │
[Stage 7: Dry Run Locator Stabilization]
         │
[Stage 8: Sandboxed Execution & Retries]
         │
[Stage 9: AI Failure Investigation & Evidence]
         │
[Stage 10: Sign-Off] --> [GATE 2: Human Defect Confirmation]
         │
[Multi-Format Reporting: Zero-JS HTML, Markdown, JSON, JUnit XML]
```

### Gate 0: Scope Attestation & Legal Authorization
* **Trigger:** Click the **QA Assistant** beaker icon in the Activity Bar, then click **Start New Run** (or run `QA Harness: Start New Run`).
* **Requirements:**
  1. Specify the Target Start URL (e.g., `https://staging.myapp.com`).
  2. Define the explicit Domain Allowlist (e.g., `staging.myapp.com, cdn.myapp.com`).
  3. Select Environment tier (`development`, `staging`, `production`).
  4. **Mandatory Checkbox:** *"I attest that I am authorized to test this target URL."*
* **Security Control:** SSRF and DNS rebinding protections abort any outbound traffic outside approved domains or targeting internal IP ranges (`127.0.0.1`, RFC 1918, `169.254.169.254`).

### Gate 1: Test Case Review & Cryptographic Hash Binding
* **Trigger:** Following exploratory profiling, the engine drafts structured test cases adhering to Appendix A.
* **Review Interface:**
  - View test cases with priority, preconditions, steps, and expected results.
  - Submit comments or request revisions (triggers semantic diffing between `v1` and `v2`).
  - Click **Approve Test Cases**.
* **Integrity Guarantee:** Approval records a SHA-256 hash in `approvals.json` and the tamper-evident audit log. If test cases are modified downstream, the engine halts execution.

### Gate 2: Product Defect Human Sign-Off
* **Trigger:** When a test failure occurs during execution, the AI Investigation engine conducts Root Cause Analysis (RCA) conforming to Appendix B.
* **Review Interface:**
  - Observed facts are strictly segregated from hypotheses.
  - Every fact cites a verified on-disk evidence ID (`[EV-001]`).
  - If classified as `Product defect`, the test result **CANNOT** automatically file a bug ticket until a human QA engineer checks the evidence and explicitly confirms the defect.

---

## 4. Test Credentials & Secret Management

Sensitive test credentials (passwords, API tokens) must **never** be hardcoded in scripts or pasted into LLM prompts.

1. Run command: `Ctrl+Shift+P > QA Harness: Store Test Credentials`.
2. Enter the key name (e.g. `TEST_ADMIN_PASSWORD`) and value.
3. Credentials are saved encrypted into the OS keychain using VS Code's `SecretStorage`.
4. The Python engine automatically references credentials through fixtures, and the PII Redaction scanner masks secrets prior to sending prompts to the LLM.

---

## 5. Artifacts and Reports

Every run produces an isolated run directory in `.qa-harness/runs/<run-id>/`:

| Artifact Path | Description |
| :--- | :--- |
| `report/report.html` | Self-contained, zero-JavaScript HTML report. CSP-compliant with print stylesheet. |
| `report/report.md` | Markdown report formatted for GitHub/GitLab pull requests or issues. |
| `report/report.json` | Complete machine-readable test execution and failure investigation data. |
| `report/junit.xml` | Standard JUnit XML format compatible with GitHub Actions, GitLab CI, and Jenkins. |
| `evidence/` | Raw screenshots, Playwright trace zip files, network HAR files, and logs. |
| `audit.jsonl` | Tamper-evident SHA-256 hash-chained log recording all actions and gate sign-offs. |

