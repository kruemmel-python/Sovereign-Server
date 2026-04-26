const statusEl = document.querySelector("#status");
const resultEl = document.querySelector("#result");
const form = document.querySelector("#contact-form");

function renderStatus(data) {
  const rows = [
    ["Service", data.service],
    ["Version", data.version],
    ["Sandbox", data.sandbox],
    ["Python", data.python],
    ["Platform", data.platform],
    ["Uptime", `${data.uptime_seconds}s`],
    ["HTML5", data.html5?.enabled ? "aktiv" : "inaktiv"],
    ["Request ID", data.request_id],
  ];
  statusEl.innerHTML = rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
}

async function loadStatus() {
  const response = await fetch("/api/status", { headers: { "Accept": "application/json" } });
  renderStatus(await response.json());
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(form).entries());
  const response = await fetch("/api/contact", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(body),
  });
  resultEl.textContent = JSON.stringify(await response.json(), null, 2);
});

document.querySelector("#refresh-status").addEventListener("click", loadStatus);
loadStatus().catch((error) => {
  statusEl.innerHTML = `<div><dt>Status</dt><dd>${error.message}</dd></div>`;
});
