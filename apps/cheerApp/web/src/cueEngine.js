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
   * @param {{zoneId: string, renderers: Record<string, (cue: object) => (void|(() => void))>, onVisibilityChange?: (hidden: boolean) => void}} opts
   *   `renderers` may return a cleanup fn to let stop() cut off an in-flight
   *   effect. `onVisibilityChange` fires when the tab is backgrounded/
   *   foregrounded (SYNC_DESIGN.md §6) — wire it to a "bring CheerApp to the
   *   foreground" prompt; the engine itself pauses the fine loop while
   *   hidden and re-evaluates (catch-up or drop) on return.
   */
  constructor(show, timeSync, { zoneId, renderers, onVisibilityChange } = {}) {
    this.startAtMs = Date.parse(show.startAtUtc);
    this.timeSync = timeSync;
    this.zoneId = zoneId;
    this.renderers = renderers;
    this._onVisibilityChange = onVisibilityChange ?? null;

    this.pending = show.cues
      .filter((cue) => cue.zones.includes("ALL") || cue.zones.includes(zoneId))
      .map((cue) => ({ ...cue, targetServerMs: this.startAtMs + cue.offsetMs, fired: false }))
      .sort((a, b) => a.targetServerMs - b.targetServerMs);

    this._coarseTimer = null;
    this._rafHandle = null;
    this._activeEffects = new Set(); // cleanup fns for in-flight renderer effects
    this._visibilityHandler = () => this._handleVisibilityChange();
  }

  /** Begin scheduling. Safe to call once timeSync.isSynced is true. */
  start() {
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", this._visibilityHandler);
    }
    this._scheduleNext();
  }

  stop() {
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", this._visibilityHandler);
    }
    if (this._coarseTimer) clearTimeout(this._coarseTimer);
    if (this._rafHandle) cancelAnimationFrame(this._rafHandle);
    this._coarseTimer = null;
    this._rafHandle = null;
    for (const cancel of this._activeEffects) cancel();
    this._activeEffects.clear();
  }

  /**
   * iOS/Safari won't run the rAF fine loop reliably in the background
   * (SYNC_DESIGN.md §6): drop it while hidden rather than let it silently
   * stall, and re-enter scheduling on return — which fires any cue still
   * within the catch-up grace window and drops the rest, same as the
   * existing late-join path.
   */
  _handleVisibilityChange() {
    const hidden = document.visibilityState === "hidden";
    this._onVisibilityChange?.(hidden);
    if (hidden) {
      if (this._rafHandle) {
        cancelAnimationFrame(this._rafHandle);
        this._rafHandle = null;
      }
    } else {
      this._scheduleNext();
    }
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
    // Renderers may optionally return a cleanup fn so stop() can cut off an
    // in-flight effect (e.g. abort mid-strobe) instead of only cancelling
    // pending schedules. Self-forgotten after the cue's own duration so
    // _activeEffects doesn't grow unbounded over a long show.
    const cancel = renderer(cue);
    if (typeof cancel === "function") {
      this._activeEffects.add(cancel);
      setTimeout(() => this._activeEffects.delete(cancel), (cue.durationMs ?? 0) + 50);
    }
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
    let stopped = false;
    let handle = null;
    const tick = () => {
      on = !on;
      rootEl.style.background = on ? "#ffffff" : "#000000";
      if (!stopped && performance.now() < endAt) {
        handle = setTimeout(tick, periodMs / 2);
      } else {
        rootEl.style.background = "#000000";
      }
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(handle);
      rootEl.style.background = "#000000";
    };
  };
}

export function colorRenderer(rootEl) {
  return (cue) => {
    rootEl.style.background = cue.params.hex;
    const handle = setTimeout(() => {
      rootEl.style.background = "#000000";
    }, cue.durationMs);
    return () => {
      clearTimeout(handle);
      rootEl.style.background = "#000000";
    };
  };
}

export function imageRenderer(rootEl, assetUrlFor) {
  return (cue) => {
    rootEl.style.background = `#000 url(${assetUrlFor(cue.params.assetId)}) center/contain no-repeat`;
    const handle = setTimeout(() => {
      rootEl.style.background = "#000000";
    }, cue.durationMs);
    return () => {
      clearTimeout(handle);
      rootEl.style.background = "#000000";
    };
  };
}

/**
 * Audio cues — headless, no on-screen element. Assumes the <audio> was
 * pre-loaded and primed ahead of showtime (assetStore.js), not fetched
 * here: fetching at fire time is exactly the live network dependency
 * docs/ARCHITECTURE.md §5 rules out.
 */
export function mediaRenderer(mediaElFor) {
  return (cue) => {
    const el = mediaElFor(cue.params.assetId);
    if (!el) return undefined;
    el.currentTime = 0;
    if ("volume" in cue.params) el.volume = cue.params.volume;
    el.play().catch((err) => console.warn("CueEngine: media play() failed", err));
    const handle = setTimeout(() => el.pause(), cue.durationMs);
    return () => {
      clearTimeout(handle);
      el.pause();
    };
  };
}

/**
 * Video cues — same pre-loaded-element assumption as mediaRenderer, plus
 * showing/hiding the (already-in-the-DOM, initially transparent) <video>
 * element itself for the cue's duration.
 */
export function videoRenderer(mediaElFor) {
  return (cue) => {
    const el = mediaElFor(cue.params.assetId);
    if (!el) return undefined;
    el.currentTime = 0;
    if ("volume" in cue.params) el.volume = cue.params.volume;
    el.style.opacity = "1";
    el.play().catch((err) => console.warn("CueEngine: video play() failed", err));
    const hide = () => {
      el.style.opacity = "0";
      el.pause();
    };
    const handle = setTimeout(hide, cue.durationMs);
    return () => {
      clearTimeout(handle);
      hide();
    };
  };
}
