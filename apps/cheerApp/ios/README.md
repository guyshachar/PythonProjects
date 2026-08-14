# CheerApp iOS

Swift source prototypes only — there is no Xcode project here yet. Xcode
projects are generated/maintained through Xcode itself (see how
`../../ios/RefPortal.xcodeproj` was built); hand-authoring a `.pbxproj`
is error-prone and out of scope for this planning drop. Per
`../docs/ROADMAP.md` Phase 2, the real project gets created in Xcode as
its own app (own bundle id — CheerApp is not a RefPortal feature) and
these files get dropped into its target.

These mirror `../web/src/timeSync.js` and `../web/src/cueEngine.js`
behaviorally — same SNTP-style offset algorithm, same two-stage
scheduling — because "synced" only means something if both clients agree
on the algorithm, not just the wire format. See `../docs/SYNC_DESIGN.md`.

## Files

- `Sources/Models.swift` — `Show`/`Cue`/`Zone`/`Asset`, `Decodable` from
  the same `shared/show.schema.json` payload the backend serves.
- `Sources/TimeSyncService.swift` — offset estimation against `/time`,
  periodic resync.
- `Sources/CueEngine.swift` — two-stage scheduler (coarse `Timer`, fine
  `CADisplayLink`) + effect protocol. Includes the one platform
  difference from web: real `AVCaptureDevice` torch control for `flash`
  cues instead of a screen strobe (`../docs/ARCHITECTURE.md` §5).

## Not yet implemented

QR scan check-in, asset pre-fetch/caching, `AVAudioEngine` sample-accurate
audio scheduling (`../docs/SYNC_DESIGN.md` §5), idle-timer/foreground
guard, WS live-control client, the Xcode project itself.
