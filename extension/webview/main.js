// @ts-check
(function () {
  // @ts-ignore
  const vscode = acquireVsCodeApi();
  const $ = (id) => /** @type {any} */ (document.getElementById(id));

  const chatContainer = $("chatContainer");
  const replayContainer = $("replayContainer");
  const txtPrompt = $("txtPrompt");
  const app = $("app");

  let state = { identity: null, ai: null, settings: null, providers: [], engineReady: true, cost: null };

  // ------------------------------------------------------------------ helpers

  function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Minimal safe formatting for engine messages: escape first, then **bold** and `code`.
  function formatText(text) {
    return escapeHtml(text)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function post(command, payload) {
    vscode.postMessage({ command, ...(payload || {}) });
  }

  function formatDuration(ms) {
    const n = Number(ms) || 0;
    if (n < 1000) return `${Math.max(0.1, n / 1000).toFixed(1)}s`;
    const s = n / 1000;
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
  }

  function relativeTime(iso) {
    const t = new Date(iso).getTime();
    const diff = (Date.now() - t) / 1000;
    if (diff < 45) return "just now";
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  const ICONS = {
    history: '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    panel: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>',
    beaker: '<path d="M9 3h6M10 3v6l-5.6 9.4A2 2 0 0 0 6.1 21h11.8a2 2 0 0 0 1.7-2.6L14 9V3"/><path d="M7.5 15h9"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    spark: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    alert: '<path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.9-3M4 13a8 8 0 0 0 14.9 3"/><path d="M4 4v4h4M20 20v-4h-4"/>',
    send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    gauge: '<path d="M12 14l4-4"/><path d="M3.5 18a9 9 0 1 1 17 0"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
    read: '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    think: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.8 10.6c.6.6.8 1.3.8 2.4h6c0-1.1.2-1.8.8-2.4A6 6 0 0 0 12 3z"/>',
    browse: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.7 5.7 3.7 9s-1.2 6.3-3.7 9M12 3C9.5 5.7 8.3 8.7 8.3 12s1.2 6.3 3.7 9"/>',
    wait: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    write: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
    shield: '<path d="M12 3 4.5 6v6c0 4.6 3.2 7.8 7.5 9 4.3-1.2 7.5-4.4 7.5-9V6z"/><path d="m9 12 2 2 4-4"/>',
    save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7M8 21v-7h8v7"/>',
    run: '<path d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.8l-12-7.5A1 1 0 0 0 7 4.5z"/>',
    investigate: '<path d="M9 8V6.5a3 3 0 0 1 6 0V8"/><rect x="7" y="8" width="10" height="12" rx="5"/><path d="M3 13h4M17 13h4M4.5 7.5 7 9M19.5 7.5 17 9M4.5 19 7 17M19.5 19 17 17M12 12v5"/>',
    report: '<path d="M4 20V11M10 20V5M16 20v-6M21 20H3"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
  };
  const KIND_ICON = {
    read: "read",
    think: "think",
    browse: "browse",
    wait: "wait",
    write: "write",
    check: "shield",
    save: "save",
    run: "run",
    investigate: "investigate",
    report: "report",
  };

  function icon(name, cls) {
    return `<svg class="ico${cls ? ` ${cls}` : ""}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  }

  function hydrateIcons(root) {
    root.querySelectorAll(".i[data-icon]").forEach((el) => {
      if (!el.firstElementChild) el.innerHTML = icon(el.getAttribute("data-icon"));
    });
  }

  function toast(text, level) {
    const host = $("toastHost");
    const el = document.createElement("div");
    el.className = `toast ${level || "info"}`;
    el.innerHTML = `${icon(level === "error" ? "alert" : "check")}<span>${escapeHtml(text)}</span>`;
    host.appendChild(el);
    setTimeout(() => el.classList.add("leaving"), 3200);
    setTimeout(() => el.remove(), 3600);
  }

  // ------------------------------------------------------------------ stages

  const SEGMENTS = [
    { label: "Scope", stages: ["STAGE_0_SCOPE"] },
    { label: "Analyze", stages: ["STAGE_1_INTAKE", "STAGE_2_ANALYSIS"] },
    { label: "Explore", stages: ["STAGE_3_EXPLORATION"] },
    { label: "Design", stages: ["STAGE_4_TEST_DESIGN"] },
    { label: "Review", stages: ["STAGE_5_REVIEW_LOOP"] },
    { label: "Dry run", stages: ["STAGE_6_SCRIPT_GEN", "STAGE_7_DRY_RUN"] },
    { label: "Execute", stages: ["STAGE_8_EXECUTION"] },
    { label: "Report", stages: ["STAGE_9_INVESTIGATION", "STAGE_10_SIGN_OFF"] },
  ];
  const STAGE_NAMES = {
    STAGE_0_SCOPE: "Scope",
    STAGE_1_INTAKE: "Intake",
    STAGE_2_ANALYSIS: "Analysis",
    STAGE_3_EXPLORATION: "Exploration",
    STAGE_4_TEST_DESIGN: "Design",
    STAGE_5_REVIEW_LOOP: "Review",
    STAGE_6_SCRIPT_GEN: "Scripts",
    STAGE_7_DRY_RUN: "Dry run",
    STAGE_8_EXECUTION: "Execution",
    STAGE_9_INVESTIGATION: "Investigation",
    STAGE_10_SIGN_OFF: "Reports",
    COMPLETED: "Completed",
    CANCELLED: "Cancelled",
    ERROR: "Error",
  };
  const KIND_LABEL = {
    suite: "New suite",
    update: "Suite update",
    retest: "Retest",
    "retest-failed": "Failed-case retest",
    regression: "Regression",
  };
  const WAITING_CARDS = new Set(["scope_card", "clarification_card", "review_card", "dry_run_card"]);
  const LIVE_STATES = new Set(["running", "waiting"]);

  function segmentIndex(stage) {
    return SEGMENTS.findIndex((s) => s.stages.includes(stage));
  }

  (function buildTrack() {
    $("stageTrack").innerHTML = SEGMENTS.map(
      (s, i) => `<div class="seg" data-i="${i}" title="${escapeHtml(s.label)}"><span class="seg-bar"></span><span class="seg-label">${escapeHtml(s.label)}</span></div>`
    ).join("");
  })();

  // ------------------------------------------------------------------ views (live + replay)

  /**
   * A view renders one session's events into a container. The live view receives events as
   * they happen; a replay view renders a stored session read-only.
   */
  function createView(container, readOnly) {
    return {
      container,
      readOnly,
      session: null,
      status: "idle",
      stage: "",
      description: "",
      reached: -1,
      stream: null,
      group: null,
      steps: new Map(),
      runningStep: null,
      looseLog: null,
    };
  }

  const liveView = createView(chatContainer, false);
  let replayView = null;
  let visibleView = liveView;

  function nearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function scrollView(view, force) {
    const el = view.container;
    if (force || view.stickToBottom !== false) el.scrollTop = el.scrollHeight;
  }

  [chatContainer, replayContainer].forEach((el) => {
    el.addEventListener("scroll", () => {
      const view = el === chatContainer ? liveView : replayView;
      if (view) view.stickToBottom = nearBottom(el);
    });
  });

  function append(view, el) {
    const welcome = view.container.querySelector(".welcome");
    if (welcome) welcome.remove();
    view.container.appendChild(el);
    hydrateIcons(el);
    scrollView(view);
    return el;
  }

  /** Close the current step group (a message, card, or log arrived between steps). */
  function breakGroup(view) {
    const group = view.group;
    if (!group) return;
    view.group = null;
    finishGroup(group);
  }

  function finishGroup(group) {
    const rows = group.querySelectorAll(".step");
    const failed = group.querySelectorAll(".step.failed, .step.cancelled").length;
    const running = group.querySelectorAll(".step.running").length;
    if (!running && rows.length >= 3 && !failed && !group.classList.contains("pinned")) {
      group.classList.remove("open");
    }
  }

  function updateGroupHead(group) {
    const rows = [...group.querySelectorAll(".step")];
    group.classList.toggle("multi", rows.length >= 2);
    const running = rows.find((r) => r.classList.contains("running"));
    const failed = rows.filter((r) => r.classList.contains("failed")).length;
    const total = rows.reduce((n, r) => n + Number(r.getAttribute("data-ms") || 0), 0);
    const label = group.querySelector(".group-label");
    const meta = group.querySelector(".group-meta");
    const headIcon = group.querySelector(".group-icon");
    group.classList.toggle("running", Boolean(running));
    group.classList.toggle("has-failed", failed > 0);
    if (running) {
      label.textContent = running.querySelector(".step-title").textContent || "Working";
      label.classList.add("shimmer");
      meta.textContent = `${rows.length} steps`;
      headIcon.innerHTML = `<span class="spinner"></span>`;
    } else {
      label.classList.remove("shimmer");
      label.textContent = failed ? `${rows.length} steps · ${failed} with problems` : `Completed ${rows.length} steps`;
      meta.textContent = formatDuration(total);
      headIcon.innerHTML = icon(failed ? "alert" : "check");
    }
  }

  function ensureGroup(view) {
    if (view.group) return view.group;
    const group = document.createElement("div");
    group.className = "step-group open";
    group.innerHTML = `
      <button class="group-head" type="button">
        <span class="group-icon"></span>
        <span class="group-label">Working</span>
        <span class="group-meta"></span>
        ${icon("chevron", "chev")}
      </button>
      <div class="group-body"><div class="group-inner"></div></div>`;
    group.querySelector(".group-head").addEventListener("click", () => {
      group.classList.toggle("open");
      group.classList.add("pinned");
    });
    view.group = group;
    append(view, group);
    return group;
  }

  function renderActivity(view, msg) {
    if (msg.phase === "start") {
      if (view.stream) view.stream = null;
      view.looseLog = null;
      const group = ensureGroup(view);
      const row = document.createElement("div");
      row.className = "step running";
      row.setAttribute("data-kind", msg.kind || "think");
      row.innerHTML = `
        <span class="step-icon">${icon(KIND_ICON[msg.kind] || "think")}<span class="step-state"></span></span>
        <div class="step-main">
          <div class="step-title shimmer">${escapeHtml(msg.title)}</div>
          <div class="step-detail">${escapeHtml(msg.detail || "")}</div>
        </div>
        <span class="step-time"><span class="spinner"></span></span>`;
      if (msg.detail) row.title = msg.detail;
      group.querySelector(".group-inner").appendChild(row);
      view.steps.set(msg.id, row);
      view.runningStep = row;
      if (msg.kind === "wait") setViewStatus(view, "waiting");
      else if (view.status === "waiting" || view.status === "idle") setViewStatus(view, "running");
      updateGroupHead(group);
      scrollView(view);
      return;
    }
    const row = view.steps.get(msg.id);
    if (!row) return;
    const detail = row.querySelector(".step-detail");
    if (msg.phase === "update") {
      detail.textContent = msg.detail || "";
      detail.classList.remove("tick");
      void detail.offsetWidth;
      detail.classList.add("tick");
      return;
    }
    // end
    const status = msg.status || "done";
    row.classList.remove("running");
    row.classList.add(status);
    row.setAttribute("data-ms", String(msg.duration_ms || 0));
    row.querySelector(".step-title").classList.remove("shimmer");
    if (msg.detail) detail.textContent = msg.detail;
    row.querySelector(".step-state").innerHTML = icon(status === "done" ? "check" : status === "cancelled" ? "stop" : "x");
    row.querySelector(".step-time").textContent = formatDuration(msg.duration_ms);
    const log = row.querySelector(".step-log");
    if (log && status === "done") log.classList.remove("open");
    if (view.runningStep === row) view.runningStep = null;
    if (row.getAttribute("data-kind") === "wait" && view.status === "waiting") setViewStatus(view, "running");
    const group = row.closest(".step-group");
    if (group) updateGroupHead(group);
  }

  function logBlock(title) {
    const wrap = document.createElement("div");
    wrap.className = "step-log open";
    wrap.innerHTML = `
      <button class="log-head" type="button">${icon("terminal")}<span class="log-title">${escapeHtml(title)}</span><span class="log-count"></span>${icon("chevron", "chev")}</button>
      <div class="log-body"><pre class="log-block"></pre></div>`;
    wrap.querySelector(".log-head").addEventListener("click", () => wrap.classList.toggle("open"));
    return wrap;
  }

  function appendLog(view, msg) {
    let target = null;
    const step = view.runningStep;
    if (step) {
      target = step.querySelector(".step-log");
      if (!target && msg.chunk) {
        target = logBlock(step.getAttribute("data-kind") === "run" ? "pytest output" : "Output");
        step.querySelector(".step-main").appendChild(target);
      }
    } else {
      if (!view.looseLog && msg.chunk) {
        breakGroup(view);
        view.looseLog = append(view, logBlock("Output"));
      }
      target = view.looseLog;
    }
    if (!target) return;
    const pre = target.querySelector("pre");
    if (msg.chunk) {
      pre.textContent += msg.chunk;
      const lines = pre.textContent.split("\n").filter(Boolean).length;
      target.querySelector(".log-count").textContent = `${lines} line${lines === 1 ? "" : "s"}`;
      pre.scrollTop = pre.scrollHeight;
    }
    if (msg.complete) view.looseLog = null;
    scrollView(view);
  }

  function appendBubble(view, sender, text) {
    breakGroup(view);
    const bubble = document.createElement("div");
    bubble.className = `msg ${sender}`;
    if (sender.includes("error")) {
      bubble.innerHTML = `${icon("alert", "msg-icon")}<div class="msg-body"></div>`;
    } else if (sender === "assistant") {
      bubble.innerHTML = `<span class="avatar">${icon("spark")}</span><div class="msg-body"></div>`;
    } else {
      bubble.innerHTML = `<div class="msg-body"></div>`;
    }
    bubble.querySelector(".msg-body").innerHTML = formatText(text);
    bubble.dataset.raw = text;
    return append(view, bubble);
  }

  function sessionIntro(view, session) {
    const el = document.createElement("div");
    el.className = "session-intro";
    el.innerHTML = `
      <span class="kind-chip" data-kind="${escapeHtml(session.kind)}">${escapeHtml(KIND_LABEL[session.kind] || session.kind)}</span>
      <div class="intro-title">${escapeHtml(session.title)}</div>
      <div class="intro-sub">${escapeHtml(session.subtitle || "")} &middot; ${escapeHtml(new Date(session.startedAt).toLocaleString())}</div>`;
    append(view, el);
  }

  function setViewStatus(view, status) {
    view.status = status;
    if (view === visibleView) renderHeader();
  }

  function handleEvent(view, msg) {
    switch (msg.type) {
      case "user":
        appendBubble(view, "user", msg.text);
        break;
      case "notice":
        appendBubble(view, "assistant error", msg.text);
        break;
      case "activity":
        renderActivity(view, msg);
        break;
      case "message.stream":
        if (msg.style === "log") {
          appendLog(view, msg);
          break;
        }
        if (!view.stream) view.stream = appendBubble(view, "assistant", "");
        view.stream.dataset.raw = (view.stream.dataset.raw || "") + (msg.chunk || "");
        view.stream.querySelector(".msg-body").innerHTML = formatText(view.stream.dataset.raw);
        if (msg.complete) view.stream = null;
        scrollView(view);
        break;
      case "card.show":
        renderCard(view, msg.card_type, msg.data || {});
        break;
      case "stage.update": {
        view.stage = String(msg.stage || "");
        view.description = msg.description || "";
        const idx = segmentIndex(view.stage);
        if (idx >= 0) view.reached = idx;
        if (view.stage === "CANCELLED") view.status = "cancelled";
        else if (view.stage === "ERROR" && !(view.session && view.session.kind === "regression")) view.status = "error";
        else if (view.stage !== "COMPLETED" && view.status === "waiting" && view.stage !== "STAGE_5_REVIEW_LOOP") view.status = "running";
        if (view === visibleView) renderHeader();
        break;
      }
    }
  }

  function renderHeader() {
    const view = visibleView;
    const header = $("runHeader");
    const badge = $("stageBadge");
    const s = view.status;
    header.setAttribute("data-state", s);
    $("runTitle").textContent = view.session
      ? `${KIND_LABEL[view.session.kind] || "Run"} · ${view.session.title}`
      : "Ready";
    $("stageDesc").textContent =
      view.description ||
      (view.session ? view.session.subtitle : "Paste a URL or open Suites to start a run");
    badge.textContent = view.stage ? STAGE_NAMES[view.stage] || view.stage : "Ready";
    badge.className = `stage-badge ${
      s === "error" || s === "failed" ? "error" : s === "passed" ? "done" : s === "cancelled" ? "muted" : s === "waiting" ? "waiting" : view.stage ? "active" : ""
    }`;
    $("btnCancel").hidden = view.readOnly || !LIVE_STATES.has(s);

    const startAt = view.session && view.session.kind && view.session.kind.startsWith("retest") ? 6 : view.session && view.session.kind === "regression" ? 6 : 0;
    const finished = view.stage === "COMPLETED" || ["passed", "failed"].includes(s);
    $("stageTrack").querySelectorAll(".seg").forEach((seg) => {
      const i = Number(seg.getAttribute("data-i"));
      seg.className = "seg";
      if (!view.session) return;
      if (i < startAt) seg.classList.add("skipped");
      else if (finished || i < view.reached) seg.classList.add("done");
      else if (i === view.reached) {
        seg.classList.add(s === "error" ? "error" : s === "cancelled" ? "cancelled" : s === "waiting" ? "waiting" : "active");
      }
    });
    $("stageTrack").classList.toggle("visible", Boolean(view.session));
  }

  function showView(view) {
    visibleView = view;
    const replay = view !== liveView;
    chatContainer.hidden = replay;
    replayContainer.hidden = !replay;
    $("inputDock").hidden = replay;
    $("replayBanner").hidden = !replay;
    if (replay) {
      const live = liveView.session && LIVE_STATES.has(liveView.status);
      $("btnBackLive").classList.toggle("pulse", Boolean(live));
      $("replayText").textContent = live ? "Viewing a past run · a run is live" : "Viewing a past run (read-only)";
    }
    renderHeader();
    renderHistory();
  }

  // ------------------------------------------------------------------ tabs

  function moveIndicator() {
    const active = document.querySelector(".tab.active");
    const indicator = $("tabIndicator");
    if (!active) return;
    indicator.style.width = `${active.offsetWidth}px`;
    indicator.style.transform = `translateX(${active.offsetLeft}px)`;
  }

  function switchTab(tab) {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t.getAttribute("data-tab") === tab);
    });
    ["assistant", "suites", "ai"].forEach((name) => {
      const panel = $(`panel-${name}`);
      const show = name === tab;
      if (show && panel.hidden) {
        panel.hidden = false;
        panel.classList.remove("enter");
        void panel.offsetWidth;
        panel.classList.add("enter");
      } else if (!show) {
        panel.hidden = true;
      }
    });
    moveIndicator();
    if (tab === "suites") post("refreshSuites");
  }

  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchTab(t.getAttribute("data-tab")))
  );
  new ResizeObserver(moveIndicator).observe(document.querySelector(".tabs"));

  // ------------------------------------------------------------------ history sidebar

  let historySessions = [];
  let historyActiveId = null;
  let historyFilter = "all";
  const seenHistory = new Set();

  function isWide() {
    return window.matchMedia("(min-width: 720px)").matches;
  }

  function toggleHistory(open) {
    if (isWide()) {
      app.classList.toggle("history-collapsed", open === undefined ? !app.classList.contains("history-collapsed") : !open);
    } else {
      app.classList.toggle("history-open", open === undefined ? !app.classList.contains("history-open") : open);
    }
    if (app.classList.contains("history-open") || !app.classList.contains("history-collapsed")) {
      post("history.list");
    }
  }

  $("btnHistory").addEventListener("click", () => toggleHistory());
  $("btnHistoryClose").addEventListener("click", () => toggleHistory(false));
  $("scrim").addEventListener("click", () => toggleHistory(false));
  $("historySearch").addEventListener("input", renderHistory);
  $("historyFilters").querySelectorAll(".filter").forEach((b) =>
    b.addEventListener("click", () => {
      historyFilter = b.getAttribute("data-filter");
      $("historyFilters").querySelectorAll(".filter").forEach((x) => x.classList.toggle("active", x === b));
      renderHistory();
    })
  );

  function bucket(iso) {
    const d = new Date(iso);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const day = 86400000;
    if (d.getTime() >= today.getTime()) return "Today";
    if (d.getTime() >= today.getTime() - day) return "Yesterday";
    if (d.getTime() >= today.getTime() - 7 * day) return "Previous 7 days";
    return "Older";
  }

  function renderHistory() {
    const list = $("historyList");
    const query = $("historySearch").value.trim().toLowerCase();
    const items = historySessions.filter((s) => {
      if (historyFilter === "suite" && !["suite", "update"].includes(s.kind)) return false;
      if (historyFilter === "retest" && !s.kind.startsWith("retest")) return false;
      if (historyFilter === "regression" && s.kind !== "regression") return false;
      return !query || `${s.title} ${s.subtitle} ${KIND_LABEL[s.kind] || ""}`.toLowerCase().includes(query);
    });
    if (!items.length) {
      list.innerHTML = `<div class="history-empty">${icon("history")}<span>${
        historySessions.length ? "No runs match." : "Runs you start appear here, each with its full step-by-step transcript."
      }</span></div>`;
      return;
    }
    const viewing = visibleView === liveView ? historyActiveId : replayView && replayView.session && replayView.session.id;
    let html = "";
    let current = "";
    for (const s of items) {
      const b = bucket(s.startedAt);
      if (b !== current) {
        current = b;
        html += `<div class="history-bucket">${escapeHtml(b)}</div>`;
      }
      const live = LIVE_STATES.has(s.status);
      const result = s.result ? `${s.result.passed}/${s.result.total}` : "";
      const fresh = !seenHistory.has(s.id);
      seenHistory.add(s.id);
      html += `
        <div class="history-item${s.id === viewing ? " selected" : ""}${fresh ? " enter" : ""}" data-id="${escapeHtml(s.id)}" role="button" tabindex="0">
          <span class="h-dot" data-status="${escapeHtml(s.status)}"></span>
          <div class="h-main">
            <div class="h-title">${escapeHtml(s.title)}</div>
            <div class="h-sub"><span class="h-kind" data-kind="${escapeHtml(s.kind)}">${escapeHtml(KIND_LABEL[s.kind] || s.kind)}</span>${escapeHtml(s.subtitle || "")}</div>
          </div>
          <div class="h-side">
            ${live ? `<span class="live-tag">${s.status === "waiting" ? "WAITING" : "LIVE"}</span>` : `<span class="h-time">${escapeHtml(relativeTime(s.startedAt))}</span>`}
            ${result ? `<span class="h-result ${s.result.failed ? "bad" : "good"}">${escapeHtml(result)}</span>` : `<span class="h-steps">${escapeHtml(s.steps)} steps</span>`}
          </div>
          ${live ? "" : `<button class="icon-btn h-delete" data-del="${escapeHtml(s.id)}" title="Remove from history">${icon("trash")}</button>`}
        </div>`;
    }
    list.innerHTML = html;
    list.querySelectorAll(".history-item").forEach((el) => {
      const id = el.getAttribute("data-id");
      const open = () => openHistory(id);
      el.addEventListener("click", (e) => {
        if (/** @type {HTMLElement} */ (e.target).closest(".h-delete")) return;
        open();
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
    list.querySelectorAll(".h-delete").forEach((b) =>
      b.addEventListener("click", () => post("history.delete", { id: b.getAttribute("data-del") }))
    );
  }

  function openHistory(id) {
    if (!isWide()) app.classList.remove("history-open");
    switchTab("assistant");
    if (id === historyActiveId && liveView.session && liveView.session.id === id) {
      showView(liveView);
      return;
    }
    post("history.open", { id });
  }

  function renderReplay(session) {
    replayContainer.innerHTML = "";
    replayContainer.classList.add("no-anim");
    const view = createView(replayContainer, true);
    view.session = session;
    view.status = "running";
    replayView = view;
    sessionIntro(view, session);
    for (const event of session.events || []) {
      try {
        handleEvent(view, event);
      } catch {
        // a malformed stored event must not break the rest of the replay
      }
    }
    breakGroup(view);
    view.container.querySelectorAll(".step.running").forEach((row) => {
      row.classList.remove("running");
      row.classList.add("cancelled");
      row.querySelector(".step-title").classList.remove("shimmer");
      row.querySelector(".step-time").textContent = "stopped";
    });
    view.container.querySelectorAll(".step-group").forEach((g) => updateGroupHead(g));
    view.status = session.status;
    const ended = session.endedAt ? new Date(session.endedAt).getTime() - new Date(session.startedAt).getTime() : 0;
    const outro = document.createElement("div");
    outro.className = `session-outro ${escapeHtml(session.status)}`;
    outro.innerHTML = `<span class="h-dot" data-status="${escapeHtml(session.status)}"></span>${escapeHtml(
      { passed: "Run passed", failed: "Run finished with failures", error: "Run stopped with an error", cancelled: "Run cancelled" }[session.status] ||
        "Run in progress when recorded"
    )}${ended ? ` &middot; ${escapeHtml(formatDuration(ended))}` : ""} &middot; ${escapeHtml(session.steps)} steps`;
    append(view, outro);
    showView(view);
    replayContainer.scrollTop = 0;
    requestAnimationFrame(() => replayContainer.classList.remove("no-anim"));
  }

  $("btnBackLive").addEventListener("click", () => showView(liveView));

  // ------------------------------------------------------------------ header state

  function renderState() {
    const ai = state.ai;
    const chipAi = $("chipAi");
    if (ai) {
      chipAi.querySelector(".chip-text").textContent = ai.ready ? ai.providerLabel.split(" (")[0] : "AI not connected";
      chipAi.className = `chip ${ai.ready ? "chip-ok" : "chip-warn"}`;
      chipAi.title = ai.detail;
    }
    const chipUser = $("chipUser");
    chipUser.querySelector(".chip-text").textContent = state.identity ? `@${state.identity}` : "Sign in";
    chipUser.className = `chip ${state.identity ? "" : "chip-warn"}`;
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
      $("aiKeyState").className = `chip ${ai.hasKey ? "chip-ok" : ""}`;
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
    $("aiStatus").className = "ai-status busy";
    post("ai.models");
  });
  $("btnTestAi").addEventListener("click", () => {
    saveAi();
    $("aiStatus").textContent = "Testing connection ...";
    $("aiStatus").className = "ai-status busy";
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
    suiteForm.classList.remove("pop");
    void suiteForm.offsetWidth;
    suiteForm.classList.add("pop");
    suiteForm.scrollIntoView({ behavior: "smooth", block: "start" });
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
      list.innerHTML = `<div class="empty-state">${icon("alert")}<p>Set up the engine to manage suites.</p></div>`;
      return;
    }
    if (!suites.length) {
      list.innerHTML = `<div class="empty-state">${icon("layers")}<p>No suites yet. Click <strong>New Suite</strong> to create one from a requirement and acceptance criteria.</p></div>`;
      return;
    }
    list.innerHTML = suites
      .map((s, i) => {
        const run = s.last_run;
        const when = run ? relativeTime(run.started_at) : "";
        const types = (s.test_types || []).map((t) => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("");
        const envs = [`${s.environment} (default)`, ...Object.keys(s.environments || {})];
        const lastEnv = run && run.environment ? ` on ${escapeHtml(run.environment)}` : "";
        const tone = !run ? "none" : run.failed || run.blocked ? "bad" : "good";
        return `
        <div class="suite-card" data-slug="${escapeHtml(s.slug)}" data-tone="${tone}" data-i="${i}">
          <div class="suite-head">
            <div class="suite-name"><span class="suite-mark">${escapeHtml(String(s.module).slice(0, 1).toUpperCase())}</span><strong>${escapeHtml(s.module)}</strong></div>
            ${statusBadge(run)}
          </div>
          ${run ? `<div class="pass-bar"><span class="pass-fill" data-pass="${escapeHtml(run.total ? run.passed / run.total : 0)}"></span></div>` : ""}
          <div class="suite-meta">
            <span>${icon("browse")}${escapeHtml(s.start_url)}</span>
            <span>${icon("layers")}v${escapeHtml(s.current_version)} &middot; ${escapeHtml(s.total_cases)} case(s) &middot; ${escapeHtml(envs.join(", "))}</span>
            ${run ? `<span>${icon("history")}Last ${escapeHtml(run.run_type)}${lastEnv} ${escapeHtml(when)} by ${escapeHtml(run.triggered_by)}</span>` : ""}
          </div>
          <div class="suite-tags">${types}</div>
          <div class="action-buttons">
            <button class="btn-primary" data-act="retest">${icon("run")}Retest all</button>
            <button class="btn-secondary" data-act="retestFailed" ${s.failed_count ? "" : "disabled"}>Retest failed (${escapeHtml(s.failed_count)})</button>
            <button class="btn-secondary" data-act="cases">Cases</button>
            ${run && run.report_html ? `<button class="btn-secondary" data-act="report">Report</button>` : ""}
            <button class="btn-secondary" data-act="secrets">Secrets${(s.required_secrets || []).length ? ` (${s.required_secrets.length})` : ""}</button>
            <button class="btn-secondary" data-act="update">Update</button>
            <button class="btn-secondary btn-danger" data-act="delete">${icon("trash")}Delete</button>
          </div>
        </div>`;
      })
      .join("");

    list.querySelectorAll(".suite-card").forEach((card) => {
      const slug = card.getAttribute("data-slug");
      const suite = suites.find((s) => s.slug === slug);
      card.style.setProperty("--i", card.getAttribute("data-i"));
      const fill = card.querySelector(".pass-fill");
      if (fill) requestAnimationFrame(() => (fill.style.width = `${Math.round(Number(fill.getAttribute("data-pass")) * 100)}%`));
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

  const CARD_META = {
    scope_card: { icon: "shield", accent: "check" },
    clarification_card: { icon: "think", accent: "think" },
    review_card: { icon: "read", accent: "read" },
    dry_run_card: { icon: "alert", accent: "wait" },
    report_card: { icon: "report", accent: "report" },
    regression_card: { icon: "layers", accent: "run" },
  };

  function renderCard(view, cardType, data) {
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
    breakGroup(view);
    view.stream = null;
    const card = document.createElement("div");
    card.className = "decision-card";
    const meta = CARD_META[cardType];
    card.setAttribute("data-accent", meta.accent);
    render(card, data);
    const h3 = card.querySelector("h3");
    if (h3) h3.insertAdjacentHTML("afterbegin", `<span class="card-icon">${icon(meta.icon)}</span>`);
    if (view.readOnly) {
      card.classList.add("read-only");
      card.querySelectorAll("input, textarea, select").forEach((el) => el.setAttribute("disabled", "true"));
      card.querySelectorAll("button").forEach((b) => {
        if (!b.hasAttribute("data-safe")) b.setAttribute("disabled", "true");
      });
    }
    append(view, card);

    if (WAITING_CARDS.has(cardType)) setViewStatus(view, "waiting");
    if (cardType === "report_card" || cardType === "regression_card") {
      const t = cardType === "regression_card" ? data.totals || {} : data;
      const failed = Number(t.failed || 0) + Number(t.blocked || 0);
      const errors = cardType === "regression_card" && (data.suites || []).some((s) => s.status === "error");
      if (cardType === "regression_card" || !view.session || view.session.kind !== "regression") {
        setViewStatus(view, failed || errors ? "failed" : "passed");
      }
    }
  }

  function field(label, value) {
    return `<div class="card-field"><span class="card-label">${label}</span><div class="card-value">${value}</div></div>`;
  }

  function renderScopeCard(card, data) {
    const domains = (data.allowed_domains || []).join(", ");
    const env = data.environment || "";
    card.innerHTML = `
      <h3>Scope &amp; Authorization <span class="gate">Gate 0</span></h3>
      ${field("Suite", `${escapeHtml(data.module)} ${data.updates_existing_suite ? '<span class="pill">new version of existing suite</span>' : ""}`)}
      ${field("Design", data.design_mode === "ai" ? `AI from requirement (${escapeHtml(data.criteria_count)} acceptance criteria)` : "Smoke design from page structure")}
      ${field("Target URL", escapeHtml(data.start_url))}
      <label class="card-label" for="scopeDomains">Allowed domains (comma separated)</label>
      <input id="scopeDomains" value="${escapeHtml(domains)}" />
      <label class="card-label" for="scopeEnv">Environment</label>
      <input id="scopeEnv" list="envSuggestions" value="${escapeHtml(env)}" placeholder="e.g. test, staging, uat" />
      <label class="attestation-box">
        <input type="checkbox" id="chkAttest" />
        <span><strong>Authorization:</strong> I confirm that I am authorized to test this target, and all browsing stays within the domains above.</span>
      </label>
      <div class="card-error" id="scopeError" hidden></div>
      <div class="action-buttons"><button class="btn-primary" id="btnConfirmScope">${icon("check")}Confirm Scope</button></div>`;

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
      card.classList.add("resolved");
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
        return `<div class="card-field question">
          <span class="card-label">${escapeHtml(q.question_id || `Q-${i + 1}`)}</span>
          <div class="q-text">${escapeHtml(q.question_text)}</div>
          ${q.context ? `<div class="muted small">${escapeHtml(q.context)}</div>` : ""}
          ${input}</div>`;
      })
      .join("");
    card.innerHTML = `
      <h3>Clarifications needed</h3>
      <p class="muted">${escapeHtml(data.summary)}</p>
      ${fields}
      <div class="action-buttons"><button class="btn-primary" id="btnAnswer">${icon("send")}Submit answers</button></div>`;
    card.querySelector("#btnAnswer").addEventListener("click", () => {
      const answers = {};
      card.querySelectorAll("[data-qid]").forEach((el) => {
        answers[el.getAttribute("data-qid")] = el.value;
      });
      post("answerClarifications", { answers });
      card.querySelector("#btnAnswer").setAttribute("disabled", "true");
      card.classList.add("resolved");
    });
  }

  function renderReviewCard(card, data) {
    const cases = data.testcases || [];
    const rows = cases
      .map(
        (tc) => `
        <details class="tc-item">
          <summary>${icon("chevron", "chev")}<strong>${escapeHtml(tc.tc_id)}</strong><span class="tc-title">${escapeHtml(tc.title)}</span>
            <span class="pill">${escapeHtml(tc.priority)}</span>${tc.ac_ref ? `<span class="pill">${escapeHtml(tc.ac_ref)}</span>` : ""}
            ${(tc.test_types || []).map((t) => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("")}</summary>
          <div class="tc-body">
            <ol>${(tc.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>
            <div class="small"><strong>Expected:</strong> ${escapeHtml(tc.expected_result)}</div>
            <div class="small muted"><strong>Automation:</strong> ${(tc.actions || []).map(escapeHtml).join(" &rarr; ")}</div>
          </div>
        </details>`
      )
      .join("");
    const coverage = (data.coverage || [])
      .map((c) => `<li class="${c.has_gaps ? "result-fail" : ""}">${escapeHtml(c.requirement_id)}: ${escapeHtml(c.requirement_text)} &rarr; ${escapeHtml((c.covered_test_case_ids || []).join(", ") || "NOT COVERED")}</li>`)
      .join("");
    const secrets = (data.required_secrets || []).map((s) => `<span class="domain-tag">${escapeHtml(s)}</span>`).join("");
    const unverified = (data.unverified_locators || []).map((u) => `<li>${escapeHtml(u)}</li>`).join("");
    const pct = Number(data.coverage_percentage || 0);

    card.innerHTML = `
      <h3>Test Case Review <span class="gate">Gate 1</span><span class="h3-sub">${escapeHtml(data.module)} v${escapeHtml(data.version)} &middot; ${escapeHtml(cases.length)} case(s)</span></h3>
      ${data.diff_summary ? `<p class="pill diff">${escapeHtml(data.diff_summary)}</p>` : ""}
      <p class="muted small">Approving binds exactly these cases to SHA-256 <code>${escapeHtml(String(data.sha256_hash).slice(0, 16))}...</code>, then generates and runs the scripts.</p>
      <div class="tc-list">${rows}</div>
      ${coverage ? `<div class="card-field"><span class="card-label">Acceptance criteria coverage</span><div class="coverage"><div class="coverage-bar"><span class="coverage-fill" data-pct="${escapeHtml(pct)}"></span></div><span class="coverage-pct">${escapeHtml(pct)}%</span></div><ul class="small">${coverage}</ul></div>` : ""}
      ${secrets ? `<div class="card-field"><span class="card-label">Secrets needed at run time</span><div>${secrets}</div><div class="muted small">You will be asked for each value once; it is kept in the OS keychain.</div></div>` : ""}
      ${unverified ? `<details class="small unverified"><summary>Locators not seen during exploration (${(data.unverified_locators || []).length})</summary><ul>${unverified}</ul></details>` : ""}
      ${data.can_revise ? `<label class="card-label" for="reviewComments">Request changes</label><textarea id="reviewComments" rows="2" placeholder="e.g. add a negative case for an empty password; drop TC-...-003"></textarea>` : ""}
      <div class="action-buttons">
        <button class="btn-primary" id="btnApproveCases">${icon("check")}Approve &amp; Run</button>
        ${data.can_revise ? `<button class="btn-secondary" id="btnRevise">Request changes</button>` : ""}
        <button class="btn-secondary" id="btnOpenCases" data-safe>${icon("external")}Open as Markdown</button>
      </div>`;

    const fill = card.querySelector(".coverage-fill");
    if (fill) requestAnimationFrame(() => (fill.style.width = `${Math.max(0, Math.min(100, pct))}%`));
    const disableAll = () => {
      card.querySelectorAll("button:not([data-safe])").forEach((b) => b.setAttribute("disabled", "true"));
      card.classList.add("resolved");
    };
    card.querySelector("#btnApproveCases").addEventListener("click", () => {
      post("approveTestcases", { version: data.version, sha256_hash: data.sha256_hash });
      disableAll();
    });
    card.querySelector("#btnOpenCases").addEventListener("click", () => post("openFile", { path: data.testcases_md }));
    const revise = card.querySelector("#btnRevise");
    if (revise) {
      revise.addEventListener("click", () => {
        const box = card.querySelector("#reviewComments");
        const comments = box.value.trim();
        if (!comments) {
          box.classList.remove("shake");
          void box.offsetWidth;
          box.classList.add("shake");
          box.focus();
          return;
        }
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
          ${i.screenshot ? `<button class="btn-secondary btn-sm" data-shot="${escapeHtml(i.screenshot)}" data-safe>Screenshot</button>` : ""}</li>`
      )
      .join("");
    card.innerHTML = `
      <h3>Dry run found ${escapeHtml(issues.length)} problem(s)<span class="h3-sub">${escapeHtml(data.module)}</span></h3>
      <p class="muted small">${escapeHtml(ok)} case(s) executable${blocked ? `, ${escapeHtml(blocked)} blocked by missing secrets` : ""}. Assertions were not evaluated; these steps could not be performed on the live page.</p>
      <ul class="small issue-list">${rows}</ul>
      <div class="action-buttons">
        ${data.can_fix ? `<button class="btn-primary" data-decision="fix">${icon("spark")}Fix with AI (re-approve)</button>` : ""}
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
        card.classList.add("resolved");
      })
    );
  }

  function resultGrid(t) {
    const cells = [
      ["Total", t.total, ""],
      ["Passed", t.passed, "result-pass"],
      ["Failed", t.failed, "result-fail"],
      ["Flaky", t.flaky, "result-warn"],
      ["Blocked", t.blocked, "result-warn"],
    ];
    return `<div class="result-grid">${cells
      .map(([label, value, cls]) => `<div class="stat ${cls}"><span class="card-label">${label}</span><div class="card-value">${escapeHtml(value || 0)}</div></div>`)
      .join("")}</div>`;
  }

  function ring(passed, total) {
    const pct = total ? passed / total : 0;
    const r = 22;
    const c = 2 * Math.PI * r;
    return `<svg class="ring" viewBox="0 0 56 56" aria-hidden="true">
      <circle class="ring-bg" cx="28" cy="28" r="${r}"/>
      <circle class="ring-fg" cx="28" cy="28" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${c.toFixed(1)}" data-offset="${(c * (1 - pct)).toFixed(1)}"/>
      <text x="28" y="32" text-anchor="middle">${Math.round(pct * 100)}%</text></svg>`;
  }

  function animateRing(card) {
    const fg = card.querySelector(".ring-fg");
    if (fg) requestAnimationFrame(() => requestAnimationFrame(() => fg.setAttribute("stroke-dashoffset", fg.getAttribute("data-offset"))));
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
    card.setAttribute("data-tone", failed ? "bad" : "good");
    card.innerHTML = `
      <h3>${escapeHtml(label)} ${failed ? "finished with failures" : "passed"}<span class="h3-sub">${escapeHtml(data.module)}</span></h3>
      <div class="report-top">${ring(Number(data.passed || 0), Number(data.total || 0))}${resultGrid(data)}</div>
      ${(data.failed_tc_ids || []).length ? field("Not passing", escapeHtml(data.failed_tc_ids.join(", "))) : ""}
      ${data.environment ? field("Environment", `${escapeHtml(data.environment)} &middot; ${escapeHtml(data.target_url)}`) : ""}
      ${analysis ? field("Failure analysis", escapeHtml(analysis)) : ""}
      ${field("Duration", `${escapeHtml(data.duration_seconds)} s &middot; by ${escapeHtml(data.triggered_by)}`)}
      <div class="action-buttons">
        <button class="btn-primary" id="btnOpenReport" data-safe>${icon("external")}Open HTML Report</button>
        ${(data.failed_tc_ids || []).length ? `<button class="btn-secondary" id="btnRetestFailed">${icon("refresh")}Retest failed</button>` : ""}
      </div>`;
    animateRing(card);
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
    card.setAttribute("data-tone", t.failed || errors ? "bad" : "good");
    card.innerHTML = `
      <h3>Regression ${t.failed || errors ? "finished with failures" : "passed"}${filters ? `<span class="h3-sub">${filters}</span>` : ""}</h3>
      <div class="report-top">${ring(Number(t.passed || 0), Number(t.total || 0))}${resultGrid(t)}</div>
      <div class="table-wrap"><table class="tc-table"><thead><tr><th>Suite</th><th>Status</th><th>Passed</th><th>Newly failing</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted small">AI calls for failure analysis: ${escapeHtml(data.ai_calls || 0)}</p>
      <div class="action-buttons"><button class="btn-primary" id="btnOpenReg" data-safe>${icon("external")}Open Regression Report</button></div>`;
    animateRing(card);
    card.querySelector("#btnOpenReg").addEventListener("click", () => post("openReport", { path: data.report_html }));
  }

  // ------------------------------------------------------------------ extension -> webview

  function startLiveSession(session) {
    chatContainer.innerHTML = "";
    Object.assign(liveView, createView(chatContainer, false), { session, status: "running" });
    sessionIntro(liveView, session);
    historyActiveId = session.id;
    showView(liveView);
  }

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
        if (msg.level === "error") {
          handleEvent(liveView, msg);
          if (visibleView !== liveView) showView(liveView);
          switchTab("assistant");
        } else {
          toast(msg.text, msg.level);
        }
        break;
      case "ai.models": {
        const models = msg.models || [];
        $("aiModelList").innerHTML = models
          .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name)}</option>`)
          .join("");
        $("aiStatus").textContent = models.length
          ? `${models.length} model(s) available. Pick one in the Model field, then Save.`
          : "No models returned; type the model name.";
        $("aiStatus").className = `ai-status ${models.length ? "ok" : "warn"}`;
        break;
      }
      case "ai.testResult":
        $("aiStatus").textContent = msg.ok ? `Connection OK. ${msg.text}` : `Connection failed: ${msg.text}`;
        $("aiStatus").className = `ai-status ${msg.ok ? "ok" : "warn"}`;
        break;
      case "session.start":
        startLiveSession(msg.session);
        break;
      case "history":
        historySessions = msg.sessions || [];
        historyActiveId = msg.activeId || null;
        renderHistory();
        break;
      case "history.session":
        if (msg.live && liveView.session && liveView.session.id === msg.session.id) showView(liveView);
        else renderReplay(msg.session);
        break;
      case "history.deleted":
        historySessions = historySessions.filter((s) => s.id !== msg.id);
        if (replayView && replayView.session && replayView.session.id === msg.id) {
          replayView = null;
          showView(liveView);
        }
        renderHistory();
        toast("Removed from history.");
        break;
      case "user":
      case "activity":
      case "message.stream":
      case "card.show":
      case "stage.update":
        handleEvent(liveView, msg);
        if (visibleView !== liveView && msg.type === "card.show" && WAITING_CARDS.has(msg.card_type)) {
          toast("The live run is waiting for you.", "info");
        }
        break;
    }
  });

  // ------------------------------------------------------------------ welcome + chat input

  chatContainer.querySelectorAll("[data-quick]").forEach((b) =>
    b.addEventListener("click", () => {
      const q = b.getAttribute("data-quick");
      if (q === "newSuite") {
        switchTab("suites");
        openSuiteForm(null);
      }
      if (q === "suites") switchTab("suites");
      if (q === "regression") post("regression", { tag: "" });
      if (q === "history") toggleHistory(true);
    })
  );

  $("btnCancel").addEventListener("click", () => post("cancelRun"));

  function autoGrow() {
    txtPrompt.style.height = "auto";
    txtPrompt.style.height = `${Math.min(160, txtPrompt.scrollHeight)}px`;
    $("btnSend").classList.toggle("ready", Boolean(txtPrompt.value.trim()));
  }

  function handleSend() {
    const text = txtPrompt.value.trim();
    if (!text) return;
    txtPrompt.value = "";
    autoGrow();
    post("userPrompt", { text });
  }

  $("btnSend").addEventListener("click", handleSend);
  txtPrompt.addEventListener("input", autoGrow);
  txtPrompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  window.addEventListener("resize", () => {
    if (isWide()) app.classList.remove("history-open");
  });

  setInterval(() => {
    if (historySessions.length) renderHistoryTimes();
  }, 60000);

  function renderHistoryTimes() {
    $("historyList").querySelectorAll(".history-item").forEach((el) => {
      const s = historySessions.find((x) => x.id === el.getAttribute("data-id"));
      const t = el.querySelector(".h-time");
      if (s && t) t.textContent = relativeTime(s.startedAt);
    });
  }

  hydrateIcons(document.body);
  renderHeader();
  requestAnimationFrame(moveIndicator);
  post("ready");
})();
