// logs.js

const logContainer = document.getElementById("run-log");
const progressBar = document.getElementById("batch-progress");
const runNowBtn   = document.getElementById("run-now-btn");

const MAX_LINES   = 1000;
const PRUNE_COUNT = 100;

// 1️⃣ Clear logs on Run Now
runNowBtn.addEventListener("click", () => {
  logContainer.innerHTML = "";
  progressBar.value   = 0;
  progressBar.max     = 0;
});

// 2️⃣ Tail log lines via SSE (existing endpoint)
const logSource = new EventSource("/api/v1/logs/stream/logs");
logSource.onmessage = ev => {
  const line = ev.data;
  const div = document.createElement("div");
  div.textContent = line;
  logContainer.appendChild(div);

  if (logContainer.children.length > MAX_LINES) {
    for (let i = 0; i < PRUNE_COUNT; i++) {
      logContainer.removeChild(logContainer.firstChild);
    }
  }
};

// 3️⃣ Listen for structured progress events
const statusSource = new EventSource("/api/v1/logs/status");
statusSource.addEventListener("progress", ev => {
  const d = JSON.parse(ev.data);
  progressBar.max   = d.total;
  progressBar.value = d.current;
});