# CheerApp

CheerApp turns a stadium or arena crowd into a synchronized digital display.
Every fan's phone becomes one "pixel" in a venue-wide show: flashlights,
screen colors, images, video and audio all fire in lockstep across
thousands of devices, driven by a pre-authored timeline and a
tightly-synchronized clock on every phone.

This folder is a **new, standalone product** inside the PythonProjects
monorepo, alongside `refPortal/`, `scoutCut/`, etc. — it does not share
RefPortal's tenancy, auth, or messaging stack. It follows the repo's
existing convention of one top-level folder per deployable/product.

## Status

Planning + architecture phase. This folder currently contains:
design docs, a data/API contract, a backend skeleton, and prototype
client code for the hardest technical problem (cross-device time sync).
No production infrastructure has been provisioned yet.

## Platforms

| Platform | Timing | Status |
|---|---|---|
| Web (PWA) | MVP | scaffolded — `web/` |
| iOS (native) | Phase 2 | Swift prototypes — `ios/` (real Xcode project TBD, created in Xcode, not by hand) |
| Android (native) | Phase 3 (later, per request) | not started — will mirror `android/`'s existing Kotlin multi-module setup when it starts |

## Folder layout

```
cheerApp/
  docs/            architecture, sync design, show format, location ID, roadmap
  backend/         FastAPI service: events/shows/zones CRUD, time endpoint, live WS control
  web/             browser client prototype (time sync + cue engine + effect rendering)
  ios/             Swift source prototypes for the same engine (torch, screen, media)
  shared/          show.schema.json — the wire format every client & the backend agree on
```

## Read next

Start with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system
overview, then [`docs/SYNC_DESIGN.md`](docs/SYNC_DESIGN.md) for how the
synchronization actually works — that's the part the whole product lives
or dies on.
