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
  const expandPill = document.getElementById("expand-hotkey-pill");
  if (expandPill) {
    expandPill.textContent = (appState.expandHotkey || "ALT + SHIFT + K").replace(/\s\+\s/g, "\u00a0+\u00a0");
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
const snippetModal         = document.getElementById("snippet-modal");
const snippetTrigger       = document.getElementById("snippet-trigger-input");
const snippetExpansion     = document.getElementById("snippet-expansion-input");
const snippetModalTitle    = document.getElementById("snippet-modal-title");
const snippetOriginalTrig  = document.getElementById("snippet-original-trigger");

// mode: "add" | "edit" | "save-from-result"
function openSnippetModal(trigger = "", expansion = "", originalTrigger = null) {
  const isEdit = originalTrigger !== null && originalTrigger !== "";
  snippetModalTitle.textContent = isEdit ? "Edit snippet" : (expansion ? "Save as snippet" : "Add snippet");
  snippetTrigger.value          = trigger;
  snippetExpansion.value        = expansion;
  snippetOriginalTrig.value     = originalTrigger || "";
  snippetModal.classList.remove("is-hidden");
  snippetModal.setAttribute("aria-hidden", "false");
  setTimeout(() => (trigger ? snippetExpansion.focus() : snippetTrigger.focus()), 60);
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
  const original  = snippetOriginalTrig.value.trim();
  if (!trigger || !expansion) { snippetTrigger.focus(); return; }
  closeSnippetModal();
  if (!hasApi()) return;

  let data;
  if (original && original.toLowerCase() !== trigger.toLowerCase()) {
    // trigger renamed → call edit_snippet
    data = await window.pywebview.api.edit_snippet(original, trigger, expansion);
  } else if (original) {
    // same trigger, just update expansion
    data = await window.pywebview.api.edit_snippet(original, trigger, expansion);
  } else {
    data = await window.pywebview.api.add_snippet(trigger, expansion);
  }
  renderSnippetsPage(data);
  applyState({ snippetCount: (data.snippets || []).length });
});

// ── Snippets page ──────────────────────────────────────────────────────────
let suggestionsDismissed = false;

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
  countLabel.textContent = snippets.length
    ? `${snippets.length} snippet${snippets.length !== 1 ? "s" : ""}` : "";

  // Suggestions panel (respects dismiss flag)
  const sugPanel = document.getElementById("suggestions-panel");
  const sugList  = document.getElementById("suggestions-list");
  if (suggestions.length > 0 && !suggestionsDismissed) {
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
      <div class="snippet-row-actions">
        <button class="snippet-action-btn" data-action="edit"
                data-trigger="${esc(s.trigger)}" data-expansion="${esc(s.expansion)}" title="Edit">
          <svg viewBox="0 0 12 12" fill="none">
            <path d="M8.5 1.5l2 2L3 11H1V9l7.5-7.5z" stroke="currentColor" stroke-width="1.3"
                  stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
        <button class="snippet-action-btn snippet-action-btn--delete"
                data-action="delete" data-trigger="${esc(s.trigger)}" title="Delete">
          <svg viewBox="0 0 12 12" fill="none">
            <path d="M2 2l8 8M10 2L2 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    `;
    row.querySelector('[data-action="edit"]').addEventListener("click", e => {
      const { trigger, expansion } = e.currentTarget.dataset;
      openSnippetModal(trigger, expansion, trigger);  // originalTrigger = trigger
    });
    row.querySelector('[data-action="delete"]').addEventListener("click", async e => {
      if (!hasApi()) return;
      const data = await window.pywebview.api.delete_snippet(e.currentTarget.dataset.trigger);
      renderSnippetsPage(data);
    });
    list.appendChild(row);
  });
}

document.getElementById("add-snippet-btn").addEventListener("click", () => openSnippetModal());

document.getElementById("dismiss-suggestions-btn").addEventListener("click", () => {
  suggestionsDismissed = true;
  document.getElementById("suggestions-panel").style.display = "none";
});

// "Save as snippet" from last result panel
document.getElementById("save-result-snippet-btn").addEventListener("click", () => {
  const text = appState.lastCleaned;
  if (!text) return;
  openSnippetModal("", text);
});

// ── File Transcription page ────────────────────────────────────────────────
let txFilePath  = "";
let txFilename  = "";
let txResults   = [];    // {filename, text, wordCount, duration}
let txIsAdding  = false; // true when adding a 2nd+ file while done panel is visible

const TX_STEPS = ["pick", "ready", "progress", "done", "error"];
function txShow(step) {
  TX_STEPS.forEach(s => {
    const el = document.getElementById("tx-step-" + s);
    if (el) el.classList.toggle("is-hidden", s !== step);
  });
}

// Inline progress block shown inside the done panel when adding a file
function _showInlineProgress(filename) {
  const list = document.getElementById("tx-transcript-list");
  // Remove any previous inline block
  const old = list.querySelector(".tx-inline-progress");
  if (old) old.remove();
  // Separator above
  if (txResults.length > 0) {
    const sep = document.createElement("div");
    sep.className = "tx-result-sep tx-inline-sep";
    list.appendChild(sep);
  }
  const el = document.createElement("div");
  el.className = "tx-inline-progress";
  el.innerHTML = `
    <div class="tx-inline-head">
      <div class="spinner spinner--sm"></div>
      <span class="tx-inline-filename">${esc(filename)}</span>
      <span class="tx-inline-pct" id="inline-pct">0%</span>
    </div>
    <div class="tx-progress-bar-wrap" style="margin-top:8px">
      <div class="tx-progress-bar" id="inline-bar" style="width:0%"></div>
    </div>
    <p class="tx-live-text" id="inline-live" style="margin-top:8px">Warming up\u2026</p>
  `;
  list.appendChild(el);
}

function _removeInlineProgress() {
  const list = document.getElementById("tx-transcript-list");
  const sep  = list.querySelector(".tx-inline-sep");
  if (sep)  sep.remove();
  const el   = list.querySelector(".tx-inline-progress");
  if (el)   el.remove();
}

async function pickFile(addMode = false) {
  if (!hasApi()) return;
  const result = await window.pywebview.api.open_file_dialog();
  if (result && result.path) {
    txFilePath = result.path;
    txFilename = result.filename;
    txIsAdding = addMode && txResults.length > 0;

    if (txIsAdding) {
      // Stay on done panel — show inline spinner immediately and start
      _showInlineProgress(txFilename);
      await window.pywebview.api.start_file_transcription(txFilePath);
    } else {
      document.getElementById("ready-filename").textContent = txFilename;
      txShow("ready");
    }
  } else if (addMode && txResults.length > 0) {
    // User cancelled picker — stay on done
    txShow("done");
  }
}

async function runTranscription() {
  if (!txFilePath || !hasApi()) return;
  document.getElementById("progress-filename").textContent = txFilename;
  document.getElementById("progress-bar").style.width = "0%";
  document.getElementById("progress-pct").textContent = "0%";
  document.getElementById("live-transcript").textContent = "Warming up\u2026";
  txShow("progress");
  await window.pywebview.api.start_file_transcription(txFilePath);
}

window.__koeTranscribeProgress = function(data) {
  if (data.error) {
    if (txIsAdding) {
      _removeInlineProgress();
      // Show error inline rather than switching panels
      const list = document.getElementById("tx-transcript-list");
      const errEl = document.createElement("p");
      errEl.className = "tx-inline-error";
      errEl.textContent = "Error: " + (data.error || "Transcription failed");
      list.appendChild(errEl);
    } else {
      document.getElementById("tx-error-text").textContent = data.error;
      txShow("error");
    }
    txIsAdding = false;
    return;
  }

  if (txIsAdding) {
    // Route updates to the inline progress block
    if (!data.done) {
      const pct    = Math.round((data.progress || 0) * 100);
      const bar    = document.getElementById("inline-bar");
      const pctEl  = document.getElementById("inline-pct");
      const liveEl = document.getElementById("inline-live");
      if (bar)    bar.style.width   = pct + "%";
      if (pctEl)  pctEl.textContent = pct + "%";
      if (liveEl && data.partialText) liveEl.textContent = data.partialText;
      return;
    }
    // Done — remove inline block, push result, re-render
    _removeInlineProgress();
    txIsAdding = false;
  } else {
    if (!data.done) {
      const pct = Math.round((data.progress || 0) * 100);
      document.getElementById("progress-bar").style.width = pct + "%";
      document.getElementById("progress-pct").textContent = pct + "%";
      if (data.partialText) {
        document.getElementById("live-transcript").textContent = data.partialText;
      }
      return;
    }
  }

  // Transcription complete — push to results list
  const text = data.text || data.partialText || "";
  txResults.push({
    filename:  data.filename || txFilename,
    text,
    wordCount: data.wordCount || text.split(/\s+/).filter(Boolean).length,
    duration:  data.duration  || null,
  });
  renderTxDone();
  txShow("done");
};

function renderTxDone() {
  const list = document.getElementById("tx-transcript-list");
  const countEl = document.getElementById("tx-file-count");
  countEl.textContent = txResults.length > 1 ? `(${txResults.length} files)` : "";
  list.innerHTML = "";
  txResults.forEach((r, idx) => {
    const block = document.createElement("div");
    block.className = "tx-result-block";
    block.innerHTML = `
      <div class="tx-result-header">
        <span class="tx-result-filename">${esc(r.filename)}</span>
        <div class="tx-result-meta">
          ${r.wordCount ? `<span class="chip">${r.wordCount} words</span>` : ""}
          ${r.duration  ? `<span class="chip">${r.duration}s</span>` : ""}
        </div>
        <button class="snippet-action-btn tx-result-remove" data-idx="${idx}" title="Remove">
          <svg viewBox="0 0 12 12" fill="none">
            <path d="M2 2l8 8M10 2L2 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
      <p class="tx-result-text">${esc(r.text)}</p>
    `;
    block.querySelector(".tx-result-remove").addEventListener("click", e => {
      const i = parseInt(e.currentTarget.dataset.idx, 10);
      txResults.splice(i, 1);
      if (txResults.length === 0) {
        txFilePath = "";
        txFilename = "";
        txShow("pick");
      } else {
        renderTxDone();
      }
    });
    list.appendChild(block);
    // Separator between files
    if (idx < txResults.length - 1) {
      const sep = document.createElement("div");
      sep.className = "tx-result-sep";
      list.appendChild(sep);
    }
  });
}

document.getElementById("browse-btn").addEventListener("click", () => pickFile(false));
document.getElementById("change-file-btn").addEventListener("click", () => pickFile(false));
document.getElementById("transcribe-btn").addEventListener("click", runTranscription);

document.getElementById("copy-all-btn").addEventListener("click", () => {
  const all = txResults.map(r => `[${r.filename}]\n${r.text}`).join("\n\n---\n\n");
  if (hasApi()) window.pywebview.api.copy_text(all);
  else navigator.clipboard?.writeText(all);
});

document.getElementById("add-file-btn").addEventListener("click", () => pickFile(true));

document.getElementById("clear-all-btn").addEventListener("click", () => {
  txResults   = [];
  txFilePath  = "";
  txFilename  = "";
  txShow("pick");
});

document.getElementById("retry-transcription-btn").addEventListener("click", () => {
  txFilePath = "";
  txFilename = "";
  txShow("pick");
});

// Drag-and-drop
const dropzone = document.getElementById("file-dropzone");
if (dropzone) {
  dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("drag-over"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
  dropzone.addEventListener("drop", async e => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
    await pickFile(false);
  });
}

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
