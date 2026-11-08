# AI QA Testing Harness for Visual Studio Code

An enterprise-grade, deterministic AI QA Testing Harness implemented in Visual Studio Code and Python.

## Key Features
- **11-Stage Deterministic Workflow**: From scope confirmation and requirement analysis to automated POM test generation, sandboxed execution, and multi-format reporting.
- **Three Human Approval Gates**:
  - **Gate 0 (Scope Attestation)**: Enforces domain allowlists, environment checks, and explicit engineer authorization.
  - **Gate 1 (Test Design Sign-off)**: Cryptographically binds approved test cases to a SHA-256 hash before test scripts can be generated.
  - **Gate 2 (Defect Sign-off)**: Mandates human engineer review and sign-off before any failed test is logged as a product defect.
- **Strict Zero-Trust Security**:
  - SSRF route interception and DNS rebinding protections.
  - AST security validation banning `eval`, `exec`, `subprocess`, `os`, and unwhitelisted libraries.
  - CSP 128-bit cryptographic nonces in Webview.
  - PII and high-entropy secret redaction before any LLM submission.
  - Tamper-evident SHA-256 hash-chained audit logging (`audit.jsonl`).
- **Multi-Format Reports**: Self-contained zero-JS HTML reports, Markdown summaries, JUnit XML, and canonical JSON.

