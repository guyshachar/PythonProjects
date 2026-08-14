# CheerApp — Location / Zone Identification

Each phone needs to know which **Zone** of the venue it's in, so the Cue
Engine can filter cues scoped to a subset of the crowd (card-stunt style
effects) versus `ALL` (whole-venue effects, which need no zone at all).

## Options

### QR code (v1, MVP)

A printed QR code per zone (section entrance, seat-back, or on a large
static banner visible from the section) encodes a signed zone token
(`zoneId` + short HMAC so a photographed/shared code can't be used to
spoof a different venue's event). User scans once on joining the show;
result is cached locally for the event's duration.

- **Pros**: zero venue hardware, zero ongoing cost, works day one,
  no OS permission beyond camera (already implicitly granted for a QR
  scan UI), trivially testable.
- **Cons**: manual step, wrong-code risk if fans move seats, needs
  physical signage the venue must print and place.
- **Fallback within QR**: a manual zone picker (list/map tap) for anyone
  who can't scan (camera issue, seat has no visible code).

### BLE beacons (Phase 3+)

Fixed iBeacon/Eddystone beacons per zone broadcast `UUID + major(zone) +
minor(subzone)`. App ranges continuously, assigns zone by strongest
non-flickering signal (hysteresis window to avoid rapid reassignment at
zone boundaries).

- **Pros**: automatic, no user action, works without line-of-sight to a
  printed code, can support finer-grained sub-zones.
- **Cons**: venue must purchase/install/maintain beacon hardware; iOS
  requires Core Location + Bluetooth permission (a heavier ask than
  camera-for-QR); RSSI-based zone assignment is noisy in a packed
  stadium (bodies attenuate BLE) and needs real on-site tuning.
- Explicitly **not** in the v1/MVP scope — it's a hardware-dependent
  venue integration, tracked for Phase 3 in `docs/ROADMAP.md` once the
  core sync/cue product is proven with QR alone.

## Decision for v1

QR-only, with a manual picker fallback. This keeps the MVP deployable at
any venue with nothing more than printed signage, and keeps zone
assignment fully decoupled from the sync engine — `docs/SYNC_DESIGN.md`
doesn't care how a zone id was obtained, only that the client has one (or
`ALL`-only shows, which need no zone identification at all and are the
simplest possible v1 demo: a single-section flash-mob effect with no
per-zone scoping).

## Privacy

A zone id is coarse (typically 100s–1000s of people per zone) and is
never combined with any other identity — CheerApp does not require login
for the crowd-facing app; a join is anonymous per-device. This should stay
true through all phases: beacon ranging in Phase 3 must not be paired
with any persistent user identifier beyond the current show session.
