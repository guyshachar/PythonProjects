# CheerApp — Architecture

## 1. Concept

An **Event** (a game, a concert) has one **Show**: a timeline of **Cues**.
Each cue says "at time T, for duration D, do effect X" — optionally scoped
to one or more **Zones** of the venue (e.g. "north stand only" for a card
stunt, or `ALL` for a whole-house blackout). Every fan's phone has joined
the event, knows its own zone, has the full show timeline pre-downloaded,
and knows its offset from a shared clock. When wall-clock time crosses a
cue's scheduled instant, every phone in scope fires the effect at (as
close to) the same instant.

There is no live per-cue network dependency during the show — cues are
**pre-authored and pre-fetched**, not streamed. The network is only
needed for: joining the event, downloading the show + assets ahead of
time, periodic clock resync, and an optional low-frequency "control"
channel for last-minute changes (delay the show, abort a cue, insert an
ad-hoc cue). This is deliberate: a stadium with 40,000 phones on 4G/5G is
a hostile, high-jitter network environment, and the sync must survive it.

## 2. Components

```
                      ┌────────────────────┐
                      │   Admin / Producer  │  authors a Show (timeline of Cues)
                      │   console (web)     │  for an Event, publishes it
                      └──────────┬──────────┘
                                 │ REST
                                 ▼
┌───────────────────────────────────────────────────────┐
│                  CheerApp Backend (FastAPI)             │
│  - Events / Shows / Zones CRUD                           │
│  - Asset storage (images/video/audio, CDN-fronted)        │
│  - /time endpoint (HTTPS round-trip time source)          │
│  - WS control channel per event (go-live, abort, delay)   │
│  - Zone check-in (QR scan / beacon report -> zone id)      │
└───────────────────────────────────────────────────────┘
        │ REST (fetch show)     │ WS (control)     │ REST (check-in)
        ▼                       ▼                   ▼
┌────────────────────────────────────────────────────────┐
│                     Client (per phone)                   │
│  1. Zone Identification  — scan QR or range BLE beacons   │
│  2. Show Sync            — download show.json + assets    │
│  3. Time Sync            — NTP-style offset vs. /time      │
│  4. Cue Engine           — schedules & fires cues in scope │
│  5. Effect Renderers     — torch / screen-color / image /  │
│                            video / audio                   │
└────────────────────────────────────────────────────────┘
```

Web and iOS share the same backend contract (`shared/show.schema.json`)
and the same *design* for the Cue Engine and Time Sync — see
`web/src/timeSync.js` / `web/src/cueEngine.js` and
`ios/Sources/TimeSyncService.swift` / `ios/Sources/CueEngine.swift`.
Keeping the algorithm identical across platforms is what makes "synced"
mean the same thing on every phone.

## 3. Data model

- **Event** — a game/concert instance: id, venue, start time, list of zones.
- **Zone** — a venue subdivision: id, human label (e.g. "North Stand"),
  optional beacon UUID/major or QR token that maps to it.
- **Show** — one timeline attached to an Event: `startAtUtc` + ordered `cues`.
- **Cue** — `{ id, offsetMs, durationMs, type, params, zones }`. `offsetMs`
  is relative to the show's `startAtUtc`, so the client computes one
  absolute UTC instant per cue: `startAtUtc + offsetMs`.
- **Cue types (v1)**: `flash` (torch strobe / screen strobe), `color`
  (solid screen fill), `image`, `video`, `audio`.

Full JSON shape: [`shared/show.schema.json`](../shared/show.schema.json),
narrative version: [`docs/SHOW_FORMAT.md`](SHOW_FORMAT.md).

## 4. Why "pre-fetch the whole timeline" instead of "stream cues live"

Streaming a cue over the network at the instant it should fire adds that
network's latency and jitter (tens to thousands of ms on a congested
stadium cell) directly to the sync error. Pre-fetching the full show and
all its media, then scheduling locally against a synced clock, removes
the show-time network entirely from the critical path — the only thing
that has to be accurate at showtime is each phone's clock offset, which
is refreshed *before* the show and doesn't depend on network conditions
*during* it. The WS control channel still exists for operator overrides,
but it is a convenience, not the sync mechanism.

## 5. Cross-cutting concerns

- **Foreground requirement**: iOS suspends background apps and revokes
  torch access when backgrounded; mobile Safari throttles background
  tabs. The app must keep the screen on (`Idle Timer` disabled / Web
  Wake Lock API) and instruct users to keep it open and foregrounded for
  the show — this is a hard platform constraint, not a bug to fix later.
- **Web has no torch/flashlight API.** No browser exposes camera-torch
  control to web pages. On web, `flash` cues render as full-screen
  strobe (white/black) instead of the camera LED. iOS renders true torch
  strobe via `AVCaptureDevice`. This must be visible to producers when
  authoring a show (see `docs/SHOW_FORMAT.md`).
- **Asset pre-fetch**: video/image/audio for a show must be fully
  downloaded and decoded/primed *before* showtime (service worker cache
  on web, local file cache on iOS) — first-frame decode latency at cue
  time would silently desync playback.
- **Privacy**: QR/beacon check-in only ever yields a coarse zone id, not
  precise geolocation. No fine-grained location permission needed for
  QR; BLE ranging requires the OS Bluetooth/location permission prompt
  on both platforms — this is disclosed in-app before requesting it.

## 6. Roadmap pointer

See [`docs/ROADMAP.md`](ROADMAP.md) for phased delivery (Web MVP → iOS →
beacons + Android).
