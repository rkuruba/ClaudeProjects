(function () {
  'use strict';

  const STORAGE_KEY = 'futureMe.messages';
  const THEME_KEY = 'futureMe.theme';

  const QUOTES = [
    "The future depends on what you do today.",
    "Write it down. Let time carry the weight of remembering.",
    "You are one decision away from a completely different life.",
    "Be patient with yourself. Growth is quiet before it's visible.",
    "Every letter to the future is a gift to someone you haven't met yet.",
    "Small steps, taken daily, become the person you're becoming.",
    "Hope is a promise you make to your future self.",
    "The best time to plant a tree was 20 years ago. The second best is now.",
    "Someday is not a day of the week. Start today.",
    "Your future self is watching you right now through memory."
  ];

  const form = document.getElementById('futureForm');
  const nameInput = document.getElementById('nameInput');
  const messageInput = document.getElementById('messageInput');
  const dateInput = document.getElementById('dateInput');
  const charCount = document.getElementById('charCount');
  const formError = document.getElementById('formError');
  const messagesList = document.getElementById('messagesList');
  const emptyState = document.getElementById('emptyState');
  const capsuleCount = document.getElementById('capsuleCount');
  const themeToggle = document.getElementById('themeToggle');
  const quoteText = document.getElementById('quoteText');
  const toast = document.getElementById('toast');

  let toastTimer = null;
  let quoteTimer = null;
  let tickTimer = null;

  /* ---------------- Theme ---------------- */

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    const prefersLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
    const theme = saved || (prefersLight ? 'light' : 'dark');
    applyTheme(theme);
  }

  function applyTheme(theme) {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem(THEME_KEY, theme);
  }

  themeToggle.addEventListener('click', function () {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    applyTheme(isLight ? 'dark' : 'light');
  });

  /* ---------------- Quotes ---------------- */

  function pickQuote(exclude) {
    let q = QUOTES[Math.floor(Math.random() * QUOTES.length)];
    if (QUOTES.length > 1) {
      let guard = 0;
      while (q === exclude && guard < 10) {
        q = QUOTES[Math.floor(Math.random() * QUOTES.length)];
        guard++;
      }
    }
    return q;
  }

  function startQuoteRotation() {
    let current = pickQuote();
    quoteText.textContent = current;
    quoteTimer = setInterval(function () {
      quoteText.classList.add('fade');
      setTimeout(function () {
        current = pickQuote(current);
        quoteText.textContent = current;
        quoteText.classList.remove('fade');
      }, 400);
    }, 6000);
  }

  /* ---------------- Storage ---------------- */

  function loadMessages() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      console.error('Failed to parse stored messages', e);
      return [];
    }
  }

  function saveMessages(messages) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  }

  function addMessage(entry) {
    const messages = loadMessages();
    messages.push(entry);
    saveMessages(messages);
  }

  function deleteMessage(id) {
    const messages = loadMessages().filter(function (m) { return m.id !== id; });
    saveMessages(messages);
  }

  /* ---------------- Toast ---------------- */

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('show');
    }, 2600);
  }

  /* ---------------- Form ---------------- */

  messageInput.addEventListener('input', function () {
    charCount.textContent = messageInput.value.length;
  });

  function setMinDate() {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    dateInput.min = now.toISOString().slice(0, 16);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    formError.textContent = '';

    const name = nameInput.value.trim();
    const message = messageInput.value.trim();
    const dateVal = dateInput.value;

    if (!name || !message || !dateVal) {
      formError.textContent = 'Please fill in every field before sealing your letter.';
      return;
    }

    const unlockTime = new Date(dateVal).getTime();
    if (isNaN(unlockTime) || unlockTime <= Date.now()) {
      formError.textContent = 'Please choose a date and time in the future.';
      return;
    }

    const entry = {
      id: (Date.now().toString(36) + Math.random().toString(36).slice(2, 8)),
      name: name,
      message: message,
      createdAt: Date.now(),
      unlockAt: unlockTime,
      revealed: false
    };

    addMessage(entry);
    form.reset();
    charCount.textContent = '0';
    setMinDate();
    renderMessages();
    showToast('Sealed! Your letter is on its way to the future. ✨');
  });

  /* ---------------- Rendering ---------------- */

  function formatDate(ts) {
    return new Date(ts).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  }

  function getCountdownParts(ms) {
    const clamped = Math.max(ms, 0);
    const totalSeconds = Math.floor(clamped / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return { days: days, hours: hours, minutes: minutes, seconds: seconds };
  }

  function buildCapsuleNode(entry) {
    const node = document.createElement('article');
    node.className = 'capsule';
    node.dataset.id = entry.id;
    node.dataset.unlockAt = String(entry.unlockAt);
    node.dataset.createdAt = String(entry.createdAt);
    node.dataset.unlocked = 'false';

    node.innerHTML =
      '<div class="capsule-top">' +
        '<div class="capsule-name">📨 ' + escapeHtml(entry.name) + '</div>' +
        '<div class="capsule-status locked">Locked</div>' +
      '</div>' +
      '<div class="capsule-meta">Sealed ' + escapeHtml(formatDate(entry.createdAt)) + ' &middot; Opens ' + escapeHtml(formatDate(entry.unlockAt)) + '</div>' +
      '<div class="capsule-countdown">' +
        '<div class="time-chip"><span class="num" data-part="days">0</span><span class="unit">Days</span></div>' +
        '<div class="time-chip"><span class="num" data-part="hours">0</span><span class="unit">Hrs</span></div>' +
        '<div class="time-chip"><span class="num" data-part="minutes">0</span><span class="unit">Min</span></div>' +
        '<div class="time-chip"><span class="num" data-part="seconds">0</span><span class="unit">Sec</span></div>' +
      '</div>' +
      '<div class="progress-track"><div class="progress-fill"></div></div>' +
      '<div class="capsule-message"></div>' +
      '<div class="capsule-actions"><button type="button" class="btn-delete">Delete</button></div>';

    node.querySelector('.btn-delete').addEventListener('click', function () {
      deleteMessage(entry.id);
      node.remove();
      updateEmptyAndCount();
      showToast('Capsule deleted.');
    });

    return node;
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMessages() {
    const messages = loadMessages().sort(function (a, b) { return a.unlockAt - b.unlockAt; });
    messagesList.innerHTML = '';
    messages.forEach(function (entry) {
      messagesList.appendChild(buildCapsuleNode(entry));
    });
    updateEmptyAndCount();
    tickAll();
  }

  function updateEmptyAndCount() {
    const count = messagesList.children.length;
    capsuleCount.textContent = String(count);
    emptyState.style.display = count === 0 ? 'flex' : 'none';
  }

  /* ---------------- Ticking / unlock logic ---------------- */

  function tickAll() {
    const now = Date.now();
    const messages = loadMessages();
    const byId = {};
    messages.forEach(function (m) { byId[m.id] = m; });

    Array.prototype.forEach.call(messagesList.children, function (node) {
      const entry = byId[node.dataset.id];
      if (!entry) return;

      const unlockAt = entry.unlockAt;
      const createdAt = entry.createdAt;
      const remaining = unlockAt - now;
      const isUnlocked = remaining <= 0;

      const parts = getCountdownParts(remaining);
      const daysEl = node.querySelector('[data-part="days"]');
      const hoursEl = node.querySelector('[data-part="hours"]');
      const minutesEl = node.querySelector('[data-part="minutes"]');
      const secondsEl = node.querySelector('[data-part="seconds"]');
      if (daysEl) daysEl.textContent = parts.days;
      if (hoursEl) hoursEl.textContent = String(parts.hours).padStart(2, '0');
      if (minutesEl) minutesEl.textContent = String(parts.minutes).padStart(2, '0');
      if (secondsEl) secondsEl.textContent = String(parts.seconds).padStart(2, '0');

      const totalSpan = Math.max(unlockAt - createdAt, 1);
      const elapsed = Math.min(Math.max(now - createdAt, 0), totalSpan);
      const pct = Math.min(100, (elapsed / totalSpan) * 100);
      const fill = node.querySelector('.progress-fill');
      if (fill) fill.style.width = pct + '%';

      const statusEl = node.querySelector('.capsule-status');
      const msgEl = node.querySelector('.capsule-message');
      const wasUnlocked = node.dataset.unlocked === 'true';

      if (isUnlocked) {
        node.classList.add('unlocked');
        node.querySelector('.capsule-countdown').style.display = 'none';
        if (statusEl) {
          statusEl.textContent = 'Unlocked';
          statusEl.classList.remove('locked');
          statusEl.classList.add('unlocked-badge');
        }
        if (msgEl) {
          msgEl.textContent = entry.message;
          msgEl.classList.remove('blurred');
        }
        if (!wasUnlocked) {
          node.dataset.unlocked = 'true';
          node.classList.add('revealing');
          setTimeout(function () { node.classList.remove('revealing'); }, 1300);
          if (!entry.revealed) {
            entry.revealed = true;
            const all = loadMessages().map(function (m) {
              return m.id === entry.id ? Object.assign({}, m, { revealed: true }) : m;
            });
            saveMessages(all);
            showToast('A capsule from ' + entry.name + ' just unlocked! 🎉');
          }
        }
      } else {
        node.dataset.unlocked = 'false';
        if (msgEl) {
          msgEl.textContent = entry.message;
          msgEl.classList.add('blurred');
        }
      }
    });
  }

  function startTicking() {
    tickAll();
    tickTimer = setInterval(tickAll, 1000);
  }

  /* ---------------- Init ---------------- */

  function init() {
    initTheme();
    setMinDate();
    startQuoteRotation();
    renderMessages();
    startTicking();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
