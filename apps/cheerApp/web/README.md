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
polls `/show` until the producer publishes one, downloads and primes
every asset the show references, then waits for a tap ("Tap to join the
show") before running the real `CueEngine` against it — status text
tracks progress through each step. The tap is required, not cosmetic:
browsers refuse to autoplay audio/video with sound before a user
gesture, so without it every video/audio cue would silently fail to
play (see `docs/ARCHITECTURE.md` §5).

To try image/video/audio cues, drop a file into `../backend/assets_store/`
(dev-only static host — see `../backend/README.md` "Assets") and
reference it from a published show's `assets[]`.

Open it in several tabs/devices at once (with different `qr` tokens) to
eyeball cross-device sync and per-zone cue scoping.

## Language (English / Hebrew)

The join-flow UI (status text, the join button, page title) is
bilingual — see `src/i18n.js`. Resolution order: `?lang=en|he` in the
URL (lets a join link force a language) → the user's saved default
(EN/עב buttons top-right, persisted to `localStorage`) → the browser's
own language → English. Hebrew also flips `<html dir>` to `rtl`, which
is what actually reflows the layout (status text alignment, the
switcher swapping sides) — see `applyLangToDocument()`'s comment for why
that one line does most of the work instead of per-element RTL CSS.

Only the flow authored in `main.js` is translated; lower-level
diagnostic errors from `timeSync.js`/`assetStore.js`/`apiClient.js`
(e.g. a sha256 mismatch) stay in English — see `i18n.js`'s header
comment for the reasoning.

## Files

- `src/timeSync.js` — SNTP-style offset estimation + periodic resync.
- `src/cueEngine.js` — two-stage cue scheduler + default effect renderers
  (flash-as-strobe, color, image, video/audio) + backgrounding handling.
- `src/apiClient.js` — thin fetch wrapper for the backend's REST contract.
- `src/assetStore.js` — pre-fetches, sha256-verifies, and primes every
  show asset before the CueEngine starts (docs/ARCHITECTURE.md §5).
- `src/wakeLock.js` — Screen Wake Lock for the show's duration.
- `src/i18n.js` — en/he strings + language detection/persistence/RTL.
- `src/main.js` — join flow: URL params → event → sync → checkin → show
  → asset pre-fetch → tap-to-join gate → CueEngine.

## Known gaps (tracked in `../docs/ROADMAP.md` Phase 1)

- **No real asset upload/CDN** — `backend/assets_store/` is a dev-only
  static host, not production infrastructure.
- **No admin UI** — publishing a show means `curl`-ing the backend
  directly (see `../backend/README.md`).
- **No re-poll after initial show fetch** — if a producer *republishes*
  a show after a fan has already joined and started scheduling against
  the first one, that fan won't pick up the change until they reload.
- **No per-device audio/video latency compensation** — cues fire via a
  plain `play()` at the synced instant; see `docs/SYNC_DESIGN.md` §5's
  "Current web implementation status" for what's still aspirational
  there (warm-up latency measurement, Web Audio API scheduling).
