let credentials = null;

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
  if (!response.ok) throw new Error(data.message || "Não foi possível concluir a solicitação.");
  return data;
}

async function refreshKeys() {
  const data = await post("/developer/keys", { ...credentials, action: "list" });
  const list = document.getElementById("keyList");
  list.replaceChildren();
  if (!data.keys.length) {
    list.textContent = "Nenhuma chave criada.";
    return;
  }
  data.keys.forEach((key) => {
    const row = document.createElement("div");
    row.className = "developer-key-row";
    const label = document.createElement("span");
    label.textContent = `${key.name} · ${key.prefix}… · ${key.active ? "Ativa" : "Revogada"}`;
    row.appendChild(label);
    if (key.active) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Revogar";
      button.addEventListener("click", async () => {
        try {
          await post("/developer/keys", { ...credentials, action: "revoke", keyId: key.id });
          await refreshKeys();
          message("Chave revogada.");
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
      message("Conta criada. Entre para gerar sua chave.");
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
      message("Você entrou. Agora pode gerar sua chave.");
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
      message("Chave criada. Copie-a agora: ela não será exibida novamente.");
    } catch (error) { message(error.message, true); }
  });

  document.getElementById("copyKeyButton").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(document.getElementById("newKey").textContent); message("Chave copiada."); }
    catch { message("Selecione e copie a chave manualmente.", true); }
  });

  document.getElementById("signOutButton").addEventListener("click", () => {
    credentials = null;
    document.getElementById("newKey").textContent = "";
    document.getElementById("newKeyPanel").hidden = true;
    document.getElementById("keyPanel").hidden = true;
    message("Sessão encerrada nesta página.");
  });
});
