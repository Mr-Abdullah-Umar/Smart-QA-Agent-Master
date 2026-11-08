# AI QA Testing Harness - Operations & Troubleshooting Runbook

This runbook provides engineering and QA teams with operational procedures, failure triage steps, and diagnostic runbooks for the AI QA Testing Harness.

---

## Runbook 1: Python Engine Process Startup & Stdio Triage

### Symptoms
* VS Code extension status bar shows "QA Engine: Disconnected".
* JSON-RPC request timeout (e.g. `RPC request 'run.start' timed out after 30000ms`).
* Child process exits immediately upon launch.

### Root Causes & Diagnostic Steps
1. **Virtual Environment Not Found:**
   - Verify `engine/.venv` exists.
   - Run `engine/.venv/Scripts/python.exe -V` (Windows) or `engine/.venv/bin/python --version` (Linux/macOS).
   - If missing, re-create the virtual environment:
     ```bash
     cd engine && python -m venv .venv && pip install -r requirements.txt
     ```
2. **Missing Dependencies:**
   - Execute package check in virtual environment:
     ```bash
     python -c "import pydantic, playwright, pytest, jinja2, defusedxml; print('OK')"
     ```
3. **Stdio Buffering on Windows:**
   - Python stdout buffering can delay line delivery. Ensure the child process is launched with the `-u` flag (`python -u -m qa_engine.main`) or environment variable `PYTHONUNBUFFERED=1`.

---

## Runbook 2: SSRF Route Interception & Destination Blocks

### Symptoms
* Browser exploration halts or fails to load styles, assets, or redirects.
* Log entry: `Blocked by client: Domain 'cdn.auth0.com' is not in the approved allowed_domains list.`

### Resolution
1. The harness strictly enforces T5 SSRF guardrails. By default, only domains listed during Gate 0 Scope Confirmation are allowed.
2. If the application redirects to an authentication provider (e.g., Auth0, Okta, Google Identity) or loads essential CDNs:
   - Abort current run.
   - Start new run and add the auth domain to the **Allowed Domains** field (e.g. `myapp.com, cdn.myapp.com, dev-1234.auth0.com`).
3. Under no circumstances should internal ranges (`127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`) be whitelisted. The engine will refuse to route traffic to them regardless of allowlist contents.

---

## Runbook 3: Playwright Browser Launch in CI/Headless Environments

### Symptoms
* `browserType.launch: Host system is missing dependencies for Chromium.`
* Browser process terminates with SIGTRAP or crash.

### Resolution
1. On fresh Linux/Docker containers, install required system libraries:
   ```bash
   npx playwright install-deps chromium
   ```
2. Ensure launch flags include `--disable-dev-shm-usage` and `--no-sandbox` (configured automatically by `GuardedBrowserSession`).
3. For debugging visual regressions, you can toggle headless mode in `qa_engine/browser/tools.py` (`headless=False`).

---

## Runbook 4: AST Security Validator Rejections

### Symptoms
* Stage 6 fails with `ScriptValidationError: Prohibited import '...'` or `'time.sleep()' is banned`.

### Resolution
1. **Banned Functions:**
   - `eval()`, `exec()`, `open()`, `input()`, `compile()`, and `getattr()` are strictly banned to prevent arbitrary remote code execution (T3).
   - `time.sleep()` is prohibited to eliminate test flakiness (T8).
2. **Proper Pattern:**
   - Replace manual sleeps with Playwright web-first assertions:
     ```python
     # DO NOT USE:
     # import time; time.sleep(5)
     
     # USE INSTEAD:
     from playwright.sync_api import expect
     expect(page.locator("button#submit")).to_be_visible()
     ```
3. **Traceability Marker:**
   - Every test function must be decorated with its approved test case ID:
     ```python
     @pytest.mark.tc("TC-LOGIN-001")
     def test_login_flow(page: Page): ...
     ```

---

## Runbook 5: Tamper-Evident Audit Trail Verification & Incident Triage

### Symptoms
* Run resumption fails with: `ValueError: Audit log verification failed: Hash mismatch at sequence...`

### Severity: HIGH (Potential unauthorized tampering or disk corruption)

### Diagnostic Steps
1. The engine seals every state change, human gate approval, and tool execution in `audit.jsonl` using a continuous SHA-256 hash-chain:
   $$H_n = \text{SHA-256}(\text{canonical\_json}(\text{record}_n) \parallel H_{n-1})$$
2. Execute programmatic verification on the run's audit trail:
   ```bash
   python -c "from qa_engine.orchestrator.audit import AuditLogger; from pathlib import Path; print(AuditLogger.verify_log_file(Path('.qa-harness/runs/<run-id>/audit.jsonl')))"
   ```
3. If `verify_log_file` reports `Non-sequential entry_id` or `Tampered content`:
   - Inspect Git or workstation file history to identify who modified `audit.jsonl` or `approvals.json`.
   - Never proceed with execution from a corrupted audit state. Discard the run and start a clean run.

---

## Runbook 6: Inspecting Playwright Execution Traces

### Procedure
When a test fails during execution or dry run:
1. Locate the trace zip file in `.qa-harness/runs/<run-id>/evidence/traces/<test_id>.zip`.
2. Inspect the interactive DOM timeline, console messages, and network waterfall:
   ```bash
   playwright show-trace .qa-harness/runs/<run-id>/evidence/traces/<test_id>.zip
   ```
3. Correlate with the verified Evidence ID `[EV-xxx]` cited in the HTML report.

