const tokenStorageKey = "meubusao.admin.token";

function setMessage(message, type = "") {
  const node = document.getElementById("adminLoginMessage");
  node.textContent = message || "";
  node.className = "status-line";
  if (type) {
    node.classList.add(`is-${type}`);
  }
}

function parseNextUrl() {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");

  if (!next || !next.startsWith("/admin/")) {
    return "/admin/usage-dashboard";
  }

  return next;
}

async function loginWithCredentials(username, password) {
  const response = await fetch("/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      username,
      password
    })
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok || !data.token) {
    throw new Error(data.message || "Utilisateur ou mot de passe invalide.");
  }

  return data.token;
}

document.addEventListener("DOMContentLoaded", () => {
  const existingToken = window.localStorage.getItem(tokenStorageKey);
  if (existingToken) {
    window.location.href = parseNextUrl();
    return;
  }

  document.getElementById("adminLoginForm").addEventListener("submit", async (event) => {
    event.preventDefault();

    const formData = new FormData(event.currentTarget);
    const username = String(formData.get("username") || "").trim();
    const password = String(formData.get("password") || "");

    if (!username) {
      setMessage("Utilisateur requis.", "error");
      return;
    }

    if (!password) {
      setMessage("Mot de passe requis.", "error");
      return;
    }

    try {
      setMessage("Connexion en cours...");
      const token = await loginWithCredentials(username, password);
      window.localStorage.setItem(tokenStorageKey, token);
      setMessage("Connexion reussie.", "success");
      window.location.href = parseNextUrl();
    } catch (error) {
      setMessage(error.message, "error");
    }
  });
});