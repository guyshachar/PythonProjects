# CheerApp — Time Synchronization Design

This is the part the product lives or dies on: thousands of independent
phones, each with a wrong and drifting clock, need to fire the same
effect within a tight window of each other with no shared trigger signal
at the moment it happens.

## 1. The algorithm (SNTP-style offset estimation)

We don't use raw UDP NTP (port 123 is frequently blocked on carrier/
stadium Wi-Fi networks, and browsers can't speak UDP at all). Instead we
run the same math NTP uses, over an HTTPS round trip to our own
`/time` endpoint, which is cheap to self-host and works everywhere HTTPS
works:

```
client sends request,  timestamp t0 (client clock)
server receives,       timestamp t1 (server clock)   \  server fills
server responds,       timestamp t2 (server clock)   /  both into body
client receives,       timestamp t3 (client clock)

round-trip delay:  δ = (t3 - t0) - (t2 - t1)
clock offset:      θ = ((t1 - t0) + (t2 - t3)) / 2
```

`θ` is how far ahead (or behind) the client's clock is from the server's.
`serverNow = clientNow + θ` at any later instant, as long as neither
clock has drifted meaningfully since the measurement (see §3).

## 2. Getting a reliable sample under network jitter

A single round trip is not trustworthy on a stadium cell network — an
asymmetric or bloated network path skews `θ` by however lopsided the
send/receive delay was. Mitigation, run by every client before a show:

1. Fire **N = 8** requests back to back (small payload, keep-alive
   connection so TCP/TLS setup cost doesn't pollute the RTT).
2. Compute `δ` and `θ` for each sample.
3. **Discard samples above the 25th-percentile RTT** (`δ`) — low-RTT
   samples are the ones where send delay ≈ receive delay, which is the
   assumption the offset formula depends on.
4. Take the **median `θ`** of the surviving samples (median, not mean,
   to reject any remaining single outlier).
5. Record `offsetMs = θ`, `lastSyncAt = clientNow`, `confidenceMs = δ_min`.

This runs: on app open, again right before "join show" is confirmed, and
on a background timer every ~60s while waiting for the show to start
(phone clocks and especially browser `Date.now()` can drift several
ms/minute, more on cheap Android hardware — irrelevant to this app's iOS/
web scope now, but the periodic resync also absorbs iOS clock steps from
NTP-disciplined system clock adjustments).

## 3. Scheduling a cue against the offset

For each cue, the client already knows the absolute target instant in
server time: `targetServerMs = show.startAtUtc + cue.offsetMs`. To fire
it locally: `targetLocalMs = targetServerMs - offsetMs`.

Naively calling `setTimeout(fire, targetLocalMs - Date.now())` is **not
precise enough** — browser/OS timer coalescing, GC pauses, and long
`targetLocalMs - Date.now()` waits (minutes) accumulate drift.
Two-stage scheduling is used instead:

- **Coarse stage** (> 2s out): a normal timer wakes the engine ~1.5s
  before the target, cheap and low-power.
- **Fine stage** (< 1.5s out): switch to a high-resolution polling loop —
  `requestAnimationFrame` on web (~16ms resolution, tied to display
  refresh, which also gives us a real deadline for compositor-synced
  visual cues), `CADisplayLink` on iOS (screen-refresh-locked, ideal for
  strobe timing since flash/color changes are inherently frame-locked
  anyway). The loop busy-checks `serverNow() >= targetServerMs` and fires
  on the first frame that crosses it — this bounds worst-case fire error
  to roughly one display frame (~16ms) plus whatever the offset's
  residual error was, instead of whatever the OS timer scheduler felt
  like giving us.
- Every resync (§2) recomputes `offsetMs`; the fine-stage loop always
  reads the latest value, so a mid-wait resync self-corrects the pending
  schedule rather than requiring cancel/reschedule.

## 4. Budget and expected precision

| Source | Typical contribution |
|---|---|
| SNTP offset estimation (median of 8, low-RTT filtered, stadium 4G/5G) | ±10–40ms |
| Clock drift between resync and showtime (60s resync cadence) | <5ms |
| Fine-stage scheduling loop resolution | ~16ms (one frame) |
| Effect activation latency (torch driver, `CSS`/`Canvas` paint, decoder start) | 0–30ms, effect-dependent |

**Design target: within ~50ms across the crowd for flash/color cues**,
visually a single unified wave rather than a ripple, in the same range
professional stadium LED card-stunt systems target. Audio/video cues are
harder — see §5.

This is a target for the sync *mechanism*; it assumes assets are
pre-fetched and primed per `docs/ARCHITECTURE.md` §5. It has not been
validated against a real venue network yet — the rollout plan in
`docs/ROADMAP.md` includes an empty-stadium sync rehearsal specifically
to measure this before it's trusted for a live show.

## 5. Audio/video is a harder problem than flash/color

Flash and color are near-instant to render once fired. Audio/video are
not: `<video>.play()` / `AVPlayer.play()` have their own internal
start-up latency (buffer priming, hardware decoder spin-up) that varies
device to device and is *not* covered by the offset math above. For v1:

- Pre-roll: call `load()`/prepare the player well before the cue and
  seek to frame 0, so `play()` only has to start an already-primed
  pipeline.
- Where available, use platform APIs that accept a **future host-clock
  start time** rather than "play now" (`AVPlayer.setRate(_:time:)` with a
  `CMTime` host-time anchor on iOS; on web there is no equivalent
  primitive for `<video>`, so the web client compensates by measuring
  each device's own `play()`-to-first-frame latency once (via a silent
  warm-up clip on join) and firing `play()` that much early).
- Audio-only cues use the Web Audio API's `AudioContext.currentTime`
  scheduling (`source.start(when)`) on web, and `AVAudioEngine`'s
  sample-accurate scheduling on iOS — both are far more precise than
  `<audio>`/`AVAudioPlayer.play()` and should be preferred for anything
  audio.
- Video precision is explicitly **not** held to the same ~50ms bar as
  flash/color for v1; it's tracked as a follow-up once the flash/color
  path is validated live.

## 6. Failure modes and fallbacks

- **No sync yet when show starts** (join too late): client shows "still
  syncing" and holds all cues until it has at least one valid sample,
  then catches up by firing any cue whose target instant has already
  passed but is within a small grace window (e.g. 1.5s), and silently
  skipping older ones rather than firing a storm of stale effects.
- **Backgrounded / screen locked**: iOS/Safari will not run the fine
  scheduling loop reliably; the app detects this (visibility change /
  scene phase) and shows a "bring CheerApp to the foreground" prompt
  rather than silently missing cues.
- **Control channel (WS) drops**: has no effect on a show already in
  progress, since the timeline was pre-fetched — only late operator
  overrides (delay/abort) are lost until reconnect.
