// @ts-check
(function () {
  // @ts-ignore
  const vscode = acquireVsCodeApi();
  const $ = (id) => /** @type {any} */ (document.getElementById(id));

  const chatContainer = $("chatContainer");
  const stageBadge = $("stageBadge");
  const stageDesc = $("stageDesc");
  const txtPrompt = $("txtPrompt");

  let currentStreamBubble = null;
  let currentLogBlock = null;
  let state = { identity: null, ai: null, settings: null, providers: [], engineReady: true };

  function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Minimal safe formatting for engine messages: escape first, then **bold**.
  function formatText(text) {
    return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function scrollChat() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  function appendMessage(sender, text) {
    const bubble = document.createElement("div");
    bubble.className = `message-bubble ${sender}`;
    bubble.innerHTML = formatText(text);
    bubble.dataset.raw = text;
    chatContainer.appendChild(bubble);
    scrollChat();
    return bubble;
  }

  function post(command, payload) {
    vscode.postMessage({ command, ...(payload || {}) });
  }

  // ------------------------------------------------------------------ tabs

  function switchTab(tab) {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t.getAttribute("data-tab") === tab);
    });
    ["assistant", "suites", "ai"].forEach((name) => {
      $(`panel-${name}`).hidden = name !== tab;
    });
    if (tab === "suites") post("refreshSuites");
  }

  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchTab(t.getAttribute("data-tab")))
  );

  // ------------------------------------------------------------------ header state

  function renderState() {
    const ai = state.ai;
    const chipAi = $("chipAi");
    if (ai) {
      chipAi.textContent = ai.ready ? `AI: ${ai.providerLabel.split(" (")[0]}` : "AI: not connected";
      chipAi.className = `chip ${ai.ready ? "chip-ok" : "chip-warn"}`;
      chipAi.title = ai.detail;
    }
    const chipUser = $("chipUser");
    chipUser.textContent = state.identity ? `@${state.identity}` : "Sign in with GitHub";
    chipUser.title = state.identity
      ? "Approvals are recorded under this GitHub account. Click to switch account or sign out."
      : "Sign in so approvals are recorded under your GitHub account";
    $("acctState").textContent = state.identity ? `Signed in as @${state.identity}` : "Not signed in";
    $("acctState").className = `chip ${state.identity ? "chip-ok" : "chip-warn"}`;
    $("btnAcctSwitch").textContent = state.identity ? "Switch account" : "Sign in";
    $("btnAcctSignOut").hidden = !state.identity;
    $("engineBanner").hidden = state.engineReady;
    $("fAi").disabled = !(ai && ai.ready);
    $("fAi").checked = Boolean(ai && ai.ready);
    renderAiForm();
  }

  $("chipUser").addEventListener("click", () => post("signIn"));
  $("btnAcctSwitch").addEventListener("click", () => post("signIn"));
  $("btnAcctSignOut").addEventListener("click", () => post("signOut"));
  $("chipAi").addEventListener("click", () => switchTab("ai"));
  $("btnSetup").addEventListener("click", () => post("setupEngine"));

  // ------------------------------------------------------------------ AI provider form

  let aiFormProvider = null;

  function renderAiForm() {
    const s = state.settings;
    if (!s || !state.providers.length) return;
    const select = $("aiProvider");
    if (!select.options.length) {
      select.innerHTML = state.providers
        .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`)
        .join("");
    }
    if (aiFormProvider === null) {
      aiFormProvider = s.provider;
      select.value = s.provider;
      $("aiModel").value = s.model;
      $("aiBaseUrl").value = s.baseUrl;
      $("aiAzureVersion").value = s.azureApiVersion;
      $("aiInvestigationModel").value = s.investigationModel || "";
    }
    applyProviderLayout();
    renderCost();
    const ai = state.ai;
    if (ai) {
      const status = $("aiStatus");
      status.textContent = `${ai.ready ? "Connected" : "Not ready"}: ${ai.detail}`;
      status.className = `ai-status ${ai.ready ? "ok" : "warn"}`;
      $("aiKeyState").textContent = ai.hasKey ? "stored in OS keychain" : "not set";
    }
  }

  function applyProviderLayout() {
    const id = $("aiProvider").value;
    const info = state.providers.find((p) => p.id === id) || state.providers[0];
    $("aiHelp").textContent = info.keyHelp;
    $("aiKeyRow").hidden = !info.needsKey;
    $("aiBaseRow").hidden = !(info.needsBaseUrl || id === "openai" || id === "anthropic" || id === "gemini");
    $("aiBaseUrl").placeholder = info.defaultBaseUrl || "https://...";
    $("aiAzureRow").hidden = id !== "azure-openai";
    const modelDisabled = id === "none";
    $("aiModel").disabled = modelDisabled;
    $("aiInvestigationModelRow").hidden = modelDisabled;
    $("aiInvestigationModel").placeholder =
      id === "azure-openai"
        ? "Empty = same deployment. A cheaper deployment saves quota."
        : "Empty = same model. Pick a cheaper one to save quota.";
    $("btnLoadModels").disabled = modelDisabled || id === "azure-openai";
    $("aiModel").placeholder =
      id === "copilot"
        ? "Leave empty to use the first available Copilot model"
        : id === "azure-openai"
          ? "Deployment name"
          : "Load models or type a model ID";
  }

  function saveAi() {
    aiFormProvider = $("aiProvider").value;
    post("ai.save", {
      provider: aiFormProvider,
      model: $("aiModel").value.trim(),
      baseUrl: $("aiBaseUrl").value.trim(),
      azureApiVersion: $("aiAzureVersion").value.trim(),
      investigationModel: $("aiInvestigationModel").value.trim(),
    });
  }

  let costFormLoaded = false;
  function renderCost() {
    const c = state.cost;
    if (!c) return;
    if (!costFormLoaded) {
      costFormLoaded = true;
      $("costInvestigate").checked = c.investigate;
      $("costReuse").checked = c.reuse;
      $("costPerRun").value = c.perRun;
      $("costDaily").value = c.daily;
    }
    const used = c.today.investigation;
    const atLimit = c.investigate && used >= c.daily;
    $("costUsage").textContent =
      `Today: ${c.today.design} design call(s), ${used} of ${c.daily} failure analyses` +
      (atLimit ? " - daily limit reached, failures are classified by rules." : ".");
    $("costUsage").className = `ai-status ${atLimit ? "warn" : "ok"}`;
  }

  $("btnSaveCost").addEventListener("click", () => {
    costFormLoaded = false;
    post("ai.costSave", {
      investigate: $("costInvestigate").checked,
      reuse: $("costReuse").checked,
      perRun: Number($("costPerRun").value),
      daily: Number($("costDaily").value),
    });
  });

  $("aiProvider").addEventListener("change", () => {
    $("aiModel").value = "";
    $("aiInvestigationModel").value = "";
    $("aiModelList").innerHTML = "";
    applyProviderLayout();
    saveAi();
  });
  $("btnSaveAi").addEventListener("click", saveAi);
  $("btnSetKey").addEventListener("click", () => {
    saveAi();
    post("ai.setKey");
  });
  $("btnClearKey").addEventListener("click", () => post("ai.clearKey"));
  $("btnLoadModels").addEventListener("click", () => {
    saveAi();
    $("aiStatus").textContent = "Loading models ...";
    post("ai.models");
  });
  $("btnTestAi").addEventListener("click", () => {
    saveAi();
    $("aiStatus").textContent = "Testing connection ...";
    $("aiStatus").className = "ai-status";
    post("ai.test");
  });

  // ------------------------------------------------------------------ suites tab

  const suiteForm = $("suiteForm");

  function openSuiteForm(prefill) {
    const p = prefill || {};
    $("formTitle").textContent = prefill ? `Update suite: ${p.module}` : "New test suite";
    $("btnSubmitSuite").textContent = prefill ? "Update & Re-design" : "Create & Design";
    $("fModule").value = p.module || "";
    $("fModule").readOnly = Boolean(prefill);
    $("fUrl").value = p.start_url || "";
    $("fDomains").value = (p.extra_domains || []).join(", ");
    $("fEnv").value = p.environment || "test";
    $("fReq").value = p.requirement_text || "";
    $("fAc").value = p.acceptance_criteria || "";
    $("fDryRun").checked = true;
    $("formNote").hidden = !prefill;
    $("formError").hidden = true;
    suiteForm.hidden = false;
    (prefill ? $("fReq") : $("fModule")).focus();
  }

  $("btnNewSuite").addEventListener("click", () => openSuiteForm(null));
  $("btnCancelForm").addEventListener("click", () => (suiteForm.hidden = true));
  $("btnRefresh").addEventListener("click", () => post("refreshSuites"));
  $("btnRegression").addEventListener("click", () => post("regression", { tag: $("regTag").value }));

  suiteForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const error = $("formError");
    const module = $("fModule").value.trim();
    const url = $("fUrl").value.trim();
    if (!module || !/^https?:\/\//i.test(url)) {
      error.textContent = "Enter a module name and an http(s) start URL.";
      error.hidden = false;
      return;
    }
    const useAi = $("fAi").checked;
    if (useAi && !$("fAc").value.trim() && !$("fReq").value.trim()) {
      error.textContent = "Enter the requirement and/or acceptance criteria for AI design.";
      error.hidden = false;
      return;
    }
    const environment = $("fEnv").value.trim();
    if (!/^[A-Za-z0-9_.-]{1,32}$/.test(environment)) {
      error.textContent = "Environment: 1-32 letters, digits, '.', '_' or '-'.";
      error.hidden = false;
      return;
    }
    error.hidden = true;
    post("newSuite", {
      module,
      url,
      domains: $("fDomains").value,
      environment,
      requirement: $("fReq").value,
      criteria: $("fAc").value,
      useAi,
      dryRun: $("fDryRun").checked,
    });
    suiteForm.hidden = true;
  });

  function statusBadge(run) {
    if (!run) return `<span class="pill">never run</span>`;
    const cls = run.failed || run.blocked ? "pill-fail" : "pill-pass";
    return `<span class="pill ${cls}">${escapeHtml(run.passed)}/${escapeHtml(run.total)} passed</span>`;
  }

  function renderSuites(suites, engineReady) {
    const list = $("suiteList");
    if (!engineReady) {
      list.innerHTML = `<p class="muted">Set up the engine to manage suites.</p>`;
      return;
    }
    if (!suites.length) {
      list.innerHTML = `<p class="muted">No suites yet. Click <strong>+ New Suite</strong> to create one from a requirement and acceptance criteria.</p>`;
      return;
    }
    list.innerHTML = suites
      .map((s) => {
        const run = s.last_run;
        const when = run ? new Date(run.started_at).toLocaleString() : "";
        const types = (s.test_types || []).map((t) => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("");
        const envs = [`${s.environment} (default)`, ...Object.keys(s.environments || {})];
        const lastEnv = run && run.environment ? ` on ${escapeHtml(run.environment)}` : "";
        return `
        <div class="suite-card" data-slug="${escapeHtml(s.slug)}">
          <div class="suite-head">
            <strong>${escapeHtml(s.module)}</strong>
            ${statusBadge(run)}
          </div>
          <div class="muted small">${escapeHtml(s.start_url)} &middot; v${escapeHtml(s.current_version)} &middot; ${escapeHtml(s.total_cases)} case(s)</div>
          <div class="muted small">Environments: ${escapeHtml(envs.join(", "))}</div>
          ${run ? `<div class="muted small">Last ${escapeHtml(run.run_type)}${lastEnv} ${escapeHtml(when)} by ${escapeHtml(run.triggered_by)}</div>` : ""}
          <div class="small">${types}</div>
          <div class="action-buttons">
            <button class="btn-primary" data-act="retest">Retest all</button>
            <button class="btn-secondary" data-act="retestFailed" ${s.failed_count ? "" : "disabled"}>Retest failed (${escapeHtml(s.failed_count)})</button>
            <button class="btn-secondary" data-act="cases">Cases</button>
            ${run && run.report_html ? `<button class="btn-secondary" data-act="report">Report</button>` : ""}
            <button class="btn-secondary" data-act="secrets">Secrets${(s.required_secrets || []).length ? ` (${s.required_secrets.length})` : ""}</button>
            <button class="btn-secondary" data-act="update">Update</button>
            <button class="btn-secondary btn-danger" data-act="delete">Delete</button>
          </div>
        </div>`;
      })
      .join("");

    list.querySelectorAll(".suite-card").forEach((card) => {
      const slug = card.getAttribute("data-slug");
      const suite = suites.find((s) => s.slug === slug);
      card.querySelectorAll("button[data-act]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const act = btn.getAttribute("data-act");
          if (act === "retest") post("retest", { slug, failed_only: false });
          if (act === "retestFailed") post("retest", { slug, failed_only: true });
          if (act === "cases") post("openFile", { path: suite.testcases_md });
          if (act === "report") post("openReport", { path: suite.last_run.report_html });
          if (act === "secrets") post("manageSecrets", { slug });
          if (act === "update") post("updateSuite", { slug });
          if (act === "delete") post("deleteSuite", { slug });
        });
      });
    });
  }

  // ------------------------------------------------------------------ cards

  function renderCard(cardType, data) {
    const card = document.createElement("div");
    card.className = "decision-card";
    const renderers = {
      scope_card: renderScopeCard,
      clarification_card: renderClarificationCard,
      review_card: renderReviewCard,
      dry_run_card: renderDryRunCard,
      report_card: renderReportCard,
      regression_card: renderRegressionCard,
    };
    const render = renderers[cardType];
    if (!render) return;
    render(card, data || {});
    chatContainer.appendChild(card);
    scrollChat();
  }

  function renderScopeCard(card, data) {
    const domains = (data.allowed_domains || []).join(", ");
    const env = data.environment || "";
    card.innerHTML = `
      <h3>Scope &amp; Authorization (Gate 0)</h3>
      <div class="card-field"><span class="card-label">Suite</span>
        <div class="card-value">${escapeHtml(data.module)} ${data.updates_existing_suite ? '<span class="pill">new version of existing suite</span>' : ""}</div></div>
      <div class="card-field"><span class="card-label">Design</span>
        <div class="card-value">${data.design_mode === "ai" ? `AI from requirement (${escapeHtml(data.criteria_count)} acceptance criteria)` : "Smoke design from page structure"}</div></div>
      <div class="card-field"><span class="card-label">Target URL</span>
        <div class="card-value">${escapeHtml(data.start_url)}</div></div>
      <label class="card-label" for="scopeDomains">Allowed domains (comma separated)</label>
      <input id="scopeDomains" value="${escapeHtml(domains)}" />
      <label class="card-label" for="scopeEnv">Environment</label>
      <input id="scopeEnv" list="envSuggestions" value="${escapeHtml(env)}" placeholder="e.g. test, staging, uat" />
      <div class="attestation-box">
        <input type="checkbox" id="chkAttest" />
        <label for="chkAttest"><strong>Authorization:</strong> I confirm that I am authorized to test this target, and all browsing stays within the domains above.</label>
      </div>
      <div class="card-error" id="scopeError" hidden></div>
      <div class="action-buttons"><button class="btn-primary" id="btnConfirmScope">Confirm Scope (Gate 0)</button></div>`;

    card.querySelector("#btnConfirmScope").addEventListener("click", () => {
      const err = card.querySelector("#scopeError");
      const environment = card.querySelector("#scopeEnv").value.trim();
      const allowed = card.querySelector("#scopeDomains").value.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);
      const problem = !card.querySelector("#chkAttest").checked
        ? "Check the authorization attestation first."
        : !/^[A-Za-z0-9_.-]{1,32}$/.test(environment)
          ? "Enter the target environment (letters, digits, '.', '_' or '-')."
          : !allowed.length
            ? "At least one allowed domain is required."
            : "";
      if (problem) {
        err.textContent = problem;
        err.hidden = false;
        return;
      }
      err.hidden = true;
      post("confirmScope", {
        scope: { start_url: data.start_url, allowed_domains: allowed, environment, authorized_attestation: true },
      });
      card.querySelector("#btnConfirmScope").setAttribute("disabled", "true");
    });
  }

  function renderClarificationCard(card, data) {
    const questions = data.questions || [];
    const fields = questions
      .map((q, i) => {
        const options = (q.options || [])
          .map((o) => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`)
          .join("");
        const input = options
          ? `<select data-qid="${escapeHtml(q.question_id)}"><option value="">Choose ...</option>${options}</select>`
          : `<textarea rows="2" data-qid="${escapeHtml(q.question_id)}"></textarea>`;
        return `<div class="card-field">
          <span class="card-label">${escapeHtml(q.question_id || `Q-${i + 1}`)}</span>
          <div>${escapeHtml(q.question_text)}</div>
          ${q.context ? `<div class="muted small">${escapeHtml(q.context)}</div>` : ""}
          ${input}</div>`;
      })
      .join("");
    card.innerHTML = `
      <h3>Clarifications needed</h3>
      <p class="muted">${escapeHtml(data.summary)}</p>
      ${fields}
      <div class="action-buttons"><button class="btn-primary" id="btnAnswer">Submit answers</button></div>`;
    card.querySelector("#btnAnswer").addEventListener("click", () => {
      const answers = {};
      card.querySelectorAll("[data-qid]").forEach((el) => {
        answers[el.getAttribute("data-qid")] = el.value;
      });
      post("answerClarifications", { answers });
      card.querySelector("#btnAnswer").setAttribute("disabled", "true");
    });
  }

  function renderReviewCard(card, data) {
    const cases = data.testcases || [];
    const rows = cases
      .map(
        (tc) => `
        <details class="tc-item">
          <summary><strong>${escapeHtml(tc.tc_id)}</strong> ${escapeHtml(tc.title)}
            <span class="pill">${escapeHtml(tc.priority)}</span>${tc.ac_ref ? `<span class="pill">${escapeHtml(tc.ac_ref)}</span>` : ""}
            ${(tc.test_types || []).map((t) => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("")}</summary>
          <ol>${(tc.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>
          <div class="small"><strong>Expected:</strong> ${escapeHtml(tc.expected_result)}</div>
          <div class="small muted"><strong>Automation:</strong> ${(tc.actions || []).map(escapeHtml).join(" &rarr; ")}</div>
        </details>`
      )
      .join("");
    const coverage = (data.coverage || [])
      .map((c) => `<li class="${c.has_gaps ? "result-fail" : ""}">${escapeHtml(c.requirement_id)}: ${escapeHtml(c.requirement_text)} &rarr; ${escapeHtml((c.covered_test_case_ids || []).join(", ") || "NOT COVERED")}</li>`)
      .join("");
    const secrets = (data.required_secrets || []).map((s) => `<span class="domain-tag">${escapeHtml(s)}</span>`).join("");
    const unverified = (data.unverified_locators || []).map((u) => `<li>${escapeHtml(u)}</li>`).join("");

    card.innerHTML = `
      <h3>Test Case Review (Gate 1) &middot; ${escapeHtml(data.module)} v${escapeHtml(data.version)}</h3>
      ${data.diff_summary ? `<p class="pill">${escapeHtml(data.diff_summary)}</p>` : ""}
      <p class="muted small">Approving binds exactly these cases to SHA-256 <code>${escapeHtml(String(data.sha256_hash).slice(0, 16))}...</code>, then generates and runs the scripts.</p>
      ${rows}
      ${coverage ? `<div class="card-field"><span class="card-label">Acceptance criteria coverage (${escapeHtml(data.coverage_percentage)}%)</span><ul class="small">${coverage}</ul></div>` : ""}
      ${secrets ? `<div class="card-field"><span class="card-label">Secrets needed at run time</span>${secrets}<div class="muted small">You will be asked for each value once; it is kept in the OS keychain.</div></div>` : ""}
      ${unverified ? `<details class="small"><summary>Locators not seen during exploration (${(data.unverified_locators || []).length})</summary><ul>${unverified}</ul></details>` : ""}
      ${data.can_revise ? `<label class="card-label" for="reviewComments">Request changes</label><textarea id="reviewComments" rows="2" placeholder="e.g. add a negative case for an empty password; drop TC-...-003"></textarea>` : ""}
      <div class="action-buttons">
        <button class="btn-primary" id="btnApproveCases">Approve &amp; Run (Gate 1)</button>
        ${data.can_revise ? `<button class="btn-secondary" id="btnRevise">Request changes</button>` : ""}
        <button class="btn-secondary" id="btnOpenCases">Open as Markdown</button>
      </div>`;

    const disableAll = () => card.querySelectorAll("button").forEach((b) => b.setAttribute("disabled", "true"));
    card.querySelector("#btnApproveCases").addEventListener("click", () => {
      post("approveTestcases", { version: data.version, sha256_hash: data.sha256_hash });
      disableAll();
    });
    card.querySelector("#btnOpenCases").addEventListener("click", () => post("openFile", { path: data.testcases_md }));
    const revise = card.querySelector("#btnRevise");
    if (revise) {
      revise.addEventListener("click", () => {
        const comments = card.querySelector("#reviewComments").value.trim();
        if (!comments) return;
        post("reviseTestcases", { comments });
        disableAll();
      });
    }
  }

  function renderDryRunCard(card, data) {
    const issues = data.issues || [];
    const cases = data.cases || [];
    const ok = cases.filter((c) => c.status === "ok").length;
    const blocked = cases.filter((c) => c.status === "blocked").length;
    const rows = issues
      .map(
        (i) => `<li><strong>${escapeHtml(i.tc_id)}</strong> step ${escapeHtml(i.step)} (${escapeHtml(i.action)}):
          ${escapeHtml(i.detail)}<div class="muted small">${escapeHtml(i.page_url)}</div>
          ${i.screenshot ? `<button class="btn-secondary small" data-shot="${escapeHtml(i.screenshot)}">Screenshot</button>` : ""}</li>`
      )
      .join("");
    card.innerHTML = `
      <h3>&#9888;&#65039; Dry run found ${escapeHtml(issues.length)} problem(s) &middot; ${escapeHtml(data.module)}</h3>
      <p class="muted small">${escapeHtml(ok)} case(s) executable${blocked ? `, ${escapeHtml(blocked)} blocked by missing secrets` : ""}. Assertions were not evaluated; these steps could not be performed on the live page.</p>
      <ul class="small">${rows}</ul>
      <div class="action-buttons">
        ${data.can_fix ? `<button class="btn-primary" data-decision="fix">Fix with AI (re-approve)</button>` : ""}
        <button class="btn-secondary" data-decision="run">Run anyway</button>
        <button class="btn-secondary" data-decision="cancel">Cancel</button>
      </div>`;
    card.querySelectorAll("button[data-shot]").forEach((b) =>
      b.addEventListener("click", () => post("openReport", { path: b.getAttribute("data-shot") }))
    );
    card.querySelectorAll("button[data-decision]").forEach((b) =>
      b.addEventListener("click", () => {
        post("dryRunDecide", { decision: b.getAttribute("data-decision") });
        card.querySelectorAll("button[data-decision]").forEach((x) => x.setAttribute("disabled", "true"));
      })
    );
  }

  function renderReportCard(card, data) {
    const failed = Number(data.failed || 0) + Number(data.blocked || 0);
    const label =
      { initial: "Run", update: "Updated suite run", retest: "Retest", "retest-failed": "Retest (failed only)" }[data.run_type] ||
      "Run";
    const inv = (data.ai_usage && data.ai_usage.investigations) || {};
    const analysed = ["ai", "reused", "cached", "rules", "limited"].reduce((n, k) => n + Number(inv[k] || 0), 0);
    const analysis = analysed
      ? [
          inv.ai ? `${inv.ai} by AI` : "",
          inv.reused ? `${inv.reused} reused (same error)` : "",
          inv.cached ? `${inv.cached} reused from earlier runs` : "",
          inv.rules ? `${inv.rules} by rules` : "",
          inv.limited ? `${inv.limited} by rules (AI limit reached)` : "",
        ]
          .filter(Boolean)
          .join(", ")
      : "";
    card.innerHTML = `
      <h3>${failed > 0 ? "&#10060;" : "&#9989;"} ${escapeHtml(label)} complete &middot; ${escapeHtml(data.module)}</h3>
      <div class="result-grid">
        <div><span class="card-label">Total</span><div class="card-value">${escapeHtml(data.total)}</div></div>
        <div><span class="card-label">Passed</span><div class="card-value result-pass">${escapeHtml(data.passed)}</div></div>
        <div><span class="card-label">Failed</span><div class="card-value result-fail">${escapeHtml(data.failed)}</div></div>
        <div><span class="card-label">Flaky</span><div class="card-value">${escapeHtml(data.flaky)}</div></div>
        <div><span class="card-label">Blocked</span><div class="card-value">${escapeHtml(data.blocked)}</div></div>
      </div>
      ${(data.failed_tc_ids || []).length ? `<div class="card-field"><span class="card-label">Not passing</span><div class="card-value">${escapeHtml(data.failed_tc_ids.join(", "))}</div></div>` : ""}
      ${data.environment ? `<div class="card-field"><span class="card-label">Environment</span><div class="card-value">${escapeHtml(data.environment)} &middot; ${escapeHtml(data.target_url)}</div></div>` : ""}
      ${analysis ? `<div class="card-field"><span class="card-label">Failure analysis</span><div class="card-value">${escapeHtml(analysis)}</div></div>` : ""}
      <div class="card-field"><span class="card-label">Duration</span><div class="card-value">${escapeHtml(data.duration_seconds)} s &middot; by ${escapeHtml(data.triggered_by)}</div></div>
      <div class="action-buttons">
        <button class="btn-primary" id="btnOpenReport">Open HTML Report</button>
        ${(data.failed_tc_ids || []).length ? `<button class="btn-secondary" id="btnRetestFailed">Retest failed</button>` : ""}
      </div>`;
    card.querySelector("#btnOpenReport").addEventListener("click", () => post("openReport", { path: data.report_html }));
    const retest = card.querySelector("#btnRetestFailed");
    if (retest) retest.addEventListener("click", () => post("retest", { slug: data.slug, failed_only: true }));
  }

  function renderRegressionCard(card, data) {
    const t = data.totals || {};
    const rows = (data.suites || [])
      .map(
        (s) => `<tr>
          <td>${escapeHtml(s.module)}</td>
          <td><span class="pill ${s.status === "passed" ? "pill-pass" : "pill-fail"}">${escapeHtml(s.status)}</span></td>
          <td>${s.status === "error" ? escapeHtml(s.error || "not run") : `${escapeHtml(s.passed)}/${escapeHtml(s.total)}`}</td>
          <td>${escapeHtml((s.newly_failing || []).join(", ") || "-")}</td></tr>`
      )
      .join("");
    const errors = (data.suites || []).some((s) => s.status === "error");
    const filters = [data.tag, data.environment].filter(Boolean).map(escapeHtml).join(", ");
    card.innerHTML = `
      <h3>${t.failed || errors ? "&#10060;" : "&#9989;"} Regression complete${filters ? ` (${filters})` : ""}</h3>
      <div class="result-grid">
        <div><span class="card-label">Tests</span><div class="card-value">${escapeHtml(t.total)}</div></div>
        <div><span class="card-label">Passed</span><div class="card-value result-pass">${escapeHtml(t.passed)}</div></div>
        <div><span class="card-label">Failed</span><div class="card-value result-fail">${escapeHtml(t.failed)}</div></div>
        <div><span class="card-label">Flaky</span><div class="card-value">${escapeHtml(t.flaky)}</div></div>
        <div><span class="card-label">Blocked</span><div class="card-value">${escapeHtml(t.blocked)}</div></div>
      </div>
      <table class="tc-table"><thead><tr><th>Suite</th><th>Status</th><th>Passed</th><th>Newly failing</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="muted small">AI calls for failure analysis: ${escapeHtml(data.ai_calls || 0)}</p>
      <div class="action-buttons"><button class="btn-primary" id="btnOpenReg">Open Regression Report</button></div>`;
    card.querySelector("#btnOpenReg").addEventListener("click", () => post("openReport", { path: data.report_html }));
  }

  // ------------------------------------------------------------------ extension -> webview

  window.addEventListener("message", (event) => {
    const msg = event.data;
    switch (msg.type) {
      case "state":
        state = msg;
        renderState();
        break;
      case "suites":
        renderSuites(msg.suites || [], msg.engineReady !== false);
        break;
      case "switchTab":
        switchTab(msg.tab);
        if (msg.openForm) openSuiteForm(null);
        break;
      case "suiteForm":
        switchTab("suites");
        openSuiteForm(msg.suite);
        break;
      case "notice":
        appendMessage("assistant error", msg.text);
        if (msg.level === "error") switchTab("assistant");
        break;
      case "ai.models": {
        const models = msg.models || [];
        $("aiModelList").innerHTML = models
          .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name)}</option>`)
          .join("");
        $("aiStatus").textContent = models.length
          ? `${models.length} model(s) available. Pick one in the Model field, then Save.`
          : "No models returned; type the model name.";
        break;
      }
      case "ai.testResult":
        $("aiStatus").textContent = msg.ok ? `Connection OK. ${msg.text}` : `Connection failed: ${msg.text}`;
        $("aiStatus").className = `ai-status ${msg.ok ? "ok" : "warn"}`;
        break;
      case "stage.update": {
        stageBadge.textContent = String(msg.stage).replace("STAGE_", "").replace(/_/g, " ");
        const s = msg.stage === "ERROR" ? "error" : msg.stage === "COMPLETED" ? "done" : "active";
        stageBadge.className = `stage-badge ${s}`;
        stageDesc.textContent = msg.description || "";
        break;
      }
      case "message.stream": {
        if (msg.style === "log") {
          if (!currentLogBlock && msg.chunk) {
            currentLogBlock = document.createElement("pre");
            currentLogBlock.className = "log-block";
            chatContainer.appendChild(currentLogBlock);
          }
          if (currentLogBlock) {
            currentLogBlock.textContent += msg.chunk;
            currentLogBlock.scrollTop = currentLogBlock.scrollHeight;
          }
          if (msg.complete) currentLogBlock = null;
        } else {
          if (!currentStreamBubble) currentStreamBubble = appendMessage("assistant", "");
          currentStreamBubble.dataset.raw = (currentStreamBubble.dataset.raw || "") + msg.chunk;
          currentStreamBubble.innerHTML = formatText(currentStreamBubble.dataset.raw);
          if (msg.complete) currentStreamBubble = null;
        }
        scrollChat();
        break;
      }
      case "card.show":
        renderCard(msg.card_type, msg.data);
        break;
    }
  });

  // ------------------------------------------------------------------ chat input

  $("btnCancel").addEventListener("click", () => post("cancelRun"));

  function handleSend() {
    const text = txtPrompt.value.trim();
    if (!text) return;
    appendMessage("user", text);
    txtPrompt.value = "";
    post("userPrompt", { text });
  }

  $("btnSend").addEventListener("click", handleSend);
  txtPrompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  post("ready");
})();
