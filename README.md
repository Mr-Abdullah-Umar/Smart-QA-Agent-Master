# Smart QA Agent - AI QA Testing Harness

A VS Code extension and Python engine that turn a requirement and its acceptance criteria into an
approved, reusable Playwright test suite, then support retesting a module and regression across all suites.

* **Suite library:** create, update (the AI revises the approved suite and keeps case IDs), and delete
  (archived) suites; retest or run regression on any named environment (dev, staging, uat, ...).
* **Dry run:** every approved step is tried once on the live page before execution; broken steps can be
  repaired by the AI and re-approved.
* **AI providers:** GitHub Copilot through VS Code (default) or an API key for OpenAI, Azure OpenAI,
  Anthropic, Gemini, GitHub Models, or any OpenAI-compatible HTTPS endpoint. The CLI uses the same
  API-key providers through `QA_AI_*` environment variables, so suites can be designed in CI.
* **Human gates:** scope attestation, test case approval bound to a SHA-256 hash, and defect sign-off,
  all recorded under your GitHub account name.
* **Safety:** domain allowlist with SSRF and private-network blocking, AST validation of generated code,
  secrets kept in VS Code SecretStorage and masked in all artifacts, hash-chained audit log.

## Layout

| Folder | Contents |
| :--- | :--- |
| `extension/` | VS Code extension (TypeScript, webview UI) |
| `engine/` | Python engine `qa_engine` (workflow, AI test design, Playwright execution, reports, CLI) |
| `docs/` | [User guide](docs/user-guide.md), [plan](docs/plan-test-suites-and-llm-providers.md), threat model, runbooks |

## Develop

```bash
cd engine
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/pip
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m pytest -q

cd ../extension
npm install
npm test                                            # compile + extension unit tests
node test-integration.js https://your-app.example   # end-to-end check with a scripted AI
npm run package                                     # builds the .vsix with the engine bundled
```

See the [user guide](docs/user-guide.md) for setup and usage.
