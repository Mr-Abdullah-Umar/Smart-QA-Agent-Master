// @ts-check
(function () {
  // @ts-ignore
  const vscode = acquireVsCodeApi();

  const chatContainer = document.getElementById("chatContainer");
  const stageBadge = document.getElementById("stageBadge");
  const stageDesc = document.getElementById("stageDesc");
  const btnCancel = document.getElementById("btnCancel");
  const txtPrompt = document.getElementById("txtPrompt");
  const btnSend = document.getElementById("btnSend");

  let currentStreamBubble = null;

  function escapeHtml(text) {
    if (!text) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function appendMessage(sender, text) {
    const bubble = document.createElement("div");
    bubble.className = `message-bubble ${sender}`;
    bubble.textContent = text;
    chatContainer.appendChild(bubble);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return bubble;
  }

  // Handle messages from Extension Host
  window.addEventListener("message", (event) => {
    const msg = event.data;

    switch (msg.type) {
      case "stage.update": {
        if (stageBadge) {
          stageBadge.textContent = msg.stage.replace("STAGE_", "").replace(/_/g, " ");
          stageBadge.className = "stage-badge active";
        }
        if (stageDesc) {
          stageDesc.textContent = msg.description || "";
        }
        break;
      }

      case "message.stream": {
        if (!currentStreamBubble) {
          currentStreamBubble = appendMessage("assistant", "");
        }
        currentStreamBubble.textContent += msg.chunk;
        if (msg.complete) {
          currentStreamBubble = null;
        }
        chatContainer.scrollTop = chatContainer.scrollHeight;
        break;
      }

      case "card.show": {
        renderCard(msg.card_type, msg.data);
        break;
      }
    }
  });

  function renderCard(cardType, data) {
    const card = document.createElement("div");
    card.className = "decision-card";

    if (cardType === "scope_card") {
      const allowedDomains = (data.allowed_domains || ["staging.example.com"])
        .map((d) => `<span class="domain-tag">${escapeHtml(d)}</span>`)
        .join("");

      card.innerHTML = `
        <h3>🛡️ Scope & Authorization (Gate 0)</h3>
        <div class="card-field">
          <span class="card-label">Target URL</span>
          <div class="card-value">${escapeHtml(data.start_url || "https://staging.example.com")}</div>
        </div>
        <div class="card-field">
          <span class="card-label">Allowed Domains</span>
          <div>${allowedDomains}</div>
        </div>
        <div class="card-field">
          <span class="card-label">Environment</span>
          <div class="card-value"><strong>${escapeHtml(data.environment || "test").toUpperCase()}</strong></div>
        </div>
        <div class="attestation-box">
          <input type="checkbox" id="chkAttest" />
          <label for="chkAttest">
            <strong>Legal Attestation:</strong> I confirm that I am authorized to test this target system, and understand that all interactions will adhere to the agreed domain allowlist.
          </label>
        </div>
        <div class="action-buttons">
          <button class="btn-primary" id="btnConfirmScope">Confirm Scope (Gate 0)</button>
        </div>
      `;

      card.querySelector("#btnConfirmScope").addEventListener("click", () => {
        const checkbox = /** @type {HTMLInputElement} */ (card.querySelector("#chkAttest"));
        if (!checkbox.checked) {
          alert("You must check the authorization attestation before proceeding.");
          return;
        }
        vscode.postMessage({
          command: "confirmScope",
          scope: {
            start_url: data.start_url || "https://staging.example.com",
            allowed_domains: data.allowed_domains || ["staging.example.com"],
            environment: data.environment || "test",
            authorized_attestation: true,
          },
        });
        card.querySelector("#btnConfirmScope").setAttribute("disabled", "true");
      });
    } else if (cardType === "review_card") {
      const cases = data.testcases || [];
      let rows = "";
      for (const tc of cases) {
        rows += `
          <tr>
            <td><strong>${escapeHtml(tc.tc_id)}</strong></td>
            <td>${escapeHtml(tc.title)}</td>
            <td>${escapeHtml(tc.priority || "P2")}</td>
          </tr>
        `;
      }

      card.innerHTML = `
        <h3>📋 Test Case Review (Gate 1 - v${escapeHtml(data.version || 1)})</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">
          Review the drafted test cases below. Approving will bind them to a SHA-256 hash.
        </p>
        <table class="tc-table">
          <thead>
            <tr><th>ID</th><th>Title</th><th>Priority</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="action-buttons">
          <button class="btn-primary" id="btnApproveCases">Approve Cases (Gate 1)</button>
          <button class="btn-secondary" id="btnRequestChanges">Request Changes</button>
        </div>
      `;

      card.querySelector("#btnApproveCases").addEventListener("click", () => {
        vscode.postMessage({
          command: "approveTestcases",
          version: data.version || 1,
          sha256_hash: data.sha256_hash || "dummy-hash",
        });
      });
    }

    chatContainer.appendChild(card);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  // Cancel Button
  if (btnCancel) {
    btnCancel.addEventListener("click", () => {
      vscode.postMessage({ command: "cancelRun" });
    });
  }

  // Send User Prompt
  function handleSend() {
    const text = txtPrompt.value.trim();
    if (!text) return;
    appendMessage("user", text);
    txtPrompt.value = "";
    vscode.postMessage({ command: "userPrompt", text });
  }

  if (btnSend) {
    btnSend.addEventListener("click", handleSend);
  }

  if (txtPrompt) {
    txtPrompt.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
  }
})();

