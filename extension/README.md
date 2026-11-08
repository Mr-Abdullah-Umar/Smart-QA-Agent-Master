# AI QA Testing Harness for Visual Studio Code

Turn a requirement and its acceptance criteria into an approved Playwright test suite, run it in a real
browser, and keep it for retesting and regression.

## Features

- **Test suites per module**: the AI analyzes the requirement, asks clarifying questions, explores the
  target pages, and drafts test cases mapped to each acceptance criterion with an automation plan.
- **Review and approve (Gate 1)**: request revisions or approve. The approval is bound to a SHA-256 hash and
  your GitHub account name.
- **Dry run**: before execution every step is tried once on the live page. Steps that cannot be performed
  are listed with screenshots; let the AI repair them (and re-approve), run anyway, or cancel.
- **Update and delete suites**: edit the requirement or criteria and the AI revises the approved suite,
  keeping the IDs of unchanged cases; deleted suites are archived, not erased.
- **Retesting**: re-run all cases of a module or only the failed ones, on its default environment or any other
  (e.g. staging, uat), with integrity checks on the stored suite.
- **Regression**: run every suite, optionally filtered by test type (smoke, sanity, regression, functional,
  negative, boundary, ui, accessibility) and environment, with a combined report of newly failing and fixed cases.
- **AI providers**: GitHub Copilot through VS Code with no key, or OpenAI, Azure OpenAI, Anthropic, Gemini,
  GitHub Models, or any OpenAI-compatible HTTPS endpoint with an API key, all from the **AI Provider** tab.
- **AI cost controls**: suite design is never limited; failure analysis uses rules first, shares one
  analysis across identical errors, reuses earlier analyses of the same failure, and stays within per-run
  and daily limits (optionally on a cheaper model). Limits never change test results.
- **Security**: domain allowlist, localhost and private networks blocked, AST validation of generated code,
  secrets in SecretStorage and masked in reports, tamper-evident audit log.

## Getting started

1. Open a trusted folder and click the **QA Harness** beaker in the Activity Bar.
2. Click **Set Up Engine** once (requires Python 3.10+ on the PATH).
3. Check the **AI Provider** tab (Copilot is the default) and sign in with GitHub.
4. In the **Suites** tab, click **New Suite** and enter the module, start URL, requirement, and acceptance criteria.

Full documentation: `docs/user-guide.md` in the project repository.
