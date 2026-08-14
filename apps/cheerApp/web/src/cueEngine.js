/**
 * Schedules and fires a Show's cues against a synced clock.
 * See cheerApp/docs/SYNC_DESIGN.md §3 for the two-stage scheduling design
 * this implements, and cheerApp/docs/SHOW_FORMAT.md for the cue shape.
 *
 * Web has no torch/flashlight API (docs/ARCHITECTURE.md §5) — "flash"
 * renders as a full-screen strobe here, not a camera LED.
 */

const COARSE_LEAD_MS = 1500; // switch to the rAF fine loop this far out
const CATCH_UP_GRACE_MS = 1500; // fire a just-missed cue instead of skipping it

export class CueEngine {
  /**
   * @param {{startAtUtc: string, cues: object[]}} show
   * @param {import('./timeSync.js').TimeSync} timeSync
   * @param {{zoneId: string, renderers: Record<string, (cue: object) => void>}} opts
   */
  constructor(show, timeSync, { zoneId, renderers }) {
    this.startAtMs = Date.parse(show.startAtUtc);
    this.timeSync = timeSync;
    this.zoneId = zoneId;
    this.renderers = renderers;

    this.pending = show.cues
      .filter((cue) => cue.zones.includes("ALL") || cue.zones.includes(zoneId))
      .map((cue) => ({ ...cue, targetServerMs: this.startAtMs + cue.offsetMs, fired: false }))
      .sort((a, b) => a.targetServerMs - b.targetServerMs);

    this._coarseTimer = null;
    this._rafHandle = null;
  }

  /** Begin scheduling. Safe to call once timeSync.isSynced is true. */
  start() {
    this._scheduleNext();
  }

  stop() {
    if (this._coarseTimer) clearTimeout(this._coarseTimer);
    if (this._rafHandle) cancelAnimationFrame(this._rafHandle);
    this._coarseTimer = null;
    this._rafHandle = null;
  }

  _nextUnfired() {
    return this.pending.find((c) => !c.fired) ?? null;
  }

  _scheduleNext() {
    const cue = this._nextUnfired();
    if (!cue) return;

    const msUntil = cue.targetServerMs - this.timeSync.serverNow();

    if (msUntil > COARSE_LEAD_MS) {
      // Coarse stage: cheap timer, wakes again closer to the fine window.
      this._coarseTimer = setTimeout(
        () => this._scheduleNext(),
        msUntil - COARSE_LEAD_MS
      );
      return;
    }

    // Already-passed cues beyond the catch-up grace window are dropped
    // silently (SYNC_DESIGN.md §6) rather than firing a stale-effect storm.
    if (msUntil < -CATCH_UP_GRACE_MS) {
      cue.fired = true;
      this._scheduleNext();
      return;
    }

    this._fineLoop();
  }

  _fineLoop() {
    const cue = this._nextUnfired();
    if (!cue) return;

    if (this.timeSync.serverNow() >= cue.targetServerMs) {
      cue.fired = true;
      this._fire(cue);
      this._scheduleNext();
      return;
    }

    this._rafHandle = requestAnimationFrame(() => this._fineLoop());
  }

  _fire(cue) {
    const renderer = this.renderers[cue.type];
    if (!renderer) {
      console.warn(`CueEngine: no renderer registered for cue type "${cue.type}"`, cue);
      return;
    }
    renderer(cue);
  }
}

// --- Default effect renderers ---------------------------------------------
// Registered by main.js; kept here as the reference implementation for the
// web platform's cue -> visible/audible effect mapping.

/** Full-screen strobe standing in for camera torch (no web torch API). */
export function flashRenderer(rootEl) {
  return (cue) => {
    const periodMs = 1000 / cue.params.frequencyHz;
    const endAt = performance.now() + cue.durationMs;
    let on = false;
    const tick = () => {
      on = !on;
      rootEl.style.background = on ? "#ffffff" : "#000000";
      if (performance.now() < endAt) {
        setTimeout(tick, periodMs / 2);
      } else {
        rootEl.style.background = "#000000";
      }
    };
    tick();
  };
}

export function colorRenderer(rootEl) {
  return (cue) => {
    rootEl.style.background = cue.params.hex;
    setTimeout(() => {
      rootEl.style.background = "#000000";
    }, cue.durationMs);
  };
}

export function imageRenderer(rootEl, assetUrlFor) {
  return (cue) => {
    rootEl.style.background = `#000 url(${assetUrlFor(cue.params.assetId)}) center/contain no-repeat`;
    setTimeout(() => {
      rootEl.style.background = "#000000";
    }, cue.durationMs);
  };
}

/** Assumes the <video>/<audio> element was pre-loaded ahead of showtime. */
export function mediaRenderer(mediaElFor) {
  return (cue) => {
    const el = mediaElFor(cue.params.assetId);
    if (!el) return;
    el.currentTime = 0;
    if ("volume" in cue.params) el.volume = cue.params.volume;
    el.play().catch((err) => console.warn("CueEngine: media play() failed", err));
    setTimeout(() => el.pause(), cue.durationMs);
  };
}
