# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Future Me" — a single-page static web app where users write a letter to their future self, pick an unlock date, and watch a live countdown until the message reveals. No backend, no build step, no package manager: just `index.html`, `style.css`, and `script.js`.

## Running / testing

There is no build system. Open `index.html` directly in a browser, or serve the folder statically, e.g.:

```
npx serve .
```

There are no automated tests or linters configured.

## Architecture

- **`index.html`** — static shell/markup only. All interactive DOM nodes referenced by `script.js` are defined here by id (`futureForm`, `messagesList`, `themeToggle`, `toast`, etc.).
- **`script.js`** — a single IIFE, no modules/bundler, no external JS dependencies. Everything lives in one file, organized into clearly commented sections: Theme, Quotes, Storage, Toast, Form, Rendering, Ticking/unlock logic, Init.
- **`style.css`** — theming via CSS custom properties on `:root`, overridden under `[data-theme="light"]` (dark is the default/no-attribute state). Fonts are loaded from Google Fonts (Poppins for display, Inter for body).

### Data model & persistence

Messages ("capsules") are persisted client-side in `localStorage` under key `futureMe.messages` as a JSON array of:
```js
{ id, name, message, createdAt, unlockAt, revealed }
```
Theme preference is stored separately under `futureMe.theme`. There is no server sync — all state is per-browser.

`loadMessages()` / `saveMessages()` in `script.js` are the sole read/write path to storage; every mutation (`addMessage`, `deleteMessage`, marking `revealed`) goes through them and then re-renders via `renderMessages()`.

### Render/tick loop

`renderMessages()` rebuilds the entire `#messagesList` DOM from storage (sorted by `unlockAt`) and is called after every mutation. Once rendered, a `setInterval` (`tickAll`, every 1s) updates each capsule's countdown numbers, progress bar, and locked/unlocked state in place without a full re-render — it reads current data from storage on each tick rather than mutating the DOM nodes' captured closures. When a capsule crosses its unlock time, `tickAll` flips it to revealed, persists `revealed: true` back to storage, and triggers the reveal animation/toast exactly once (guarded by comparing `node.dataset.unlocked` against the new state).

When adding new capsule fields or behaviors, this storage → render → tick pattern is the one to follow: mutate storage, then let `renderMessages`/`tickAll` reflect it, rather than mutating rendered DOM state directly.
