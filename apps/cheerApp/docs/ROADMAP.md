# CheerApp — Roadmap

## Phase 0 — Planning (this drop)

- Architecture, sync design, show format, location ID docs.
- Backend skeleton: Events/Shows/Zones models + `/time` endpoint contract.
- Web prototype of the Time Sync + Cue Engine (the highest-risk piece,
  validated first, cheapest platform to iterate on).
- Swift source prototypes mirroring the same design for iOS.

## Phase 1 — Web MVP

- Backend: real persistence — **done**, Postgres via SQLAlchemy + Alembic
  (`backend/app/db.py`, `db_models.py`, `repository.py`); see
  `backend/README.md` "Database". Show publish validates against
  `shared/show.schema.json` **and** cross-checks every cue's `assetId`
  actually exists in `show.assets` (`main.py`'s `publish_show`) — a
  dangling reference is caught at publish time, not discovered live at
  showtime. Still open: real asset upload + CDN — for now producers drop
  files into `backend/assets_store/`, served by a dev-only static mount
  (`main.py`'s `/assets`), not a production pipeline.
- Web client: join-by-link/QR flow, QR zone check-in — **done**
  (`web/src/main.js`, `apiClient.js`). Asset pre-fetch — **done**
  (`web/src/assetStore.js`): every asset is downloaded, sha256-verified,
  and (for video/audio) primed to a ready-to-play `<video>`/`<audio>`
  element before the CueEngine ever starts, so no cue depends on live
  network at fire time (docs/ARCHITECTURE.md §5) — not via a service
  worker as originally planned, a plain in-memory fetch+Blob store
  turned out sufficient for a single-session client. All five cue types
  (flash/color/image/video/audio) render for real now.
  A **"Tap to join the show" gate** blocks starting the engine (not the
  setup work before it) — required because Chrome/Safari refuse
  audio/video autoplay-with-sound without a prior user gesture; this
  wasn't anticipated in the original design and was only caught by
  testing in a real browser (a bare page load, no click, throws
  `NotAllowedError` on the first video/audio cue).
  "Bring to foreground" guard + Wake Lock — **done** (`web/src/wakeLock.js`,
  `CueEngine`'s `onVisibilityChange`).
- Admin console (minimal): author a show as JSON with schema validation
  and a timeline preview; visual drag-and-drop editor is a later
  nice-to-have, not required to run a real show.
- **Exit criterion**: an empty-venue (or living-room, 10+ phones)
  rehearsal measuring actual cross-device fire-time spread for a
  `flash`/`color` show, checked against the ~50ms target in
  `docs/SYNC_DESIGN.md` §4, before any live crowd use.

## Phase 2 — iOS native

- Real Xcode project (created in Xcode, this repo's `ios/` app is a
  useful reference for signing/scheme conventions but is a *separate*
  app — CheerApp ships as its own bundle id, not a RefPortal feature).
- Port `ios/Sources/*.swift` prototypes into the project: `AVCaptureDevice`
  torch control for true flash, `AVAudioEngine` sample-accurate audio,
  `CADisplayLink` fine-scheduling.
- Same backend, same `show.schema.json` — no server changes required to
  add this platform.

## Phase 3 — Beacons + Android

- BLE beacon zone identification (`docs/LOCATION_ID.md`), starting with
  one pilot venue's hardware install.
- Android client mirroring the iOS feature set, following this repo's
  existing `android/` Kotlin multi-module conventions
  (`core-data`/`core-network`/`core-ui`/`app`).

## Phase 4 — Show authoring tools

- Visual timeline editor for producers.
- BPM/beat-aligned cue generation from an uploaded audio track.
- Rehearsal/simulation mode: preview a show against a simulated crowd of
  virtual clients with injected network jitter, to catch sync
  regressions before a live venue does.

## Explicitly out of scope for now

- Android before Phase 3 (per the original request: iOS + web first).
- Any effect type beyond flash/color/image/video/audio.
- Beacon-based zones before QR-only is proven live.
