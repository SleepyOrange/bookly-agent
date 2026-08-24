/* Bookly Concierge widget. Drop this + widget.css onto any page and it wires
 * itself up against POST /api/chat -- the same endpoint the standalone
 * /chat page and the CLI ultimately go through (app/orchestrator.py).
 * No page-specific code required beyond including these two files.
 *
 * Exposes window.BooklyWidget = { open(), sendMessage(text), endSession() }
 * so the host page can deep-link into the agent (see the footer links on
 * the storefront) or trigger a fresh conversation programmatically.
 */
(function () {
  const CHAT_ICON = `<svg class="bw-icon-chat" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4 12c0-4.42 3.58-8 8-8s8 3.58 8 8-3.58 8-8 8c-1.13 0-2.2-.23-3.18-.66L4 21l1.66-4.82C4.6 14.98 4 13.55 4 12Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>`;
  const CLOSE_ICON = `<svg class="bw-icon-close" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display:none"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
  const RESET_ICON = `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 12a9 9 0 1 0 2.6-6.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M3 5v5h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

  const root = document.createElement("div");
  root.id = "bookly-widget";
  root.innerHTML = `
    <div class="bw-nudge" id="bw-nudge">
      <button class="bw-nudge-close" id="bw-nudge-close" aria-label="Dismiss">&times;</button>
      Need a hand with an order, a return, or anything else?
    </div>
    <div class="bw-panel" role="dialog" aria-label="Bookly Concierge chat" aria-hidden="true">
      <div class="bw-header">
        <div class="bw-header-title">
          <strong>Bookly Concierge</strong>
          <span class="bw-status"><span class="bw-status-dot"></span><span id="bw-status-text">Usually replies in seconds</span></span>
        </div>
        <div class="bw-header-actions">
          <button class="bw-reset" id="bw-reset" aria-label="End this conversation and start fresh" title="New conversation">${RESET_ICON}</button>
          <button class="bw-close" id="bw-close" aria-label="Close chat">&times;</button>
        </div>
      </div>
      <div class="bw-log" id="bw-log"></div>
      <div class="bw-suggestions" id="bw-suggestions">
        <button type="button" data-msg="Where is my order?">Where's my order?</button>
        <button type="button" data-msg="I want to return a book">Return a book</button>
        <button type="button" data-msg="What's your return policy?">Return policy</button>
      </div>
      <form class="bw-form" id="bw-form">
        <input type="text" id="bw-input" placeholder="Type a message..." autocomplete="off" aria-label="Message" />
        <button type="submit">Send</button>
      </form>
    </div>
    <button class="bw-launcher" id="bw-launcher" aria-haspopup="dialog" aria-expanded="false" aria-label="Open Bookly Concierge chat">
      ${CHAT_ICON}${CLOSE_ICON}
    </button>
  `;
  document.body.appendChild(root);

  const launcher = root.querySelector("#bw-launcher");
  const panel = root.querySelector(".bw-panel");
  const closeBtn = root.querySelector("#bw-close");
  const resetBtn = root.querySelector("#bw-reset");
  const log = root.querySelector("#bw-log");
  const form = root.querySelector("#bw-form");
  const input = root.querySelector("#bw-input");
  const suggestions = root.querySelector("#bw-suggestions");
  const nudge = root.querySelector("#bw-nudge");
  const nudgeClose = root.querySelector("#bw-nudge-close");
  const statusText = root.querySelector("#bw-status-text");

  let sessionId = sessionStorage.getItem("bookly_session_id") || null;
  let greeted = false;

  // Fetched once, best-effort -- if this fails, the chat still works fine,
  // it just never shows product cards. Same catalog data the storefront
  // already renders, so book titles named in a reply have real cover art
  // to point at, not a description asking you to imagine it.
  const catalogByTitle = new Map();
  fetch("/api/catalog")
    .then((res) => (res.ok ? res.json() : []))
    .then((books) => books.forEach((b) => catalogByTitle.set(b.title, b)))
    .catch(() => {});

  // Escape first, unconditionally, so nothing in a tool result or a
  // customer's own message can inject real HTML -- only *after* that is it
  // safe to turn the few markdown patterns the model actually produces
  // (bold, bullet lines) into real formatting instead of literal
  // asterisks/dashes. Not a full markdown parser on purpose -- just the
  // patterns actually seen in replies.
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Bullet markers before italics, and only "- " (not "* "): a bare
    // asterisk-space list marker would otherwise look like the opening of
    // an italic run to the regex below, and [^*] matches across newlines,
    // so it could span from one bullet's "*" all the way to the next
    // line's, mangling both. Restricting to "-" sidesteps that entirely.
    html = html.replace(/^- (.+)$/gm, "&bull; $1");
    html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    return html;
  }

  function addBubble(role, text, pending) {
    const row = document.createElement("div");
    row.className = "bw-row " + role;
    const bubble = document.createElement("div");
    bubble.className = "bw-bubble" + (pending ? " pending" : "");
    if (role === "agent") bubble.innerHTML = renderMarkdown(text);
    else bubble.textContent = text;
    row.appendChild(bubble);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  function addProductCard(book) {
    const row = document.createElement("div");
    row.className = "bw-row agent";
    const card = document.createElement("div");
    card.className = "bw-product-card";

    const img = document.createElement("img");
    img.src = book.cover_url;
    img.alt = "";
    card.appendChild(img);

    const info = document.createElement("div");
    info.className = "bw-product-info";
    const titleEl = document.createElement("span");
    titleEl.className = "bw-product-title";
    titleEl.textContent = book.title;
    const authorEl = document.createElement("span");
    authorEl.className = "bw-product-author";
    authorEl.textContent = book.author;
    info.append(titleEl, authorEl);
    card.appendChild(info);

    row.appendChild(card);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }

  // Only the latest reply's product card(s) stay visible -- each new reply
  // clears whatever was showing before, rather than accumulating a card per
  // turn for the life of the conversation.
  let currentProductRows = [];

  function showMentionedProducts(replyText) {
    currentProductRows.forEach((row) => row.remove());
    currentProductRows = [];
    catalogByTitle.forEach((book, title) => {
      if (replyText.includes(title)) currentProductRows.push(addProductCard(book));
    });
  }

  function ensureGreeting() {
    if (greeted) return;
    greeted = true;
    // window.BooklyAuth is optional -- auth.js may not be included on every
    // host page (e.g. the bare /chat page), so this degrades to the
    // generic greeting rather than requiring it.
    const user = window.BooklyAuth && window.BooklyAuth.currentUser();
    const greeting = user
      ? `Hi ${user.name.split(" ")[0]}, good to see you -- I already know it's you, so we can skip straight to it. What's going on?`
      : "Hi, I'm your Bookly Concierge -- happy to check on an order, help with a return, or settle a policy question. What can I do for you?";
    addBubble("agent", greeting);
  }

  async function endSession() {
    const idToReset = sessionId;
    sessionId = null;
    sessionStorage.removeItem("bookly_session_id");
    currentProductRows.forEach((row) => row.remove());
    currentProductRows = [];
    log.innerHTML = "";
    greeted = false;
    ensureGreeting();
    if (statusText) {
      const previous = statusText.textContent;
      statusText.textContent = "New conversation started";
      setTimeout(() => {
        statusText.textContent = previous;
      }, 2500);
    }
    if (idToReset) {
      try {
        // Best-effort -- the client-side reset above already happened
        // regardless, so a network hiccup here doesn't strand the customer
        // with a chat that looks reset but isn't. The old Session object on
        // the server (messages, case_state) is simply never referenced
        // again once its id is gone from sessionStorage either way.
        await fetch(`/api/reset?session_id=${encodeURIComponent(idToReset)}`, { method: "POST" });
      } catch (err) {
        /* best-effort, see above */
      }
    }
  }

  function openPanel() {
    root.classList.add("open");
    launcher.setAttribute("aria-expanded", "true");
    panel.setAttribute("aria-hidden", "false");
    nudge.classList.remove("show");
    ensureGreeting();
    setTimeout(() => input.focus(), 50);
  }

  function closePanel() {
    root.classList.remove("open");
    launcher.setAttribute("aria-expanded", "false");
    panel.setAttribute("aria-hidden", "true");
  }

  function togglePanel() {
    if (root.classList.contains("open")) closePanel();
    else openPanel();
  }

  async function sendMessage(text) {
    if (!text || !text.trim()) return;
    if (!root.classList.contains("open")) openPanel();
    addBubble("user", text);
    input.value = "";
    input.disabled = true;
    const pending = addBubble("agent", "Thinking...", true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      const data = await res.json();
      sessionId = data.session_id;
      sessionStorage.setItem("bookly_session_id", sessionId);
      pending.innerHTML = renderMarkdown(data.reply);
      pending.classList.remove("pending");
      showMentionedProducts(data.reply);
    } catch (err) {
      pending.textContent = "Something went wrong reaching support -- please try again in a moment.";
      pending.classList.remove("pending");
    } finally {
      input.disabled = false;
      input.focus();
    }
  }

  launcher.addEventListener("click", togglePanel);
  closeBtn.addEventListener("click", closePanel);
  resetBtn.addEventListener("click", endSession);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(input.value);
  });
  suggestions.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-msg]");
    if (btn) sendMessage(btn.dataset.msg);
  });
  nudgeClose.addEventListener("click", (e) => {
    e.stopPropagation();
    nudge.classList.remove("show");
  });
  nudge.addEventListener("click", openPanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && root.classList.contains("open")) closePanel();
  });

  // A quiet nudge after a few seconds on the page, once per visit.
  if (!sessionStorage.getItem("bookly_nudge_shown")) {
    setTimeout(() => {
      if (!root.classList.contains("open")) {
        nudge.classList.add("show");
        sessionStorage.setItem("bookly_nudge_shown", "1");
        setTimeout(() => nudge.classList.remove("show"), 9000);
      }
    }, 1800);
  }

  // Public API so the host page can deep-link into the agent.
  window.BooklyWidget = {
    open: openPanel,
    close: closePanel,
    sendMessage: sendMessage,
    endSession: endSession,
  };
})();
