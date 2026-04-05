// ── State ─────────────────────────────────────────────────────────────────
let appState = {
  statusKey: "idle",
  status: "Ready",
  hotkey: "ALT + K",
  microphoneLabel: "System default",
  microphoneOptions: [],
  microphone: "",
  outputModeLabel: "Type and copy",
  outputOptions: [],
  outputMode: "both",
  showOverlay: true,
  soundFeedback: true,
  lastTranscript: "",
  lastCleaned: "",
  lastDelivery: "",
  lastDuration: "",
  model: "small.en",
  history: []
};

// ── Element refs ──────────────────────────────────────────────────────────
const statusCard    = document.getElementById("status-card");
const statusPill    = document.getElementById("status-pill");
const hotkeyPill    = document.getElementById("hotkey-pill");
const statusLabel   = document.getElementById("status-label");
const statusSub     = document.getElementById("status-sub");
const stateBadge    = document.getElementById("state-badge");
const lastCleaned   = document.getElementById("last-cleaned");
const lastDelivery  = document.getElementById("last-delivery");
const lastDuration  = document.getElementById("last-duration");
const micValue      = document.getElementById("mic-value");
const outputValue   = document.getElementById("output-value");
const overlaySwitch = document.getElementById("overlay-switch");
const soundSwitch   = document.getElementById("sound-switch");
const modelValue    = document.getElementById("model-value");
const historyList   = document.getElementById("history-list");
const sheet         = document.getElementById("option-sheet");
const sheetBackdrop = document.getElementById("sheet-backdrop");
const sheetTitle    = document.getElementById("sheet-title");
const optionList    = document.getElementById("option-list");

// ── State rendering ───────────────────────────────────────────────────────
const STATE_MAP = {
  idle:       { label: "Ready",      sub: "Hold Alt + K to speak",    badge: "Idle" },
  listening:  { label: "Listening",  sub: "Speak naturally\u2026",          badge: "Recording" },
  processing: { label: "Processing", sub: "Transcribing your speech\u2026", badge: "Processing" },
  delivered:  { label: "Delivered",  sub: "Text written to your app",  badge: "Done" },
  error:      { label: "Error",      sub: "Something went wrong",      badge: "Error" },
};

function applyState(state) {
  appState = { ...appState, ...state };

  // Derive status key from status string if not provided
  const key = appState.statusKey || inferKey(appState.status || "");
  const s   = STATE_MAP[key] || STATE_MAP.idle;

  statusCard.dataset.state = key;
  statusPill.textContent   = appState.status || s.label;
  statusLabel.textContent  = s.label;
  statusSub.textContent    = s.sub;
  stateBadge.textContent   = s.badge;

  hotkeyPill.innerHTML = (appState.hotkey || "ALT + K")
    .replace(/\s\+\s/g, "\u00a0+\u00a0");

  micValue.textContent    = appState.microphoneLabel || "System default";
  outputValue.textContent = appState.outputModeLabel || "Type and copy";
  modelValue.textContent  = appState.model || "small.en";

  overlaySwitch.classList.toggle("on", Boolean(appState.showOverlay));
  soundSwitch.classList.toggle("on", Boolean(appState.soundFeedback));

  lastCleaned.textContent  = appState.lastCleaned  || "Nothing yet \u2014 hold Alt + K and speak.";
  lastDelivery.textContent = appState.lastDelivery || "";
  lastDuration.textContent = appState.lastDuration || "";

  renderHistory(appState.history || []);
}

function inferKey(status) {
  const s = status.toLowerCase();
  if (s.includes("listen") || s.includes("recording")) return "listening";
  if (s.includes("process"))                           return "processing";
  if (s.includes("error") || s.includes("fail"))      return "error";
  if (s.includes("written") || s.includes("typed") || s.includes("copied") || s.includes("delivered")) return "delivered";
  return "idle";
}

// ── History ────────────────────────────────────────────────────────────────
function renderHistory(entries) {
  if (!entries || entries.length === 0) {
    historyList.innerHTML = '<p class="history-empty">Your recent dictations will appear here.</p>';
    return;
  }
  historyList.innerHTML = "";
  entries.slice().reverse().forEach(entry => {
    const el = document.createElement("div");
    el.className = "history-entry";
    el.innerHTML = `
      <span class="history-entry-text" title="${escHtml(entry.text)}">${escHtml(entry.text)}</span>
      <span class="history-entry-time">${entry.time || ""}</span>
      <button class="history-copy-btn" data-text="${escHtml(entry.text)}">Copy</button>
    `;
    el.querySelector(".history-copy-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      const text = e.target.dataset.text;
      if (hasApi()) await window.pywebview.api.copy_text(text);
      else navigator.clipboard?.writeText(text);
    });
    historyList.appendChild(el);
  });
}

function escHtml(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── Option sheet ───────────────────────────────────────────────────────────
let sheetOpen = false;

function openSheet(title, options, current, onSelect) {
  sheetTitle.textContent = title;
  optionList.innerHTML = "";
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.className = "option-item" + (opt.value === current ? " selected" : "");
    btn.textContent = opt.label;
    btn.addEventListener("click", async () => {
      closeSheet();
      await onSelect(opt.value);
    });
    optionList.appendChild(btn);
  });
  sheetOpen = true;
  sheet.classList.remove("is-hidden");
  sheet.setAttribute("aria-hidden", "false");
}

function closeSheet() {
  sheetOpen = false;
  sheet.classList.add("is-hidden");
  sheet.setAttribute("aria-hidden", "true");
}

// ── API bridge ─────────────────────────────────────────────────────────────
function hasApi() { return Boolean(window.pywebview?.api); }

async function refresh() {
  if (!hasApi()) return;
  try {
    const s = await window.pywebview.api.get_state();
    if (s) applyState(s);
  } catch(e) { console.error(e); }
}

window.__koeApplyState = s => { if (s) applyState(s); };

// ── Event wiring ───────────────────────────────────────────────────────────
document.getElementById("hide-btn").addEventListener("click", async () => {
  if (hasApi()) await window.pywebview.api.hide_window();
});

document.getElementById("mic-setting").addEventListener("click", () => {
  openSheet("Microphone", appState.microphoneOptions || [], appState.microphone, async val => {
    if (!hasApi()) return;
    applyState(await window.pywebview.api.set_input_device(val));
  });
});

document.getElementById("output-setting").addEventListener("click", () => {
  openSheet("Output mode", appState.outputOptions || [], appState.outputMode, async val => {
    if (!hasApi()) return;
    applyState(await window.pywebview.api.set_output_mode(val));
  });
});

document.getElementById("overlay-toggle").addEventListener("click", async () => {
  if (!hasApi()) return;
  applyState(await window.pywebview.api.set_overlay_enabled(!appState.showOverlay));
});

document.getElementById("sound-toggle").addEventListener("click", async () => {
  if (!hasApi()) return;
  applyState(await window.pywebview.api.set_sound_enabled(!appState.soundFeedback));
});

document.getElementById("copy-result-btn").addEventListener("click", async () => {
  if (!hasApi()) return;
  applyState(await window.pywebview.api.copy_last_result());
});

document.getElementById("clear-result-btn").addEventListener("click", async () => {
  if (!hasApi()) return;
  applyState(await window.pywebview.api.clear_last_result());
});

document.getElementById("clear-history-btn").addEventListener("click", async () => {
  if (!hasApi()) return;
  applyState(await window.pywebview.api.clear_history());
});

sheetBackdrop.addEventListener("click", closeSheet);
window.addEventListener("keydown", e => { if (e.key === "Escape" && sheetOpen) closeSheet(); });

// ── Init ──────────────────────────────────────────────────────────────────
applyState({});

if (hasApi()) {
  refresh();
  setInterval(refresh, 1000);
}
