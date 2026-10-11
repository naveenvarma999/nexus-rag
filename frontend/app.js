"use strict";
const root = document.querySelector("#app");
const state = {
  user: null,
  view: "chat",
  history: [],
  docs: [],
  answer: null,
  config: {},
  auth: "login",
  email: "",
};
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const csrf = () =>
  decodeURIComponent(
    document.cookie
      .split("; ")
      .find((v) => v.startsWith("csrf_token="))
      ?.slice(11) || "",
  );
let renewing = null,
  poll = null;
function toast(message) {
  const t = document.querySelector("#toast");
  t.textContent = message;
  t.style.display = "block";
  clearTimeout(t.timer);
  t.timer = setTimeout(() => (t.style.display = "none"), 4500);
}
async function raw(path, options = {}) {
  return fetch("/api" + path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf(),
      ...options.headers,
    },
  });
}
async function renew() {
  if (!renewing)
    renewing = (async () => {
      const run = async () => {
        const check = await raw("/auth/me");
        if (check.ok) return true;
        return (await raw("/auth/refresh", { method: "POST" })).ok;
      };
      return navigator.locks
        ? navigator.locks.request("nexus-refresh", run)
        : run();
    })().finally(() => (renewing = null));
  return renewing;
}
async function api(path, options = {}, retry = true) {
  let r = await raw(path, options);
  if (r.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await renew()) r = await raw(path, options);
    else {
      state.user = null;
      renderAuth();
      throw Error("Your session has expired. Please sign in.");
    }
  }
  const body = await r
    .json()
    .catch(() => ({ detail: "The service returned an unexpected response." }));
  if (!r.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : "Check the entered information and try again.";
    throw Error(
      detail +
        (r.headers.get("Retry-After")
          ? ` Retry in ${Math.ceil(Number(r.headers.get("Retry-After")) / 60)} minute(s).`
          : ""),
    );
  }
  return body;
}
const post = (path, data) =>
  api(path, { method: "POST", body: JSON.stringify(data) }, false);
function renderAuth(message = "") {
  clearInterval(poll);
  const mode = state.auth;
  const titles = {
    login: ["Welcome back", "Sign in to your private workspace."],
    signup: [
      "Create your account",
      "Start with your email. Verify it to join.",
    ],
    verify: [
      "Check your inbox",
      "Enter the six-digit code sent to your email.",
    ],
    forgot: [
      "Forgot your password?",
      "We’ll email a code if your account is eligible.",
    ],
    reset: [
      "Set a new password",
      "Enter your email code and choose a new password.",
    ],
  };
  const [title, subtitle] = titles[mode];
  root.innerHTML = `<main class="auth"><section class="story"><div class="brand"><span class="mark">✦</span>nexus</div><h1>Your knowledge.<br><span>A clearer answer.</span></h1><p class="subtle">Bring your documents together. Ask better questions. Find answers with sources you can return to.</p><div class="scene" aria-hidden="true"><div class="orbit"><div class="tile"></div><div class="tile"></div><div class="tile"></div></div></div><footer>A private space for your work.</footer></section><section class="auth-panel"><div class="form-card"><p class="eyebrow">NEXUS WORKSPACE</p><h2>${title}</h2><p class="subtle">${subtitle}</p>${message ? `<p class="notice">${esc(message)}</p>` : ""}<form id="auth-form">
  ${mode === "signup" ? '<label for="name">Full name</label><input id="name" name="name" required maxlength="80" autocomplete="name" placeholder="Alex Morgan">' : ""}
  <label for="email">Email address</label><input id="email" name="email" type="email" required autocomplete="email" value="${esc(state.email)}" placeholder="you@company.com">
  ${["verify", "reset"].includes(mode) ? '<label for="code">Verification code</label><input id="code" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="000000" required>' : ""}
  ${["login", "signup", "reset"].includes(mode) ? `<label for="password">${mode === "reset" ? "New password" : "Password"}</label><input id="password" name="password" type="password" required minlength="${mode === "login" ? 1 : 12}" maxlength="128" autocomplete="${mode === "login" ? "current-password" : "new-password"}" placeholder="${mode === "login" ? "Enter your password" : "At least 12 characters"}">` : ""}
  ${mode === "reset" ? '<label for="confirm">Confirm new password</label><input id="confirm" name="confirm" type="password" required minlength="12" maxlength="128" autocomplete="new-password">' : ""}
  ${mode === "login" ? '<button type="button" class="quiet" data-auth="forgot">Forgot password?</button>' : ""}
  <div id="auth-error" class="error" role="alert"></div><button class="primary" type="submit">${{ login: "Sign in →", signup: "Send verification code →", verify: "Verify email →", forgot: "Send reset code →", reset: "Change password →" }[mode]}</button></form>
  ${mode === "login" || mode === "signup" ? `<div class="divider">or</div>${state.config.google_enabled ? '<a class="google" href="/api/auth/google/start">Continue with Google</a>' : '<p class="small-note">Google sign-in is not configured for this workspace yet.</p>'}` : ""}
  <p class="small-note">${mode === "login" ? 'New to Nexus? <button class="quiet" data-auth="signup">Create an account</button>' : '<button class="quiet" data-auth="login">Back to sign in</button>'}</p>${["verify", "reset"].includes(mode) ? '<p class="small-note">Codes expire in 10 minutes. To request another, restart signup or password reset after 60 seconds.</p>' : ""}</div></section></main>`;
  root.querySelectorAll("[data-auth]").forEach(
    (b) =>
      (b.onclick = () => {
        state.email = root.querySelector("#email").value;
        state.auth = b.dataset.auth;
        renderAuth();
      }),
  );
  root.querySelector("#auth-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.currentTarget,
      data = Object.fromEntries(new FormData(form));
    const button = form.querySelector("[type=submit]");
    button.disabled = true;
    button.textContent = "Please wait…";
    state.email = data.email;
    try {
      if (mode === "reset" && data.password !== data.confirm)
        throw Error("The passwords do not match.");
      delete data.confirm;
      const paths = {
        login: "login",
        signup: "signup",
        verify: "verify-email",
        forgot: "forgot-password",
        reset: "reset-password",
      };
      const result = await post("/auth/" + paths[mode], data);
      if (mode === "login") {
        state.user = result.user;
        state.auth = "login";
        await showApp();
      } else {
        state.auth = {
          signup: "verify",
          verify: "login",
          forgot: "reset",
          reset: "login",
        }[mode];
        renderAuth(result.message);
      }
    } catch (err) {
      document.querySelector("#auth-error").textContent = err.message;
      button.disabled = false;
      button.textContent = "Try again";
    }
  };
}
async function showApp() {
  clearInterval(poll);
  root.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><span class="mark">✦</span>nexus</div><nav class="nav" aria-label="Main navigation"><button data-view="chat">✧ &nbsp; Ask Nexus</button><button data-view="documents">▤ &nbsp; My documents</button><button data-view="history">↶ &nbsp; Search history</button><button data-view="security">⚿ &nbsp; Account security</button></nav><div class="account"><span class="badge">PRIVATE WORKSPACE</span><strong>${esc(state.user.name)}</strong><span class="subtle">${esc(state.user.email)}</span><br><button class="quiet" id="logout">Sign out ↗</button></div></aside><main class="main"><header class="topbar"><span id="breadcrumb">Workspace / Ask Nexus</span><button class="quiet" id="mobile-logout">Sign out</button></header><section class="workspace" id="workspace"></section></main></div>`;
  root.querySelectorAll("[data-view]").forEach(
    (b) =>
      (b.onclick = () => {
        state.view = b.dataset.view;
        renderView();
      }),
  );
  const logout = async () => {
    try {
      await post("/auth/logout", {});
      state.user = null;
      state.answer = null;
      state.history = [];
      state.docs = [];
      state.auth = "login";
      renderAuth();
    } catch (e) {
      toast(e.message);
    }
  };
  root.querySelector("#logout").onclick = logout;
  root.querySelector("#mobile-logout").onclick = logout;
  await renderView();
}
async function renderView() {
  clearInterval(poll);
  root
    .querySelectorAll("[data-view]")
    .forEach((b) =>
      b.classList.toggle("active", b.dataset.view === state.view),
    );
  root.querySelector("#breadcrumb").textContent =
    "Workspace / " +
    {
      chat: "Ask Nexus",
      documents: "My documents",
      history: "Search history",
      security: "Account security",
    }[state.view];
  const w = root.querySelector("#workspace");
  w.innerHTML = '<p class="subtle">Loading your workspace…</p>';
  try {
    if (state.view === "chat") {
      state.docs = await api("/documents");
      renderChat();
    }
    if (state.view === "documents") {
      state.docs = await api("/documents");
      renderDocuments();
      poll = setInterval(refreshDocs, 5000);
    }
    if (state.view === "security") {
      await renderSecurity();
    }
    if (state.view === "history") {
      state.history = await api("/history");
      renderHistory();
    }
  } catch (e) {
    if (state.user)
      w.innerHTML = `<p class="error" role="alert">${esc(e.message)}</p>`;
  }
}
function answerHTML(a) {
  return `<article class="answer"><h3>${esc(a.question)}</h3><div class="answer-body">${esc(a.answer)}</div><div class="sources">${a.sources.length} source excerpts${a.sources.map((s, i) => `<details><summary>[${i + 1}] ${esc(s.title)} · excerpt ${s.chunk + 1}</summary><p>${esc(s.text)}</p></details>`).join("")}</div></article>`;
}
function renderChat() {
  const ready = state.docs.filter((d) => d.status === "ready").length;
  const w = root.querySelector("#workspace");
  w.innerHTML = `<div class="welcome"><div class="mini-mark" aria-hidden="true">✧</div><p class="eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</p><h1>What would you like to discover?</h1><p class="subtle">Ask your documents. Get answers with a source.</p></div>${!state.config.ai_configured ? '<p class="notice">AI search needs an AWS Bedrock model configured by your administrator.</p>' : ""}${!ready ? '<p class="notice">Add a document and wait for indexing to finish to start a conversation. <button class="quiet" id="go-docs">Open my documents →</button></p>' : ""}<div class="cards">${[
    ["✦", "Summarize the key ideas in my documents."],
    ["⌘", "What are the most important decisions?"],
    ["↗", "Which actions should I take next?"],
  ]
    .map(
      ([icon, q]) =>
        `<button class="suggestion" data-question="${esc(q)}"><span>${icon}</span>${q}</button>`,
    )
    .join(
      "",
    )}</div><div id="answers">${state.answer ? answerHTML(state.answer) : ""}</div><form class="composer" id="ask-form"><label class="hidden" for="question">Your question</label><textarea id="question" required minlength="2" maxlength="2000" placeholder="Ask anything about your documents…"></textarea><div class="compose-bottom"><span>${ready} ready document${ready === 1 ? "" : "s"} · Private to you</span><button class="primary" type="submit" ${!ready ? "disabled" : ""}>Ask Nexus ↑</button></div><div id="ask-error" class="error" role="alert"></div></form><p class="small-note">AI answers can be incomplete. Open the sources to check important details.</p>`;
  w.querySelector("#go-docs")?.addEventListener("click", () => {
    state.view = "documents";
    renderView();
  });
  w.querySelectorAll("[data-question]").forEach(
    (b) =>
      (b.onclick = () => {
        w.querySelector("#question").value = b.dataset.question;
        w.querySelector("#question").focus();
      }),
  );
  w.querySelector("#ask-form").onsubmit = async (e) => {
    e.preventDefault();
    const b = e.currentTarget.querySelector("button");
    b.disabled = true;
    b.textContent = "Searching…";
    w.querySelector("#ask-error").textContent = "";
    try {
      state.answer = await api("/chat", {
        method: "POST",
        body: JSON.stringify({ question: w.querySelector("#question").value }),
      });
      w.querySelector("#answers").innerHTML = answerHTML(state.answer);
      w.querySelector("#question").value = "";
    } catch (err) {
      if (state.user) w.querySelector("#ask-error").textContent = err.message;
    } finally {
      b.disabled = false;
      b.textContent = "Ask Nexus ↑";
    }
  };
}
function docsHTML() {
  return state.docs.length
    ? state.docs
        .map(
          (d) =>
            `<div class="document"><span class="doc-icon">▤</span><div class="info"><strong>${esc(d.title)}</strong><small>Added ${new Date(d.created * 1000).toLocaleDateString()}</small></div><span class="status">${{ pending: "Queued / retrying…", processing: "Indexing…", ready: "Ready to search", failed: "Indexing failed — remove and upload again" }[d.status] || esc(d.status)}</span><button class="quiet" data-delete="${esc(d.id)}" aria-label="Delete ${esc(d.title)}">Remove</button></div>`,
        )
        .join("")
    : '<div class="empty">Your next answer starts with a document.<br>Add a text or Markdown file to get started.</div>';
}
function bindDeletes() {
  root.querySelectorAll("[data-delete]").forEach(
    (b) =>
      (b.onclick = async () => {
        if (
          !confirm(
            "Remove this document? Saved answers in history will remain.",
          )
        )
          return;
        try {
          await api("/documents/" + encodeURIComponent(b.dataset.delete), {
            method: "DELETE",
          });
          await refreshDocs();
          toast("Document removed.");
        } catch (e) {
          toast(e.message);
        }
      }),
  );
}
async function refreshDocs() {
  if (state.view !== "documents" || !state.user) return;
  try {
    state.docs = await api("/documents");
    const list = document.querySelector("#doc-list");
    if (list) {
      list.innerHTML = docsHTML();
      bindDeletes();
    }
  } catch (e) {
    toast(e.message);
  }
}
function renderDocuments() {
  const w = root.querySelector("#workspace");
  w.innerHTML = `<div class="page-heading"><div><p class="eyebrow">YOUR SOURCES</p><h2>My documents</h2><p class="subtle">The context behind every answer. Visible only to you.</p></div><button class="primary" id="show-upload">+ Add document</button></div><form id="upload-form" class="upload hidden"><h3>Add a document</h3><label for="file">Text or Markdown file (optional)</label><input id="file" type="file" accept=".txt,.md,text/plain,text/markdown"><label for="doc-title">Document title</label><input id="doc-title" required maxlength="160" placeholder="e.g. Product launch notes"><label for="doc-text">Document text · up to 20,000 characters</label><textarea id="doc-text" required minlength="20" maxlength="20000" placeholder="Paste your document here…"></textarea><div id="upload-error" class="error" role="alert"></div><div class="actions"><button class="primary" type="submit">Add to workspace</button><button id="cancel-upload" type="button">Cancel</button></div></form><div id="doc-list">${docsHTML()}</div>`;
  w.querySelector("#show-upload").onclick = () => {
    w.querySelector("#upload-form").classList.remove("hidden");
    w.querySelector("#doc-title").focus();
  };
  w.querySelector("#cancel-upload").onclick = () =>
    w.querySelector("#upload-form").classList.add("hidden");
  w.querySelector("#file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 80000 || !/\.(txt|md)$/i.test(f.name)) {
      toast("Choose a text or Markdown file under 80 KB.");
      return;
    }
    const text = await f.text();
    if (text.length > 20000) {
      toast("This file exceeds the 20,000 character limit.");
      return;
    }
    w.querySelector("#doc-title").value = f.name.slice(0, 160);
    w.querySelector("#doc-text").value = text;
  };
  w.querySelector("#upload-form").onsubmit = async (e) => {
    e.preventDefault();
    const b = e.currentTarget.querySelector("[type=submit]");
    b.disabled = true;
    try {
      await api("/documents", {
        method: "POST",
        body: JSON.stringify({
          title: w.querySelector("#doc-title").value,
          text: w.querySelector("#doc-text").value,
        }),
      });
      e.target.reset();
      e.target.classList.add("hidden");
      await refreshDocs();
      toast("Document added. Indexing will begin shortly.");
    } catch (err) {
      if (state.user)
        w.querySelector("#upload-error").textContent = err.message;
    } finally {
      b.disabled = false;
    }
  };
  bindDeletes();
}
function renderHistory() {
  const w = root.querySelector("#workspace");
  w.innerHTML = `<div class="page-heading"><div><p class="eyebrow">PICK UP WHERE YOU LEFT OFF</p><h2>Search history</h2><p class="subtle">Your latest 100 questions and saved answers.</p></div><button id="clear-history" ${!state.history.length ? "disabled" : ""}>Clear history</button></div>${state.history.length ? state.history.map((h) => `<button class="history-item" data-history="${esc(h.id)}"><span>${esc(h.question)}</span><span class="subtle">${new Date(h.created * 1000).toLocaleDateString()} ↗</span></button>`).join("") : '<div class="empty">Your saved answers will appear here after your first question.</div>'}`;
  w.querySelectorAll("[data-history]").forEach(
    (b) =>
      (b.onclick = () => {
        state.answer = state.history.find((h) => h.id === b.dataset.history);
        state.view = "chat";
        renderView();
      }),
  );
  w.querySelector("#clear-history").onclick = async () => {
    if (!confirm("Permanently clear all your search history?")) return;
    try {
      await api("/history", { method: "DELETE" });
      state.history = [];
      state.answer = null;
      renderHistory();
    } catch (e) {
      toast(e.message);
    }
  };
}
(async () => {
  try {
    state.config = await api("/config", {}, false);
    let r = await raw("/auth/me");
    if (r.status === 401 && csrf() && (await renew()))
      r = await raw("/auth/me");
    if (r.ok) {
      state.user = (await r.json()).user;
      await showApp();
    } else renderAuth();
  } catch (e) {
    renderAuth();
    document.querySelector("#auth-error").textContent = e.message;
  }
})();

async function renderSecurity() {
  const sessions = await api("/account/sessions");
  const w = root.querySelector("#workspace");
  w.innerHTML = `<div class="page-heading"><div><p class="eyebrow">YOU ARE IN CONTROL</p><h2>Account security</h2><p class="subtle">Review your sessions and secure your account.</p></div><button id="logout-all">Sign out everywhere</button></div><h3>Signed-in sessions</h3>${sessions.map((s) => `<div class="document"><div class="info"><strong>${s.current ? "This browser" : esc(s.device)}</strong><small>Last active ${new Date(s.last_seen * 1000).toLocaleString()}</small></div><button data-revoke="${esc(s.id)}" data-current="${s.current}">Sign out</button></div>`).join("")}<form class="upload" id="change-password"><h3>Change password</h3><p class="subtle">For email/password accounts. Changing your password signs out every session.</p><label for="current-password">Current password</label><input id="current-password" type="password" autocomplete="current-password" maxlength="128" required><label for="new-password">New password</label><input id="new-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><label for="confirm-password">Confirm new password</label><input id="confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><div class="actions"><button class="primary" type="submit">Change password</button></div><div id="security-error" class="error" role="alert"></div></form>`;
  const resetUI = () => {
    state.user = null;
    state.answer = null;
    state.history = [];
    state.docs = [];
    state.auth = "login";
    renderAuth("You have been signed out.");
  };
  w.querySelector("#logout-all").onclick = async () => {
    if (!confirm("Sign out all browsers, including this one?")) return;
    try {
      await api("/account/logout-all", { method: "POST" });
      resetUI();
    } catch (e) {
      toast(e.message);
    }
  };
  w.querySelectorAll("[data-revoke]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await api(
            "/account/sessions/" + encodeURIComponent(b.dataset.revoke),
            { method: "DELETE" },
          );
          if (b.dataset.current === "true") resetUI();
          else await renderSecurity();
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  w.querySelector("#change-password").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.currentTarget.querySelector("button");
    button.disabled = true;
    try {
      const password = w.querySelector("#new-password").value;
      if (password !== w.querySelector("#confirm-password").value)
        throw Error("The new passwords do not match.");
      await api("/account/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: w.querySelector("#current-password").value,
          new_password: password,
        }),
      });
      resetUI();
    } catch (err) {
      if (state.user)
        w.querySelector("#security-error").textContent = err.message;
    } finally {
      button.disabled = false;
    }
  };
}
