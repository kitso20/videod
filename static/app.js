const $ = (id) => document.getElementById(id);
const urlInput = $("url");
const fetchBtn = $("fetch");
const downloadBtn = $("download");
const qualitySel = $("quality");
const preview = $("preview");
const options = $("options");
const probeError = $("probe-error");
const queueEl = $("queue");
const emptyEl = $("empty");

let current = null;
let mode = "video";

function setMode(next) {
  mode = next;
  document.querySelectorAll("#mode-seg button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode)
  );
  renderQualities();
}

function renderQualities() {
  if (!current) return;
  const list = mode === "audio" ? current.audio_qualities.map((q) => ({ id: q, label: `${q} kbps` })) : current.qualities;
  qualitySel.innerHTML = list.map((q) => `<option value="${q.id}">${q.label}</option>`).join("");
  if (mode === "audio") qualitySel.value = "192";
}

document.querySelectorAll("#mode-seg button").forEach((b) =>
  b.addEventListener("click", () => setMode(b.dataset.mode))
);

async function fetchInfo() {
  const url = urlInput.value.trim();
  if (!url) return;
  probeError.classList.add("hidden");
  fetchBtn.disabled = true;
  fetchBtn.textContent = "Fetching…";
  try {
    const res = await fetch("/api/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to fetch");
    current = data;
    $("thumb").src = data.thumbnail || "";
    $("title").textContent = data.title;
    $("sub").textContent = [data.uploader, data.extractor, data.is_live ? "LIVE" : ""]
      .filter(Boolean)
      .join(" · ");
    preview.classList.remove("hidden");
    options.classList.remove("hidden");
    renderQualities();
  } catch (err) {
    probeError.textContent = err.message;
    probeError.classList.remove("hidden");
    preview.classList.add("hidden");
    options.classList.add("hidden");
  } finally {
    fetchBtn.disabled = false;
    fetchBtn.textContent = "Fetch";
  }
}

async function startDownload() {
  if (!current) return;
  downloadBtn.disabled = true;
  const payload = { url: urlInput.value.trim(), mode, quality: qualitySel.value };
  try {
    await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } finally {
    downloadBtn.disabled = false;
  }
}

function fmtSize(bytes) {
  if (!bytes) return "";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (bytes >= 1024 && i < u.length - 1) { bytes /= 1024; i++; }
  return `${bytes.toFixed(1)} ${u[i]}`;
}

const BADGE = {
  queued: "Queued",
  downloading: "Downloading",
  processing: "Processing",
  done: "Done",
  error: "Failed",
  canceled: "Canceled",
};

function render(tasks) {
  const active = tasks.filter((t) => !["done", "error", "canceled"].includes(t.status));
  emptyEl.classList.toggle("hidden", tasks.length > 0);
  queueEl.innerHTML = tasks
    .map((t) => {
      const pct = Math.max(0, Math.min(100, t.progress || 0));
      const showBar = ["queued", "downloading", "processing"].includes(t.status);
      const sub =
        t.status === "error"
          ? `<span class="error">${escapeHtml(t.error)}</span>`
          : t.status === "done"
          ? `${fmtSize(t.filesize)}`
          : `${pct.toFixed(0)}% ${t.speed ? "· " + t.speed : ""} ${t.eta ? "· ETA " + t.eta : ""}`;
      const actions = [];
      if (t.status === "done") {
        actions.push(`<a href="/api/files/${encodeURIComponent(t.filename)}" download>Download</a>`);
        actions.push(`<button data-remove="${t.id}">Remove</button>`);
      } else if (["queued", "downloading", "processing"].includes(t.status)) {
        actions.push(`<button data-cancel="${t.id}">Cancel</button>`);
      } else {
        actions.push(`<button data-remove="${t.id}">Remove</button>`);
      }
      return `<li class="item">
        <div class="top">
          <span class="name">${escapeHtml(t.title)}</span>
          <span class="badge ${t.status}">${BADGE[t.status] || t.status}</span>
        </div>
        ${showBar ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}
        <div class="sub"><span>${t.mode === "audio" ? "MP3" : "MP4"} · ${t.quality}</span><span>${sub}</span></div>
        <div class="actions">${actions.join("")}</div>
      </li>`;
    })
    .join("");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

queueEl.addEventListener("click", async (e) => {
  const cancelId = e.target.dataset?.cancel;
  const removeId = e.target.dataset?.remove;
  if (cancelId) await fetch(`/api/tasks/${cancelId}/cancel`, { method: "POST" });
  if (removeId) await fetch(`/api/tasks/${removeId}`, { method: "DELETE" });
});

$("clear").addEventListener("click", async () => {
  const res = await fetch("/api/tasks");
  const tasks = await res.json();
  await Promise.all(
    tasks
      .filter((t) => ["done", "error", "canceled"].includes(t.status))
      .map((t) => fetch(`/api/tasks/${t.id}`, { method: "DELETE" }))
  );
});

fetchBtn.addEventListener("click", fetchInfo);
downloadBtn.addEventListener("click", startDownload);
urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") fetchInfo(); });

const es = new EventSource("/api/events");
es.onmessage = (e) => render(JSON.parse(e.data));
