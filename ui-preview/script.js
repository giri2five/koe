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
  history: [],
  snippetCount: 0,
};

// ── Page routing ───────────────────────────────────────────────────────────
let activePage = "dashboard";

function showPage(pageId) {
  activePage = pageId;
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-link").forEach(n => n.classList.remove("active"));
  const page = document.getElementById("page-" + pageId);
  if (page) page.classList.add("active");
  const nav = document.querySelector(`.nav-link[data-page="${pageId}"]`);
  if (nav) nav.classList.add("active");

  if (pageId === "snippets") loadSnippetsPage();
}

document.querySelectorAll(".nav-link").forEach(btn => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});

// ── Element refs ───────────────────────────────────────────────────────────
const statusCard    = document.getElementById("status-card");
const statusLabel   = document.getElementById("status-label");
const statusSub     = document.getElementById("status-sub");
const stateBadge    = document.getElementById("state-badge");
const hotkeyPill    = document.getElementById("hotkey-pill");
const micValue      = document.getElementById("mic-value");
const outputValue   = document.getElementById("output-value");
const overlaySwitch = document.getElementById("overlay-switch");
const soundSwitch   = document.getElementById("sound-switch");
const modelValue    = document.getElementById("model-value");
const lastCleaned   = document.getElementById("last-cleaned");
const lastDelivery  = document.getElementById("last-delivery");
const lastDuration  = document.getElementById("last-duration");
const historyList   = document.getElementById("history-list");
const sheet         = document.getElementById("option-sheet");
const sheetBackdrop = document.getElementById("sheet-backdrop");
const sheetTitle    = document.getElementById("sheet-title");
const optionList    = document.getElementById("option-list");
const snippetNavBadge = document.getElementById("snippet-nav-badge");

// ── Status map ─────────────────────────────────────────────────────────────
const STATUS_MAP = {
  idle:       { label: "Ready",          sub: "Hold Alt\u00a0+\u00a0K to speak",  badge: "Idle" },
  listening:  { label: "Listening\u2026", sub: "Speak naturally",                  badge: "Recording" },
  processing: { label: "Processing\u2026", sub: "Transcribing your speech",        badge: "Processing" },
  delivered:  { label: "Delivered",      sub: "Text written to your app",          badge: "Done" },
  error:      { label: "Error",          sub: "Something went wrong",              badge: "Error" },
};

// ── Apply state ────────────────────────────────────────────────────────────
function applyState(incoming) {
  const prev = { ...appState };
  appState = { ...appState, ...incoming };

  const key = appState.statusKey || inferKey(appState.status || "");
  const s   = STATUS_MAP[key] || STATUS_MAP.idle;

  statusCard.dataset.state = key;
  statusLabel.textContent  = s.label;
  statusSub.textContent    = s.sub;
  stateBadge.textContent   = s.badge;

  if (hotkeyPill) {
    hotkeyPill.textContent = (appState.hotkey || "ALT + K").replace(/\s\+\s/g, "\u00a0+\u00a0");
  }

  micValue.textContent    = appState.microphoneLabel || "System default";
  outputValue.textContent = appState.outputModeLabel || "Type and copy";
  modelValue.textContent  = appState.model || "small.en";

  // Snippet nav badge
  const sc = appState.snippetCount ?? 0;
  if (sc > 0) {
    snippetNavBadge.textContent = sc;
    snippetNavBadge.style.display = "";
  } else {
    snippetNavBadge.style.display = "none";
  }

  overlaySwitch.classList.toggle("on", Boolean(appState.showOverlay));
  soundSwitch.classList.toggle("on",   Boolean(appState.soundFeedback));

  const cleaned = appState.lastCleaned || "";
  lastCleaned.textContent = cleaned || "Hold Alt\u00a0+\u00a0K and speak \u2014 your text appears here.";
  lastCleaned.classList.toggle("has-content", cleaned.length > 0);

  lastDelivery.textContent = appState.lastDelivery || "";
  lastDuration.textContent = appState.lastDuration  || "";

  if (JSON.stringify(appState.history) !== JSON.stringify(prev.history)) {
    renderHistory(appState.history || []);
  }
}

function inferKey(status) {
  const s = status.toLowerCase();
  if (s.includes("listen") || s.includes("recording")) return "listening";
  if (s.includes("process"))                            return "processing";
  if (s.includes("error")  || s.includes("fail"))      return "error";
  if (s.includes("written") || s.includes("typed") ||
      s.includes("copied")  || s.includes("delivered") ||
      s.includes("snippet")) return "delivered";
  return "idle";
}

// ── History ────────────────────────────────────────────────────────────────
function renderHistory(entries) {
  if (!entries || entries.length === 0) {
    historyList.innerHTML = '<p class="empty-hint">Your recent dictations will appear here.</p>';
    return;
  }
  historyList.innerHTML = "";
  entries.slice().reverse().forEach(entry => {
    const el = document.createElement("div");
    el.className = "history-entry";
    el.innerHTML = `
      <span class="h-entry-text" title="${esc(entry.text)}">${esc(entry.text)}</span>
      <span class="h-entry-time">${entry.time || ""}</span>
      <button class="h-entry-btn" data-action="save" data-text="${esc(entry.text)}" title="Save as snippet">⌘</button>
      <button class="h-entry-btn" data-action="copy" data-text="${esc(entry.text)}">Copy</button>
    `;
    el.querySelector('[data-action="copy"]').addEventListener("click", async e => {
      e.stopPropagation();
      const text = e.currentTarget.dataset.text;
      if (hasApi()) await window.pywebview.api.copy_text(text);
      else navigator.clipboard?.writeText(text);
    });
    el.querySelector('[data-action="save"]').addEventListener("click", e => {
      e.stopPropagation();
      openSnippetModal("", e.currentTarget.dataset.text);
    });
    historyList.appendChild(el);
  });
}

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Option sheet (mic / output picker) ────────────────────────────────────
let sheetOpen = false;

function openSheet(title, options, current, onSelect) {
  sheetTitle.textContent = title;
  optionList.innerHTML   = "";
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

// ── Snippet modal ──────────────────────────────────────────────────────────
const snippetModal     = document.getElementById("snippet-modal");
const snippetTrigger   = document.getElementById("snippet-trigger-input");
const snippetExpansion = document.getElementById("snippet-expansion-input");
const snippetModalTitle = document.getElementById("snippet-modal-title");

function openSnippetModal(trigger = "", expansion = "") {
  snippetModalTitle.textContent = expansion ? "Save as snippet" : "Add snippet";
  snippetTrigger.value   = trigger;
  snippetExpansion.value = expansion;
  snippetModal.classList.remove("is-hidden");
  snippetModal.setAttribute("aria-hidden", "false");
  setTimeout(() => snippetTrigger.focus(), 60);
}

function closeSnippetModal() {
  snippetModal.classList.add("is-hidden");
  snippetModal.setAttribute("aria-hidden", "true");
}

document.getElementById("snippet-cancel-btn").addEventListener("click", closeSnippetModal);
document.getElementById("snippet-modal-backdrop").addEventListener("click", closeSnippetModal);

document.getElementById("snippet-save-btn").addEventListener("click", async () => {
  const trigger   = snippetTrigger.value.trim();
  const expansion = snippetExpansion.value.trim();
  if (!trigger || !expansion) {
    snippetTrigger.focus();
    return;
  }
  closeSnippetModal();
  if (hasApi()) {
    const data = await window.pywebview.api.add_snippet(trigger, expansion);
    renderSnippetsPage(data);
    // If not on snippets page, show a brief nav badge update
    applyState({ snippetCount: (data.snippets || []).length });
  }
});

// ── Snippets page ──────────────────────────────────────────────────────────
async function loadSnippetsPage() {
  if (!hasApi()) {
    renderSnippetsPage({ snippets: [], suggestions: [] });
    return;
  }
  const data = await window.pywebview.api.get_snippets_data();
  renderSnippetsPage(data);
}

function renderSnippetsPage(data) {
  const snippets    = data?.snippets    || [];
  const suggestions = data?.suggestions || [];

  // Badge + count label
  applyState({ snippetCount: snippets.length });
  const countLabel = document.getElementById("snippet-count-label");
  countLabel.textContent = snippets.length ? `${snippets.length} snippet${snippets.length !== 1 ? "s" : ""}` : "";

  // Suggestions panel
  const sugPanel = document.getElementById("suggestions-panel");
  const sugList  = document.getElementById("suggestions-list");
  if (suggestions.length > 0) {
    sugPanel.style.display = "";
    sugList.innerHTML = "";
    suggestions.forEach(s => {
      const card = document.createElement("div");
      card.className = "suggestion-card";
      card.innerHTML = `
        <div class="snippet-trigger">${esc(s.trigger)}</div>
        <div class="snippet-expansion">${esc(s.expansion)}</div>
        <div class="snippet-reason">${esc(s.reason || "")}</div>
        <button class="btn-ghost snippet-add-btn">+ Add</button>
      `;
      card.querySelector(".snippet-add-btn").addEventListener("click", () => {
        openSnippetModal(s.trigger, s.expansion);
      });
      sugList.appendChild(card);
    });
  } else {
    sugPanel.style.display = "none";
  }

  // Snippets list
  const list = document.getElementById("snippets-list");
  if (snippets.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <p class="empty-state-title">No snippets yet</p>
        <p class="empty-state-hint">Add one above, or after dictating say <em>"save snippet as [name]"</em></p>
      </div>`;
    return;
  }
  list.innerHTML = "";
  snippets.forEach(s => {
    const row = document.createElement("div");
    row.className = "snippet-row";
    row.innerHTML = `
      <div class="snippet-row-content">
        <span class="snippet-trigger-pill">${esc(s.trigger)}</span>
        <svg viewBox="0 0 16 16" fill="none" class="snippet-arrow">
          <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span class="snippet-expansion-text">${esc(s.expansion)}</span>
      </div>
      <button class="snippet-delete-btn" data-trigger="${esc(s.trigger)}" title="Delete">
        <svg viewBox="0 0 12 12" fill="none">
          <path d="M2 2l8 8M10 2L2 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
        </svg>
      </button>
    `;
    row.querySelector(".snippet-delete-btn").addEventListener("click", async e => {
      const trigger = e.currentTarget.dataset.trigger;
      if (!hasApi()) return;
      const data = await window.pywebview.api.delete_snippet(trigger);
      renderSnippetsPage(data);
    });
    list.appendChild(row);
  });
}

document.getElementById("add-snippet-btn").addEventListener("click", () => {
  openSnippetModal();
});

// "Save as snippet" from last result panel
document.getElementById("save-result-snippet-btn").addEventListener("click", () => {
  const text = appState.lastCleaned;
  if (!text) return;
  openSnippetModal("", text);
  // Switch to snippets page so user can see it was saved
});

// ── File Transcription page ────────────────────────────────────────────────
let selectedFilePath = "";

function setDropzoneState(state) {
  ["dropzone-idle", "dropzone-selected", "dropzone-loading"].forEach(id => {
    document.getElementById(id).classList.add("is-hidden");
  });
  document.getElementById("dropzone-" + state).classList.remove("is-hidden");
}

async function pickFile() {
  if (!hasApi()) return;
  const result = await window.pywebview.api.open_file_dialog();
  if (result && result.path) {
    selectedFilePath = result.path;
    document.getElementById("selected-filename").textContent = result.filename;
    setDropzoneState("selected");
    document.getElementById("transcribe-result").classList.add("is-hidden");
  }
}

async function runTranscription() {
  if (!selectedFilePath || !hasApi()) return;

  document.getElementById("transcribing-filename").textContent = document.getElementById("selected-filename").textContent;
  setDropzoneState("loading");
  document.getElementById("transcribe-result").classList.add("is-hidden");

  const result = await window.pywebview.api.transcribe_file(selectedFilePath);

  if (result.error) {
    setDropzoneState("selected");
    // Show error inline
    const out = document.getElementById("transcript-output");
    out.textContent = "Error: " + result.error;
    document.getElementById("transcribe-result").classList.remove("is-hidden");
    return;
  }

  setDropzoneState("selected");
  document.getElementById("transcript-output").textContent = result.text || "";
  document.getElementById("transcript-words").textContent  = result.wordCount ? `${result.wordCount} words` : "";
  document.getElementById("transcript-duration").textContent = result.duration ? `${result.duration}s` : "";
  document.getElementById("transcript-file").textContent   = result.filename || "";
  document.getElementById("transcribe-result").classList.remove("is-hidden");
}

document.getElementById("browse-btn").addEventListener("click", pickFile);
document.getElementById("change-file-btn").addEventListener("click", pickFile);
document.getElementById("transcribe-btn").addEventListener("click", runTranscription);
document.getElementById("copy-transcript-btn").addEventListener("click", () => {
  const text = document.getElementById("transcript-output").textContent;
  if (!text) return;
  if (hasApi()) window.pywebview.api.copy_text(text);
  else navigator.clipboard?.writeText(text);
});
document.getElementById("new-transcription-btn").addEventListener("click", () => {
  selectedFilePath = "";
  document.getElementById("transcribe-result").classList.add("is-hidden");
  setDropzoneState("idle");
});

// Drag & drop support
const dropzone = document.getElementById("file-dropzone");
dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("drag-over"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
dropzone.addEventListener("drop", async e => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  // In pywebview we can't get actual file paths from drop events easily,
  // so just trigger the file picker instead
  await pickFile();
});

// ── API bridge ─────────────────────────────────────────────────────────────
function hasApi() { return Boolean(window.pywebview?.api); }

async function refresh() {
  if (!hasApi()) return;
  try {
    const s = await window.pywebview.api.get_state();
    if (s) applyState(s);
  } catch (e) { /* ignore */ }
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
window.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (sheetOpen) closeSheet();
    if (!snippetModal.classList.contains("is-hidden")) closeSnippetModal();
  }
});

// ── Init ───────────────────────────────────────────────────────────────────
applyState({});

function startPolling() {
  refresh();
  setInterval(refresh, 1200);
}

if (hasApi()) {
  startPolling();
} else {
  window.addEventListener("pywebviewready", startPolling);
}
