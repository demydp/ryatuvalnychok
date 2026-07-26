(function () {
  const emptyState = document.getElementById("companion-empty");
  const chatCard = document.getElementById("companion-chat");
  const goSettingsBtn = document.getElementById("btn-companion-go-settings");
  const modelSelect = document.getElementById("companion-model");
  const clearBtn = document.getElementById("btn-companion-clear");
  const examplesEl = document.getElementById("companion-examples");
  const messagesEl = document.getElementById("companion-messages");
  const statusBox = document.getElementById("companion-status");
  const input = document.getElementById("companion-input");
  const sendBtn = document.getElementById("btn-companion-send");

  const MODEL_STORAGE_KEY = "companion_model";

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str === null || str === undefined ? "" : str;
    return div.innerHTML;
  }

  function restoreModel() {
    const saved = localStorage.getItem(MODEL_STORAGE_KEY);
    if (saved && [...modelSelect.options].some((o) => o.value === saved)) {
      modelSelect.value = saved;
    }
  }

  modelSelect.addEventListener("change", () => {
    localStorage.setItem(MODEL_STORAGE_KEY, modelSelect.value);
  });

  function hideStatus() {
    statusBox.className = "status-box";
    statusBox.textContent = "";
  }

  function showStatus(type, message) {
    statusBox.className = `status-box show ${type}`;
    statusBox.textContent = message;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendMessage(role, text) {
    const bubble = document.createElement("div");
    bubble.className = `companion-msg companion-msg-${role}`;
    bubble.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
    messagesEl.appendChild(bubble);
    scrollToBottom();
    return bubble;
  }

  function appendTyping() {
    const bubble = document.createElement("div");
    bubble.className = "companion-msg companion-msg-assistant companion-msg-typing";
    bubble.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(bubble);
    scrollToBottom();
    return bubble;
  }

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }

  function setBusy(busy) {
    sendBtn.disabled = busy;
    input.disabled = busy;
    sendBtn.textContent = busy ? I18N.t("companion.btn.sending") : I18N.t("companion.btn.send");
  }

  async function send() {
    const text = input.value.trim();
    if (!text || sendBtn.disabled) return;

    hideStatus();
    appendMessage("user", text);
    input.value = "";
    autoResize();
    setBusy(true);
    const typingEl = appendTyping();

    try {
      // Історія — на бекенді (app/companion_history.py): сервер сам підвантажує збережений
      // діалог і дописує туди нову пару питання+відповідь, клієнту носити її з собою не треба.
      const res = await fetch("/api/companion/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, model: modelSelect.value }),
      });
      const data = await res.json();
      typingEl.remove();
      if (!res.ok) {
        showStatus("error", data.error || I18N.t("companion.msg.error"));
        return;
      }
      appendMessage("assistant", data.reply);
    } catch (e) {
      typingEl.remove();
      showStatus("error", I18N.t("common.network_error", { message: e.message }));
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("input", autoResize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  clearBtn.addEventListener("click", async () => {
    if (!confirm(I18N.t("companion.msg.confirm_clear"))) return;
    hideStatus();
    clearBtn.disabled = true;
    try {
      const res = await fetch("/api/companion/history", { method: "DELETE" });
      if (!res.ok) {
        showStatus("error", I18N.t("companion.msg.error"));
        return;
      }
      messagesEl.innerHTML = "";
    } catch (e) {
      showStatus("error", I18N.t("common.network_error", { message: e.message }));
    } finally {
      clearBtn.disabled = false;
    }
  });

  examplesEl.querySelectorAll(".companion-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.textContent.trim();
      autoResize();
      input.focus();
    });
  });

  goSettingsBtn.addEventListener("click", () => {
    const settingsTabBtn = document.querySelector('.tab-btn[data-tab="settings"]');
    if (settingsTabBtn) settingsTabBtn.click();
  });

  async function loadHistory() {
    // Підвантажує збережений на бекенді діалог (app/companion_history.py) — викликається при
    // кожному відкритті вкладки, тому переключення проєкту чи перезавантаження сторінки завжди
    // показує актуальний чат активного проєкту, а не те, що лишилось у пам'яті браузера.
    try {
      const res = await fetch("/api/companion/history");
      const data = await res.json();
      messagesEl.innerHTML = "";
      (data.history || []).forEach((msg) => appendMessage(msg.role, msg.content));
    } catch (e) {
      // Мовчки лишаємо порожній чат — не критично, користувач просто побачить чистий діалог.
    }
  }

  async function checkKey() {
    try {
      const res = await fetch("/api/settings");
      const cfg = await res.json();
      const hasKey = !!cfg.anthropic_api_key;
      emptyState.style.display = hasKey ? "none" : "block";
      chatCard.style.display = hasKey ? "block" : "none";
      if (hasKey) await loadHistory();
    } catch (e) {
      emptyState.style.display = "block";
      chatCard.style.display = "none";
    }
  }

  const companionTabBtn = document.querySelector('.tab-btn[data-tab="companion"]');
  if (companionTabBtn) companionTabBtn.addEventListener("click", checkKey);

  restoreModel();
  checkKey();
})();
