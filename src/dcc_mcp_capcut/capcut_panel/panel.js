/*
 * Minimal CapCut-side panel contract.  The host integration injects a
 * `window.CapCut` object; unsupported versions fail closed and are reported
 * to MCP instead of claiming success.
 */
const baseUrl = window.DCC_MCP_CAPCUT_BRIDGE_URL || "http://127.0.0.1:47410";
const token = window.DCC_MCP_CAPCUT_BRIDGE_TOKEN || "dev-token";
const status = document.getElementById("status");

async function reply(id, result, error) {
  await fetch(`${baseUrl}/result`, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-DCC-MCP-Token": token},
    body: JSON.stringify({id, result, error: error ? String(error) : null})
  });
}

async function dispatch(job) {
  const api = window.CapCut;
  if (!api || typeof api.dispatch !== "function") {
    throw new Error("CapCut host API is unavailable; install the matching panel build");
  }
  return api.dispatch(job.action, job.params || {});
}

async function poll() {
  try {
    const response = await fetch(`${baseUrl}/next`, {headers: {"X-DCC-MCP-Token": token}});
    const job = await response.json();
    if (job.id) {
      try { await reply(job.id, await dispatch(job), null); }
      catch (error) { await reply(job.id, null, error); }
    }
    status.textContent = "Connected — waiting for typed MCP actions";
  } catch (error) {
    status.textContent = `Bridge unavailable: ${error}`;
  } finally { setTimeout(poll, 100); }
}
poll();
