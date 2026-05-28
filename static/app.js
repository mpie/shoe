const monitorsEl = document.querySelector("#monitors");
const template = document.querySelector("#monitorTemplate");
const notifyButton = document.querySelector("#notifyButton");

const panels = new Map(); // id -> { root, fields..., initialized }
const openedMatchUrls = new Map(); // id -> productUrl already announced
let statusTimer = null;
let heartbeatTimer = null;

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js");
}

notifyButton.addEventListener("click", requestNotifications);

bootstrap();

async function bootstrap() {
  await refreshStatus();
  startPolling();
  startDesktopHeartbeat();
}

function ensurePanel(monitor) {
  let panel = panels.get(monitor.id);
  if (panel) {
    return panel;
  }

  const root = template.content.firstElementChild.cloneNode(true);
  root.dataset.id = monitor.id;
  monitorsEl.appendChild(root);

  panel = {
    root,
    title: root.querySelector(".monitor-title"),
    loginBadge: root.querySelector(".login-badge"),
    form: root.querySelector(".monitor-form"),
    searchText: root.querySelector(".f-searchText"),
    targetUrl: root.querySelector(".f-targetUrl"),
    intervalSeconds: root.querySelector(".f-intervalSeconds"),
    size: root.querySelector(".f-size"),
    startButton: root.querySelector(".startButton"),
    stopButton: root.querySelector(".stopButton"),
    clearButton: root.querySelector(".clearButton"),
    stateLabel: root.querySelector(".stateLabel"),
    checksLabel: root.querySelector(".checksLabel"),
    message: root.querySelector(".message"),
    logList: root.querySelector(".log-list"),
    initialized: false,
  };

  panel.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    openedMatchUrls.delete(monitor.id);
    await requestNotifications();
    await postJson(`/api/start/${monitor.id}`, {
      searchText: panel.searchText.value,
      targetUrl: panel.targetUrl.value,
      intervalSeconds: Number(panel.intervalSeconds.value || 20),
      size: panel.size.value || "",
    });
    await refreshStatus();
  });

  panel.stopButton.addEventListener("click", async () => {
    await postJson(`/api/stop/${monitor.id}`, {});
    await refreshStatus();
  });

  panel.clearButton.addEventListener("click", async () => {
    await postJson(`/api/logs/clear/${monitor.id}`, {});
    await refreshStatus();
  });

  panels.set(monitor.id, panel);
  return panel;
}

async function startDesktopHeartbeat() {
  try {
    const runtime = await fetch("/api/runtime").then((response) => response.json());
    if (!runtime.desktop) {
      return;
    }
    await sendHeartbeat();
    heartbeatTimer = window.setInterval(sendHeartbeat, 5000);
  } catch {
    return;
  }
}

async function sendHeartbeat() {
  try {
    await fetch("/api/heartbeat", { method: "POST" });
  } catch {
    if (heartbeatTimer !== null) {
      window.clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }
}

function startPolling() {
  stopPolling();
  statusTimer = window.setInterval(refreshStatus, 2000);
}

function stopPolling() {
  if (statusTimer !== null) {
    window.clearInterval(statusTimer);
    statusTimer = null;
  }
}

async function refreshStatus() {
  let data;
  try {
    data = await fetch("/api/status").then((response) => response.json());
  } catch {
    return;
  }

  for (const monitor of data.monitors ?? []) {
    const panel = ensurePanel(monitor);
    renderMonitor(panel, monitor);

    if (monitor.result && monitor.result.productUrl !== openedMatchUrls.get(monitor.id)) {
      openedMatchUrls.set(monitor.id, monitor.result.productUrl);
      announceMatch(monitor);
    }
  }
}

function renderMonitor(panel, monitor) {
  panel.title.textContent = monitor.label;

  if (!panel.initialized) {
    panel.searchText.value = monitor.searchText ?? "";
    panel.targetUrl.value = monitor.targetUrl ?? "";
    panel.intervalSeconds.value = monitor.intervalSeconds ?? 20;
    panel.size.value = monitor.size ?? "";
    panel.initialized = true;
  }

  panel.loginBadge.textContent = monitor.loginConfigured
    ? `Login: ${monitor.loginUser}`
    : "Geen login ingesteld";

  renderLog(panel.logList, monitor.logEntries ?? []);

  panel.stateLabel.textContent = monitor.running ? "Actief" : "Gestopt";
  panel.checksLabel.textContent = String(monitor.checks ?? 0);
  panel.startButton.disabled = Boolean(monitor.running);
  panel.stopButton.disabled = !monitor.running;

  if (monitor.result) {
    panel.message.textContent = "Gevonden. Checkout is geopend; rond af in de browser.";
  } else if (monitor.lastError) {
    panel.message.textContent = `Laatste fout: ${monitor.lastError}`;
  } else {
    panel.message.textContent = monitor.running
      ? `Zoekt naar "${monitor.searchText}"...`
      : "Klaar om te starten.";
  }
}

function renderLog(logList, entries) {
  if (entries.length === 0) {
    logList.innerHTML = "<li>Nog geen activiteit.</li>";
    return;
  }

  logList.innerHTML = entries
    .slice()
    .reverse()
    .map((entry) => renderLogEntry(entry))
    .join("");
}

function renderLogEntry(entry) {
  const [time, ...messageParts] = entry.split(" | ");
  const message = messageParts.join(" | ") || entry;
  const type = getLogType(message);

  return `
    <li class="log-item log-${type}">
      <span class="log-time">${escapeHtml(time)}</span>
      <span class="log-badge">${getLogLabel(type)}</span>
      <span class="log-message">${highlightLogMessage(message)}</span>
    </li>
  `;
}

function getLogType(message) {
  if (/fout|failed|could not|timed out/i.test(message)) return "error";
  if (/gevonden|match/i.test(message)) return "found";
  if (/checkout|shopping cart|cart|ingelogd|login/i.test(message)) return "cart";
  if (/automation|clicked|browser|aangeklikt|ingevuld/i.test(message)) return "auto";
  if (/check #|volgende check|nieuwe poging/i.test(message)) return "check";
  return "info";
}

function getLogLabel(type) {
  return {
    auto: "AUTO",
    cart: "CART",
    check: "CHECK",
    error: "FOUT",
    found: "MATCH",
    info: "INFO",
  }[type];
}

function highlightLogMessage(message) {
  return escapeHtml(message)
    .replace(/(&quot;[^&]+&quot;)/g, "<mark>$1</mark>")
    .replace(/(https?:\/\/\S+)/g, '<span class="log-url">$1</span>');
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function announceMatch(monitor) {
  playAlertSound();

  const title = `${monitor.label} match gevonden`;
  const body = `${monitor.result.matchedText} is gevonden. Checkout wordt geopend.`;

  if (Notification.permission === "granted") {
    const registration = await navigator.serviceWorker?.ready;
    if (registration) {
      registration.showNotification(title, {
        body,
        icon: "/icon.svg",
        badge: "/icon.svg",
        requireInteraction: true,
      });
    } else {
      new Notification(title, { body });
    }
  }
}

async function requestNotifications() {
  if (!("Notification" in window)) {
    return;
  }
  if (Notification.permission === "default") {
    await Notification.requestPermission();
  }
}

function playAlertSound() {
  const context = new AudioContext();
  const oscillator = context.createOscillator();
  const gain = context.createGain();

  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(880, context.currentTime);
  oscillator.frequency.setValueAtTime(660, context.currentTime + 0.18);
  gain.gain.setValueAtTime(0.0001, context.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.35, context.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.55);

  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start();
  oscillator.stop(context.currentTime + 0.58);
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}
