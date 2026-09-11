const express = require('express');
const path = require('path');
const fs = require('fs');
const colors = require('./data/colors');

const app = express();
const PORT = process.env.PORT || 3000;
const RECENT_FILE = path.join(__dirname, 'data', 'recent.json');
const MAX_RECENT = 5;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return { r, g, b };
}

function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h /= 6;
  }

  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
}

function readRecent() {
  try {
    const raw = fs.readFileSync(RECENT_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    return [];
  }
}

function writeRecent(list) {
  fs.writeFileSync(RECENT_FILE, JSON.stringify(list, null, 2), 'utf-8');
}

app.get('/api/colors', (req, res) => {
  const enriched = colors.map((c) => {
    const rgb = hexToRgb(c.hex);
    const hsl = rgbToHsl(rgb.r, rgb.g, rgb.b);
    return { ...c, rgb, hsl };
  });
  res.json(enriched);
});

app.get('/api/recent', (req, res) => {
  res.json(readRecent().slice(0, MAX_RECENT));
});

app.post('/api/recent', (req, res) => {
  const { name, hex } = req.body || {};
  if (!name || typeof hex !== 'string' || !/^#([0-9A-Fa-f]{6})$/.test(hex)) {
    return res.status(400).json({ error: 'A valid name and hex color are required.' });
  }

  const list = readRecent();
  list.unshift({ name, hex, timestamp: new Date().toISOString() });
  const trimmed = list.slice(0, MAX_RECENT);
  writeRecent(trimmed);
  res.json(trimmed);
});

app.listen(PORT, () => {
  console.log(`Color Palette Explorer running at http://localhost:${PORT}`);
});
