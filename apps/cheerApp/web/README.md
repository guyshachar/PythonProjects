# CheerApp Web

Prototype browser client for the Time Sync + Cue Engine described in
`../docs/SYNC_DESIGN.md`. Plain ES modules, no build step yet — this is
here to validate the sync algorithm, not to be the final PWA shell (that
will follow `rpPwa/`'s Vite-based conventions once this moves past
prototype, per `../docs/ROADMAP.md` Phase 1).

## Try it

```bash
# terminal 1
cd cheerApp/backend && pip install -r requirements.txt && uvicorn app.main:app --port 5100

# terminal 2 — any static file server
cd cheerApp/web && python -m http.server 8080
```

Open `http://localhost:8080`. It syncs against the local backend's
`/time`, then runs a two-cue demo show (a 5-strobe-per-second flash, then
a red full-screen flash) a few seconds after page load — open it in
several tabs/devices at once to eyeball the sync.

## Files

- `src/timeSync.js` — SNTP-style offset estimation + periodic resync.
- `src/cueEngine.js` — two-stage cue scheduler + default effect renderers
  (flash-as-strobe, color, image, video/audio).
- `src/main.js` — demo wiring (no real join/QR flow yet).

Not yet implemented (tracked in `../docs/ROADMAP.md` Phase 1): join-by-
link/QR zone check-in, service-worker asset pre-fetch, Wake Lock /
foreground guard, admin show authoring.
