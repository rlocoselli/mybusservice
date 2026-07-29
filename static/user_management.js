const tokenStorageKey = "meubusao.admin.token";
const loginPath = "/admin/login";

function getStoredToken() {
  return window.localStorage.getItem(tokenStorageKey) || "";
}

function clearStoredToken() {
  window.localStorage.removeItem(tokenStorageKey);
}

function redirectToLogin() {
  const next = encodeURIComponent(window.location.pathname);
  window.location.href = `${loginPath}?next=${next}`;
}

function setMessage(message, type = "") {
  const node = document.getElementById("userManagementMessage");
  node.textContent = message || "";
  node.className = "status-line";
  if (type) {
    node.classList.add(`is-${type}`);
  }
}

async function fetchJson(url, token, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      token,
      ...(options.headers || {})
    }
  });

  const data = await response.json().catch(() => ({}));

  if (response.status === 403) {
    clearStoredToken();
    redirectToLogin();
    throw new Error("Session expiree. Veuillez vous reconnecter.");
  }

  if (!response.ok) {
    throw new Error(data.message || `Request failed with status ${response.status}`);
  }

  return data;
}

function formatDate(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("fr-FR");
}

function renderUsers(users) {
  const body = document.getElementById("usersTableBody");
  body.innerHTML = users.map((user) => `
    <tr>
      <td>${user.username}</td>
      <td>${user.displayName || "-"}</td>
      <td>${user.isActive ? "Oui" : "Non"}</td>
      <td>${user.hasPassword ? "Oui" : "Non"}</td>
      <td>${formatDate(user.passwordUpdatedAt)}</td>
      <td>${formatDate(user.createdAt)}</td>
    </tr>
  `).join("");
}

async function loadUsers() {
  const token = getStoredToken();
  if (!token) {
    redirectToLogin();
    return;
  }

  try {
    const users = await fetchJson("/admin/users", token);
    renderUsers(users);
    setMessage("Utilisateurs charges.", "success");
  } catch (error) {
    setMessage(error.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("logoutButton").addEventListener("click", () => {
    clearStoredToken();
    redirectToLogin();
  });

  if (!getStoredToken()) {
    redirectToLogin();
    return;
  }

  document.getElementById("passwordForm").addEventListener("submit", async (event) => {
    event.preventDefault();

    const token = getStoredToken();
    if (!token) {
      redirectToLogin();
      return;
    }

    const formData = new FormData(event.currentTarget);
    const payload = {
      username: String(formData.get("username") || "").trim(),
      password: String(formData.get("password") || "")
    };

    try {
      const result = await fetchJson("/admin/users/password", token, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      event.currentTarget.reset();
      event.currentTarget.elements.username.value = payload.username;
      setMessage(`${result.username}: mot de passe hashe et enregistre.`, "success");
      loadUsers();
    } catch (error) {
      setMessage(error.message, "error");
    }
  });

  loadUsers();
});
