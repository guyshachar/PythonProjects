# CheerApp Web

Browser client for the Time Sync + Cue Engine described in
`../docs/SYNC_DESIGN.md`, now wired to the real backend for join/zone
check-in/show-fetch (see "Try it" below) — not just the standalone
two-cue demo this started as. Plain ES modules, no build step yet; that
will follow `rpPwa/`'s Vite-based conventions once this moves past
prototype, per `../docs/ROADMAP.md` Phase 1.

## Try it

```bash
# terminal 1
cd cheerApp/backend
docker compose up -d db && alembic upgrade head
uvicorn app.main:app --port 5100

# terminal 2 — any static file server
cd cheerApp/web && python -m http.server 8080
```

Create an Event and publish a Show against the running backend (see
`../backend/README.md`'s endpoint table, or just `curl` — there's no
admin UI yet). Then open:

```
http://localhost:8080/?event=<eventId>&qr=<qrToken>
```

`qr` is optional — the QR token printed on a venue zone's physical
signage (`POST /events` returns each zone's `qrToken`); omit it to join
as zone `"ALL"` for testing. The page then: fetches the event, starts
clock sync, resolves your zone via `/checkin` if a QR token was given,
polls `/show` until the producer publishes one, and runs the real
`CueEngine` against it — status text tracks progress through each step.

Open it in several tabs/devices at once (with different `qr` tokens) to
eyeball cross-device sync and per-zone cue scoping.

## Files

- `src/timeSync.js` — SNTP-style offset estimation + periodic resync.
- `src/cueEngine.js` — two-stage cue scheduler + default effect renderers
  (flash-as-strobe, color, image, video/audio) + backgrounding handling.
- `src/apiClient.js` — thin fetch wrapper for the backend's REST contract.
- `src/wakeLock.js` — Screen Wake Lock for the show's duration.
- `src/main.js` — join flow: URL params → event → sync → checkin → show
  → CueEngine, wiring status text and the foreground/Wake Lock guard.

## Known gaps (tracked in `../docs/ROADMAP.md` Phase 1)

- **No asset pre-fetch/CDN yet** — only `flash`/`color` cues render for
  real. `image`/`video`/`audio` cues currently just log a missing-
  renderer warning (no assets to fetch/prime yet).
- **No admin UI** — publishing a show means `curl`-ing the backend
  directly (see `../backend/README.md`).
- **No re-poll after initial show fetch** — if a producer *republishes*
  a show after a fan has already joined and started scheduling against
  the first one, that fan won't pick up the change until they reload.
