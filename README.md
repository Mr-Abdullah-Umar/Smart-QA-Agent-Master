# Smart QA Agent: AI QA Testing Harness for Visual Studio Code

[![CI](https://github.com/Mr-Abdullah-Umar/Smart-QA-Agent-Master/actions/workflows/ci.yml/badge.svg)](https://github.com/Mr-Abdullah-Umar/Smart-QA-Agent-Master/actions/workflows/ci.yml)
[![Security Scan](https://github.com/Mr-Abdullah-Umar/Smart-QA-Agent-Master/actions/workflows/security-scan.yml/badge.svg)](https://github.com/Mr-Abdullah-Umar/Smart-QA-Agent-Master/actions/workflows/security-scan.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![VS Code Extension](https://img.shields.io/badge/VS%20Code-^1.88.0-blue)](https://marketplace.visualstudio.com/)

An enterprise-grade, deterministic AI QA Testing Harness built as a Visual Studio Code extension coupled with a sandboxed Python reasoning and test execution engine.

---

## 🌟 Key Highlights

- **11-Stage Deterministic Workflow:** From requirement intake to semantic web exploration, Page Object Model (POM) test generation, sandboxed execution, and Root Cause Analysis.
- **Three Human Approval Gates:**
  - **Gate 0 (Scope Attestation):** Enforces legal authorization checkboxes and strict domain allowlists before any network navigation is allowed.
  - **Gate 1 (Test Design Sign-off):** Cryptographically binds approved test cases to a SHA-256 content hash. Downstream execution halts if test cases are altered.
  - **Gate 2 (Product Defect Sign-off):** An AI proposal of a `Product defect` requires explicit human engineer confirmation before bug tickets are recorded.
- **Zero-Trust Security & Network Firewalls:**
  - **SSRF & DNS Rebinding Protection:** Blocks access to loopback (`127.0.0.1`), RFC 1918 private subnets, link-local, and cloud metadata (`169.254.169.254`).
  - **AST Security Validator:** Statically analyzes generated test scripts to block `eval()`, `exec()`, `os`, `subprocess`, raw sockets, and `time.sleep()`.
  - **Confidential Redaction:** Automatically scrubs passwords, API tokens, and PII before submitting prompts to the LLM.
  - **Tamper-Evident Audit Trail:** Every event, approval, and tool call is sealed into a SHA-256 hash-chain (`audit.jsonl`).
- **Semantic ARIA Exploration:** Explores web applications using accessibility trees with unique indexed tags (`#1`, `#2`)—eliminating fragile pixel guessing and brittle CSS selectors.
- **Multi-Format Reports:** Generates self-contained, **zero-JavaScript** HTML reports, Markdown summaries, JUnit XML, and canonical JSON.

---

## 📂 Repository Structure

```
Smart-QA-Agent-Master/
├── .github/workflows/
│   ├── ci.yml                     # Multi-OS CI (Python 3.10-3.12, Node 20, Pytest)
│   └── security-scan.yml          # Automated Bandit, Ruff, pip-audit, Gitleaks, CycloneDX SBOM
├── docs/
│   ├── threat-model.md            # Threat model (T1-T19) & security boundaries
│   ├── spike-report.md            # Copilot SDK spike & LLMProvider contract
│   ├── user-guide.md              # Complete end-user operational manual
│   ├── runbooks.md                # Diagnostic runbooks for stdio, SSRF, and triage
│   └── release-notes-v0.1.0.md    # Production release notes & package checksums
├── SD Doc/
│   ├── AI_QA_Testing_Harness_VSCode_Solution_Design.docx  # Source solution design
│   ├── AI_QA_Testing_Harness_Implementation_Plan.md        # 9-phase master plan
│   └── complete_system_architecture_whole_system_test_plan.md # Exhaustive architecture & test plan
├── engine/                        # Python QA Automation Engine
│   ├── pyproject.toml             # Ruff, Bandit, pytest configuration
│   ├── requirements.txt           # Pinned engine dependencies
│   ├── qa_engine/                 # Core engine package
│   │   ├── main.py                # JSON-RPC 2.0 stdio server entry point
│   │   ├── browser/               # Playwright crawler, ARIA snapshots, a11y checks
│   │   ├── execution/             # Sandboxed runner, dry run, flakiness detection
│   │   ├── generation/            # POM script generator, AST security validator
│   │   ├── investigation/         # Evidence indexer, 7-class RCA failure classifier
│   │   ├── llm/                   # Abstract provider, mock provider, schemas, prompts
│   │   ├── orchestrator/          # 11-stage state machine, audit hash-chain, RPC
│   │   ├── reporting/             # Report builder, zero-JS HTML/Markdown templates
│   │   └── security/              # SSRF firewall, PII redaction, path confinement
│   └── tests/                     # 115 passing unit, integration & security penetration tests
├── extension/                     # VS Code TypeScript Extension
│   ├── package.json               # Extension manifest, commands & configuration
│   ├── tsconfig.json              # TypeScript configuration
│   ├── src/                       # TypeScript sources (chat provider, RPC client, CSP)
│   ├── webview/                   # Webview UI (decision cards, timeline, styles)
│   ├── test-integration.js        # Node.js <-> Python stdio RPC integration test
│   └── ai-qa-testing-harness-0.1.0.vsix # Packaged VSIX extension bundle
├── requirements.txt               # Root dependencies
└── .gitignore                     # Git ignore rules
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
* **OS:** Windows 10/11, macOS 12+, or Linux (Ubuntu 20.04+).
* **VS Code:** Version `^1.88.0` or higher.
* **Python:** Version `3.10`, `3.11`, or `3.12`.
* **Node.js:** Version `20.x` or higher.

### 2. Set Up Python Engine
```bash
cd engine
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 3. Build & Install the VS Code Extension
```bash
cd extension
npm install
npm run compile
npm run package

# Install into VS Code:
code --install-extension ai-qa-testing-harness-0.1.0.vsix
```

### 4. Running the Complete Test Suite
```bash
# In the engine virtual environment:
pytest engine/tests -v --tb=short

# Run static security and lint checks:
ruff check engine/qa_engine engine/tests
bandit -r engine/qa_engine -c engine/pyproject.toml

# Run the extension integration test:
node extension/test-integration.js
```
*(All 115 tests passing across unit, integration, and security penetration suites).*

---

## 🔒 Security Architecture

The harness adheres to a strict Zero-Trust model:
1. **SSRF Guardrails:** All HTTP/HTTPS traffic is verified against domain allowlists and validated against private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`).
2. **AST Static Code Guard:** Any AI-generated code attempting to access OS utilities, file systems, or network sockets is rejected before write or execution.
3. **Webview CSP Nonces:** Every VS Code webview turn uses a 128-bit cryptographic nonce to block script injections.
4. **Secret Vault:** Test credentials are saved securely in the OS keychain via VS Code `SecretStorage` and never exposed in plain text to the LLM.

---

## 📄 Documentation Links
* [User Guide](docs/user-guide.md)
* [Operational Runbooks](docs/runbooks.md)
* [Threat Model & Security Specifications](docs/threat-model.md)
* [Full System Architecture & Master Test Plan](SD%20Doc/complete_system_architecture_whole_system_test_plan.md)
* [Release Notes v0.1.0](docs/release-notes-v0.1.0.md)

---

## 📜 License
Distributed under the Apache 2.0 License. See `extension/LICENSE.txt` for details.
