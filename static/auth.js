/* Bookly login. Drop this + auth.css onto any page with an
 * <span id="bookly-auth-slot"></span> in its nav and it wires itself up
 * against POST /api/login, /api/logout, GET /api/me (app/channels/web.py).
 *
 * This is what lets the chat widget stop asking for order ID + email once
 * a customer is signed in -- see app/memory.py's authenticated_email and
 * app/orchestrator.py's identity-gated tool override for the other half.
 *
 * Exposes window.BooklyAuth = { currentUser(), open() } so widget.js can
 * personalize its greeting without duplicating the /api/me fetch.
 */
(function () {
  const slot = document.getElementById("bookly-auth-slot");

  const modal = document.createElement("div");
  modal.id = "bookly-auth-modal";
  modal.innerHTML = `
    <div class="auth-card" role="dialog" aria-label="Sign in to Bookly">
      <button type="button" class="auth-close" id="auth-close" aria-label="Close">&times;</button>
      <h2>Sign in</h2>
      <p class="auth-sub">So Bookly Concierge already knows who you are -- no more repeating your order ID and email in chat.</p>
      <div class="auth-error" id="auth-error"></div>
      <form id="auth-form">
        <label for="auth-email">Email</label>
        <input type="email" id="auth-email" autocomplete="username" required />
        <label for="auth-password">Password</label>
        <input type="password" id="auth-password" autocomplete="current-password" required />
        <button type="submit" class="auth-submit" id="auth-submit">Sign in</button>
      </form>
      <p class="auth-hint">Demo account: any password works for <code>alice@example.com</code> or <code>bob@example.com</code>.</p>
    </div>
  `;
  document.body.appendChild(modal);

  const closeBtn = modal.querySelector("#auth-close");
  const form = modal.querySelector("#auth-form");
  const emailInput = modal.querySelector("#auth-email");
  const passwordInput = modal.querySelector("#auth-password");
  const submitBtn = modal.querySelector("#auth-submit");
  const errorBox = modal.querySelector("#auth-error");

  let currentUser = null;

  function openModal() {
    errorBox.classList.remove("show");
    passwordInput.value = "";
    modal.classList.add("open");
    setTimeout(() => emailInput.focus(), 50);
  }

  function closeModal() {
    modal.classList.remove("open");
  }

  function renderSlot() {
    if (!slot) return;
    if (currentUser) {
      slot.innerHTML = `
        <span class="auth-greeting">Hi, <strong>${currentUser.name}</strong></span>
        <button type="button" class="auth-link" id="auth-signout">Sign out</button>
      `;
      slot.querySelector("#auth-signout").addEventListener("click", signOut);
    } else {
      slot.innerHTML = `<button type="button" class="auth-link" id="auth-signin">Sign in</button>`;
      slot.querySelector("#auth-signin").addEventListener("click", openModal);
    }
  }

  async function refreshUser() {
    try {
      const res = await fetch("/api/me");
      currentUser = res.ok ? await res.json() : null;
    } catch (err) {
      currentUser = null;
    }
    renderSlot();
  }

  async function signOut() {
    try {
      await fetch("/api/logout", { method: "POST" });
    } catch (err) {
      /* best-effort -- the cookie will still expire client-side on reload */
    }
    currentUser = null;
    renderSlot();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.classList.remove("show");
    submitBtn.disabled = true;
    submitBtn.textContent = "Signing in...";
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: emailInput.value, password: passwordInput.value }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        errorBox.textContent = body.message || "Couldn't sign in with that email.";
        errorBox.classList.add("show");
        return;
      }
      currentUser = await res.json();
      renderSlot();
      closeModal();
    } catch (err) {
      errorBox.textContent = "Something went wrong -- please try again.";
      errorBox.classList.add("show");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Sign in";
    }
  });

  closeBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("open")) closeModal();
  });

  refreshUser();

  window.BooklyAuth = {
    currentUser: () => currentUser,
    open: openModal,
  };
})();
