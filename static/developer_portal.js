let credentials = null;
const copy = window.developerCopy || {};
const t = (key) => copy[key] || copy.request_failed || key;

function message(text, error = false) {
  const node = document.getElementById("developerMessage");
  node.textContent = text;
  node.className = `status-line${error ? " is-error" : " is-success"}`;
}

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(t(data.code || "request_failed"));
  return data;
}

async function refreshKeys() {
  const data = await post("/developer/keys", { ...credentials, action: "list" });
  const list = document.getElementById("keyList");
  list.replaceChildren();
  if (!data.keys.length) {
    list.textContent = t("no_keys");
    return;
  }
  data.keys.forEach((key) => {
    const row = document.createElement("div");
    row.className = "developer-key-row";
    const label = document.createElement("span");
    label.textContent = `${key.name} · ${key.prefix}… · ${key.active ? t("active") : t("revoked")}`;
    row.appendChild(label);
    if (key.active) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = t("revoke");
      button.addEventListener("click", async () => {
        try {
          await post("/developer/keys", { ...credentials, action: "revoke", keyId: key.id });
          await refreshKeys();
          message(t("key_revoked"));
        } catch (error) { message(error.message, true); }
      });
      row.appendChild(button);
    }
    list.appendChild(row);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const username = String(form.get("username") || "").trim();
      await post("/developer/register", { username, password: form.get("password") });
      document.querySelector('#loginForm [name="username"]').value = username;
      event.currentTarget.reset();
      message(t("account_created"));
    } catch (error) { message(error.message, true); }
  });

  document.getElementById("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    credentials = { username: String(form.get("username") || "").trim(), password: String(form.get("password") || "") };
    try {
      await refreshKeys();
      document.getElementById("keyPanel").hidden = false;
      event.currentTarget.reset();
      message(t("login_success"));
    } catch (error) { credentials = null; message(error.message, true); }
  });

  document.getElementById("createKeyForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const name = new FormData(event.currentTarget).get("name");
      const result = await post("/developer/keys", { ...credentials, action: "create", name });
      document.getElementById("newKey").textContent = result.key;
      document.getElementById("newKeyPanel").hidden = false;
      event.currentTarget.reset();
      await refreshKeys();
      message(t("key_created"));
    } catch (error) { message(error.message, true); }
  });

  document.getElementById("copyKeyButton").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(document.getElementById("newKey").textContent); message(t("copied")); }
    catch { message(t("copy_manually"), true); }
  });

  document.getElementById("signOutButton").addEventListener("click", () => {
    credentials = null;
    document.getElementById("newKey").textContent = "";
    document.getElementById("newKeyPanel").hidden = true;
    document.getElementById("keyPanel").hidden = true;
    message(t("signed_out"));
  });
});
