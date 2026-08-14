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
  `backend/README.md` "Database". Still open: asset upload + CDN, show
  publish/validate against `shared/show.schema.json` (validation itself
  is already wired in `main.py`, asset upload is not).
- Web client: join-by-link/QR flow, QR zone check-in, asset pre-fetch via
  service worker, full Cue Engine (flash-as-strobe, color, image, video,
  audio), "bring to foreground" guard, Wake Lock.
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
