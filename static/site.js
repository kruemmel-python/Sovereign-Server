const statusTarget = document.querySelector("#status");
const resultTarget = document.querySelector("#result");
const form = document.querySelector("#contact-form");

function renderStatus(data) {
  const rows = [
    ["Service", data.service],
    ["Version", data.version],
    ["Sandbox", data.sandbox],
    ["Python", data.python],
    ["Uptime", `${data.uptime_seconds}s`],
    ["Request-ID", data.request_id],
  ];

  statusTarget.innerHTML = rows
    .map(([key, value]) => `<div><dt>${key}</dt><dd>${String(value)}</dd></div>`)
    .join("");
}

async function loadStatus() {
  const response = await fetch("/api/status", {
    headers: { "Accept": "application/json" },
  });
  renderStatus(await response.json());
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(form).entries());

  const response = await fetch("/api/contact", {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  resultTarget.textContent = JSON.stringify(data, null, 2);
  loadStatus();
});

loadStatus().catch((error) => {
  statusTarget.innerHTML = `<div><dt>Status</dt><dd>${error.message}</dd></div>`;
});
