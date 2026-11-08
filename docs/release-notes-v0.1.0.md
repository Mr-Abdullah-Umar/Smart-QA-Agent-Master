# Release Notes - AI QA Testing Harness v0.1.0

**Release Date:** November 8, 2026  
**Status:** Certified & Production-Ready  
**Distribution Bundle:** `extension/ai-qa-testing-harness-0.1.0.vsix`  
**SHA-256 Checksum:** `BEC0DB8E1ED103F52DC45311B36C43BBB877B29BF93ACF126CFD4241726052B0`  

---

## 1. Executive Summary

Version 0.1.0 delivers the full implementation of the **AI QA Testing Harness for Visual Studio Code**, fulfilling 100% of the specifications from the *Solution Design Document* across all 9 planned phases (Phase 0 through Phase 8).

The harness couples an ergonomic TypeScript VS Code extension with a sandboxed Python reasoning and execution engine. It automates web application intake, semantic exploration, test case drafting, Page Object Model (POM) script generation, sandboxed execution, root-cause investigation, and multi-format reporting with zero pixel guessing, zero brittle locators, and zero unauthorized execution.

---

## 2. Delivered Core Capabilities

### Phase 0: Foundation & Threat Matrix
* Implemented threat matrix covering 12 distinct attack vectors (T1–T12).
* Automated CI/CD security workflows (`.github/workflows/ci.yml`, `security-scan.yml`) with Ruff, Bandit, pip-audit, and Gitleaks.
* Evaluated preview Copilot SDK and isolated model interactions behind `LLMProvider`.

### Phase 1: Python Engine Core & JSON-RPC Orchestrator
* Clean stdio line-delimited JSON-RPC 2.0 communication layer.
* 11-stage deterministic state machine strictly enforcing progression prerequisites.
* Tamper-evident SHA-256 hash-chained audit trail (`audit.jsonl`).

### Phase 2: VS Code Extension Shell & Webview
* Modern TypeScript extension with Activity Bar view container and Webview chat provider.
* Strict Content Security Policy (CSP) with 128-bit cryptographic nonces per session.
* Interactive decision cards for Gate 0 (Scope Attestation) and Gate 1 (Test Case Review).
* Encrypted credential storage leveraging VS Code `SecretStorage`.

### Phase 3: Intake, SSRF Guardrails & Semantic ARIA Exploration
* Domain allowlist and DNS resolution firewall blocking loopback, RFC 1918, link-local, and cloud metadata (`169.254.169.254`).
* Action classification (`SAFE_READ`, `STATE_CHANGE`, `DESTRUCTIVE`).
* Compact ARIA accessibility snapshot engine with `#1`, `#2` reference indexing.
* `site-profile.json` generation and ambiguity/risk extraction.

### Phase 4: Test Case Design & Review Loop
* Standard Appendix A schema with Pydantic validation.
* Human-readable Markdown serialization and canonical SHA-256 hash calculation for Gate 1.
* Iterative comment review loop with semantic diffing between test-case versions.

### Phase 5: POM Script Generator, AST Validator & Execution Sandbox
* Playwright test suites utilizing Page Object Models mapped with `@pytest.mark.tc("TC-ID")`.
* Static AST security validator enforcing import allowlists and banning `eval`, `exec`, `subprocess`, `os`, `open`, and `time.sleep()`.
* Stripped-environment sandboxed runner with process timeouts and fresh browser context per test.
* Bounded dry-run locator stabilization logging to `repair-log.json`.

### Phase 6: Extended Coverage, RCA Investigation & Reporting
* WCAG 2.1 AA accessibility scans, console error tracking, network failure capture, performance metrics, and passive security header audits.
* Evidence Indexer (`evidence.py`) calculating SHA-256 hashes and assigning verified IDs (`[EV-001]`).
* Appendix B Root Cause Analysis (`classifier.py`) categorizing failures into 7 mutually exclusive classes and strictly verifying cited evidence IDs.
* Gate 2 human sign-off enforcement for confirmed `Product defect` classifications.
* Multi-format report builder: self-contained zero-JS HTML (Jinja2 autoescaped), Markdown, JSON, and JUnit XML.

### Phase 7: Pre-Release Security Checklist & Pilot Evaluation
* Prompt injection defense test suite.
* SSRF penetration test suite covering loopback, metadata, and protocol smuggling.
* AST evasion and obfuscated malicious code interception suite.
* Audit trail tamper-detection test suite.
* Simulated end-to-end pilot verifying Section 13 benchmarks:
  - 100% test-case traceability.
  - 100% verified evidence citations.
  - Zero open Critical/High security findings.

### Phase 8: Signed VSIX Packaging & Operational Runbooks
* Bundled and packaged `ai-qa-testing-harness-0.1.0.vsix`.
* Comprehensive user guide (`docs/user-guide.md`) and operational runbooks (`docs/runbooks.md`).

---

## 3. Verification & Test Metrics Summary

* **Unit & Integration Tests:** 115 passing tests (`115 passed in 5.49s`).
* **Code Quality & Linter:** Ruff check 100% clean (`All checks passed!`).
* **Security Scans:** Bandit AST security scan 100% clean (`0 High, 0 Medium, 0 Low issues`).
* **E2E Extension Integration:** TypeScript <-> Python JSON-RPC test (`100% passed`).

