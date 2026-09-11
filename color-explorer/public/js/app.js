(function () {
  const grid = document.getElementById('color-grid');
  const noResults = document.getElementById('no-results');
  const searchInput = document.getElementById('search-input');
  const recentList = document.getElementById('recent-list');
  const recentEmpty = document.getElementById('recent-empty');
  const themeToggle = document.getElementById('theme-toggle');
  const themeIcon = document.getElementById('theme-icon');
  const toast = document.getElementById('toast');

  let colors = [];
  let toastTimer = null;

  function getContrastColor(hex) {
    const clean = hex.replace('#', '');
    const r = parseInt(clean.substring(0, 2), 16);
    const g = parseInt(clean.substring(2, 4), 16);
    const b = parseInt(clean.substring(4, 6), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.55 ? '#1c1c28' : '#ffffff';
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add('show');
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2400);
  }

  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
      }
      throw new Error('clipboard API unavailable');
    } catch (err) {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
  }

  function createCard(color) {
    const card = document.createElement('div');
    card.className = 'color-card';
    card.style.backgroundColor = color.hex;
    card.dataset.hex = color.hex;
    card.dataset.name = color.name.toLowerCase();

    const textColor = getContrastColor(color.hex);
    card.style.color = textColor;

    const hint = document.createElement('span');
    hint.className = 'card-hint';
    hint.textContent = 'Click to copy';
    hint.style.color = textColor;

    const name = document.createElement('div');
    name.className = 'card-name';
    name.textContent = color.name;

    const values = document.createElement('div');
    values.className = 'card-values';
    values.innerHTML = `
      <span>${color.hex.toUpperCase()}</span>
      <span>RGB(${color.rgb.r}, ${color.rgb.g}, ${color.rgb.b})</span>
      <span>HSL(${color.hsl.h}, ${color.hsl.s}%, ${color.hsl.l}%)</span>
    `;

    card.appendChild(hint);
    card.appendChild(name);
    card.appendChild(values);

    card.addEventListener('click', () => handleColorClick(color));

    return card;
  }

  function renderGrid(list) {
    grid.innerHTML = '';
    if (list.length === 0) {
      noResults.classList.remove('hidden');
      return;
    }
    noResults.classList.add('hidden');
    list.forEach((color) => grid.appendChild(createCard(color)));
  }

  function renderRecent(list) {
    recentList.querySelectorAll('.recent-swatch').forEach((el) => el.remove());

    if (!list || list.length === 0) {
      recentEmpty.style.display = 'block';
      return;
    }

    recentEmpty.style.display = 'none';
    list.forEach((item) => {
      const swatch = document.createElement('div');
      swatch.className = 'recent-swatch';
      swatch.style.backgroundColor = item.hex;
      swatch.title = `${item.name} · ${item.hex} · ${new Date(item.timestamp).toLocaleString()}`;
      swatch.addEventListener('click', () => {
        const match = colors.find((c) => c.hex.toLowerCase() === item.hex.toLowerCase());
        handleColorClick(match || { name: item.name, hex: item.hex });
      });
      recentList.appendChild(swatch);
    });
  }

  async function loadRecent() {
    try {
      const res = await fetch('/api/recent');
      const list = await res.json();
      renderRecent(list);
    } catch (err) {
      renderRecent([]);
    }
  }

  async function handleColorClick(color) {
    document.body.style.backgroundColor = color.hex;

    await copyToClipboard(color.hex.toUpperCase());
    showToast('Copied HEX to clipboard!');

    try {
      const res = await fetch('/api/recent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: color.name, hex: color.hex })
      });
      const list = await res.json();
      renderRecent(list);
    } catch (err) {
      // Non-fatal: recently-viewed persistence failed, UI already reflects the click.
    }
  }

  function setupSearch() {
    searchInput.addEventListener('input', () => {
      const query = searchInput.value.trim().toLowerCase();
      const filtered = colors.filter(
        (c) => c.name.toLowerCase().includes(query) || c.hex.toLowerCase().includes(query)
      );
      renderGrid(filtered);
    });
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      themeIcon.textContent = '☀️';
    } else {
      document.documentElement.removeAttribute('data-theme');
      themeIcon.textContent = '🌙';
    }
  }

  function setupThemeToggle() {
    const saved = localStorage.getItem('theme') ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    applyTheme(saved);

    themeToggle.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem('theme', next);
    });
  }

  async function init() {
    setupThemeToggle();
    setupSearch();

    try {
      const res = await fetch('/api/colors');
      colors = await res.json();
      renderGrid(colors);
    } catch (err) {
      grid.innerHTML = '<p class="no-results">Could not load colors. Please refresh the page.</p>';
    }

    loadRecent();
  }

  init();
})();
