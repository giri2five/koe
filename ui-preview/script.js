const states = {
  idle: {
    kicker: "Ready",
    title: "Press Alt + K to start dictation.",
    body: "Speak, release, and Koe writes into the active app while keeping the same text copied.",
    pill: "Idle",
    summaryTitle: "Simple capture flow.",
    resultTitle: "What Koe last heard.",
    summaryLines: [
      "Open any text field.",
      "Hold Alt + K, speak, release.",
      "Koe writes into the app and keeps the same text copied."
    ],
    note: "This window should stay simple: one hotkey, a few working controls, and no fake UI."
  },
  listening: {
    kicker: "Listening",
    title: "Speak naturally while Koe listens.",
    body: "The live overlay should stay centered at the top of the screen and react to your voice in real time.",
    pill: "Listening",
    summaryTitle: "Capture should feel alive.",
    resultTitle: "Live capture is active.",
    summaryLines: [
      "The waveform should react to your voice, not sit static.",
      "Whispered speech should still register clearly.",
      "The app window should stay out of the way while capture is active."
    ],
    note: "Listening should feel immediate: top-center capsule, reactive waveform, no visual clutter."
  },
  processing: {
    kicker: "Processing",
    title: "Turn speech into clean text quickly.",
    body: "Routes, notes, steps, and casual messages should land in the right shape instead of generic cleanup.",
    pill: "Processing",
    summaryTitle: "Processing should stay brief.",
    resultTitle: "Current result is being shaped.",
    summaryLines: [
      "Pause briefly while Koe resolves structure and punctuation.",
      "Keep casual language casual when the target looks like chat.",
      "Turn numbered speech into real steps when the content is procedural."
    ],
    note: "Processing should feel brief, smart, and invisible once the text lands."
  },
  delivered: {
    kicker: "Delivered",
    title: "Write into the app and keep it copied.",
    body: "The active app should receive the text immediately, with the clipboard preserved as a fallback.",
    pill: "Delivered",
    summaryTitle: "Delivery should be dependable.",
    resultTitle: "Latest successful result.",
    summaryLines: [
      "Typed or pasted into the focused text field.",
      "Copied to clipboard at the same time.",
      "No extra confirmation toast unless something failed."
    ],
    note: "Successful delivery should be quiet and obvious, not ceremonial."
  },
  error: {
    kicker: "Problem",
    title: "Failures should stay inside the app.",
    body: "When Koe fails, the window should explain what broke instead of opening blank or noisy windows.",
    pill: "Attention",
    summaryTitle: "Errors should stay contained.",
    resultTitle: "Latest failed result.",
    summaryLines: [
      "No stray console windows.",
      "No hidden launcher confusion.",
      "No dead buttons pretending to work."
    ],
    note: "Errors should be short, clear, and recoverable."
  }
};

const panel = document.querySelector("#hero-panel");
const kicker = document.querySelector("#hero-kicker");
const title = document.querySelector("#hero-title");
const body = document.querySelector("#hero-body");
const pill = document.querySelector("#hero-pill");
const summaryTitle = document.querySelector("#summary-title");
const resultTitle = document.querySelector("#result-title");
const draftSurface = document.querySelector("#draft-surface");
const statusPill = document.querySelector("#status-pill");
const enginePill = document.querySelector("#engine-pill");
const hotkeyPill = document.querySelector("#hotkey-pill");
const microphoneValue = document.querySelector("#microphone-value");
const outputValue = document.querySelector("#output-value");
const lastTranscript = document.querySelector("#last-transcript");
const lastCleaned = document.querySelector("#last-cleaned");
const lastDelivery = document.querySelector("#last-delivery");
const lastDuration = document.querySelector("#last-duration");
const copyResultButton = document.querySelector("#copy-result-button");
const clearResultButton = document.querySelector("#clear-result-button");
const overlaySwitch = document.querySelector("#overlay-switch");
const soundSwitch = document.querySelector("#sound-switch");
const inspectorNote = document.querySelector("#inspector-note");
const optionSheet = document.querySelector("#option-sheet");
const optionBackdrop = document.querySelector("#option-backdrop");
const optionList = document.querySelector("#option-list");
const sheetTitle = document.querySelector("#sheet-title");
const captureButton = document.querySelector("#capture-button");
const microphoneSetting = document.querySelector("#microphone-setting");
const outputSetting = document.querySelector("#output-setting");
const overlaySetting = document.querySelector("#overlay-setting");
const soundSetting = document.querySelector("#sound-setting");

let currentState = {
  statusKey: "idle",
  microphoneOptions: [],
  outputOptions: []
};
let sheetOpen = false;

function hasLiveApi() {
  return Boolean(window.pywebview && window.pywebview.api);
}

function renderVisualState(stateKey) {
  const state = states[stateKey] || states.idle;
  panel.dataset.state = stateKey;
  kicker.textContent = state.kicker;
  title.textContent = state.title;
  body.textContent = state.body;
  pill.textContent = state.pill;
  summaryTitle.textContent = state.summaryTitle;
  resultTitle.textContent = state.resultTitle;
  inspectorNote.textContent = state.note;

  draftSurface.innerHTML =
    '<div class="draft-index">01</div>' +
    state.summaryLines.map((line) => `<p class="draft-line">${line}</p>`).join("");
}

function applySwitch(element, enabled) {
  element.classList.toggle("is-on", Boolean(enabled));
}

function statusToStateKey(statusKey, statusText) {
  if (statusKey) return statusKey;
  const lowered = (statusText || "").toLowerCase();
  if (lowered.includes("listen")) return "listening";
  if (lowered.includes("process")) return "processing";
  if (lowered.includes("error") || lowered.includes("fail")) return "error";
  if (lowered.includes("written") || lowered.includes("typed") || lowered.includes("copied")) return "delivered";
  return "idle";
}

function applyRuntimeState(state) {
  currentState = state;
  const statusKey = statusToStateKey(state.statusKey, state.status);
  hotkeyPill.innerHTML = (state.hotkey || "ALT + K").replace(/\s\+\s/g, "&nbsp;+&nbsp;");
  statusPill.textContent = state.status || "Ready";
  enginePill.textContent = "On-device";
  microphoneValue.textContent = state.microphoneLabel || "System default";
  outputValue.textContent = state.outputModeLabel || "Write into app and keep copied";
  applySwitch(overlaySwitch, state.showOverlay);
  applySwitch(soundSwitch, state.soundFeedback);
  lastTranscript.textContent = state.lastTranscript || "Nothing captured yet.";
  lastCleaned.textContent = state.lastCleaned || "Nothing delivered yet.";
  lastDelivery.textContent = state.lastDelivery || "No delivery yet";
  lastDuration.textContent = state.lastDuration || "0.00s";
  renderVisualState(statusKey);
}

function openOptionSheet(titleText, options, currentValue, onSelect) {
  optionList.innerHTML = "";
  sheetTitle.textContent = titleText;
  options.forEach((option) => {
    const button = document.createElement("button");
    button.className = "option-item";
    button.type = "button";
    button.textContent = option.label;
    if (option.value === currentValue) {
      button.classList.add("is-selected");
    }
    button.addEventListener("click", async () => {
      closeOptionSheet();
      await onSelect(option.value);
    });
    optionList.appendChild(button);
  });
  sheetOpen = true;
  optionSheet.classList.remove("is-hidden");
  optionSheet.setAttribute("aria-hidden", "false");
}

function closeOptionSheet() {
  sheetOpen = false;
  optionSheet.classList.add("is-hidden");
  optionSheet.setAttribute("aria-hidden", "true");
}

async function refreshState() {
  if (!hasLiveApi()) return;
  try {
    const state = await window.pywebview.api.get_state();
    if (state) applyRuntimeState(state);
  } catch (error) {
    console.error(error);
  }
}

window.__koeApplyState = (state) => {
  if (state) applyRuntimeState(state);
};

captureButton.addEventListener("click", async () => {
  if (!hasLiveApi()) return;
  await window.pywebview.api.hide_window();
});

microphoneSetting.addEventListener("click", () => {
  openOptionSheet(
    "Microphone",
    currentState.microphoneOptions || [],
    currentState.microphone,
    async (value) => {
      if (!hasLiveApi()) return;
      const state = await window.pywebview.api.set_input_device(value);
      applyRuntimeState(state);
    }
  );
});

outputSetting.addEventListener("click", () => {
  openOptionSheet(
    "Output",
    currentState.outputOptions || [],
    currentState.outputMode,
    async (value) => {
      if (!hasLiveApi()) return;
      const state = await window.pywebview.api.set_output_mode(value);
      applyRuntimeState(state);
    }
  );
});

overlaySetting.addEventListener("click", async () => {
  if (!hasLiveApi()) return;
  const state = await window.pywebview.api.set_overlay_enabled(!currentState.showOverlay);
  applyRuntimeState(state);
});

soundSetting.addEventListener("click", async () => {
  if (!hasLiveApi()) return;
  const state = await window.pywebview.api.set_sound_enabled(!currentState.soundFeedback);
  applyRuntimeState(state);
});

copyResultButton.addEventListener("click", async () => {
  if (!hasLiveApi()) return;
  const state = await window.pywebview.api.copy_last_result();
  applyRuntimeState(state);
});

clearResultButton.addEventListener("click", async () => {
  if (!hasLiveApi()) return;
  const state = await window.pywebview.api.clear_last_result();
  applyRuntimeState(state);
});

optionBackdrop.addEventListener("click", closeOptionSheet);
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && sheetOpen) {
    closeOptionSheet();
  }
});

renderVisualState("idle");

if (hasLiveApi()) {
  refreshState();
  setInterval(refreshState, 900);
}
