# CheerApp — Show Format

A **Show** is the single artifact both platforms render identically from.
Canonical JSON Schema: [`../shared/show.schema.json`](../shared/show.schema.json).

## Example

```json
{
  "showId": "show_2026-08-14_ifa-cup-final",
  "eventId": "event_ifa-cup-final",
  "startAtUtc": "2026-08-14T19:00:00.000Z",
  "assets": [
    { "assetId": "img_logo", "type": "image", "url": "https://cdn.cheerapp.example/shows/.../logo.png" },
    { "assetId": "clip_anthem", "type": "audio", "url": "https://cdn.cheerapp.example/shows/.../anthem.m4a" }
  ],
  "cues": [
    {
      "id": "c1",
      "offsetMs": 1452000,
      "durationMs": 10000,
      "type": "flash",
      "params": { "frequencyHz": 5 },
      "zones": ["ALL"]
    },
    {
      "id": "c2",
      "offsetMs": 1882000,
      "durationMs": 5000,
      "type": "color",
      "params": { "hex": "#FF0000" },
      "zones": ["ALL"]
    },
    {
      "id": "c3",
      "offsetMs": 2100000,
      "durationMs": 6000,
      "type": "image",
      "params": { "assetId": "img_logo" },
      "zones": ["NORTH", "SOUTH"]
    },
    {
      "id": "c4",
      "offsetMs": 2400000,
      "durationMs": 30000,
      "type": "audio",
      "params": { "assetId": "clip_anthem", "volume": 1.0 },
      "zones": ["ALL"]
    }
  ]
}
```

## Field notes

- `offsetMs` — milliseconds from `startAtUtc`. Always relative, never a
  wall-clock time, so an operator delaying the whole show only has to
  change one field (`startAtUtc`) and every cue shifts with it.
- `zones` — list of zone ids, or the literal `"ALL"`. A cue not scoped to
  the viewer's zone is downloaded (for preview/rehearsal tooling) but
  never fires on that device.
- `params` per `type`:
  - `flash` — `{ frequencyHz }`. Renders as camera-torch strobe on iOS,
    full-screen black/white strobe on web (no torch API on the web
    platform — see `docs/ARCHITECTURE.md` §5). Producers should preview
    both renderings before publishing a show.
  - `color` — `{ hex }`. Solid full-screen fill.
  - `image` / `video` — `{ assetId }`, referencing `assets[]` so the
    binary is fetched/cached once and reused across cues.
  - `audio` — `{ assetId, volume }`.
- `assets[]` — every media reference used by any cue, fetched and primed
  by clients before the show starts (`docs/ARCHITECTURE.md` §5,
  `docs/SYNC_DESIGN.md` §5).

## Versioning

`show.schema.json` is `$id`-versioned (`v1`). Backend and both clients
must agree on the schema version they speak; the backend rejects a show
publish that doesn't validate, and clients reject/ignore a show whose
`$schemaVersion` they don't recognize rather than guessing at unknown
cue types.
