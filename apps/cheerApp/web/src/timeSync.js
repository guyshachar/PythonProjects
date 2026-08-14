/**
 * SNTP-style clock offset estimation against the CheerApp backend's
 * cheap /time endpoint. See cheerApp/docs/SYNC_DESIGN.md §1-2 for the
 * math and the sampling/filtering rationale — keep this file and
 * ../../ios/Sources/TimeSyncService.swift behavioraly identical.
 */

const SAMPLE_COUNT = 8;
const KEEP_FRACTION = 0.75; // discard worst quarter by round-trip delay

/**
 * @param {string} timeEndpoint e.g. "https://api.cheerapp.example/time"
 * @returns {Promise<{offsetMs: number, confidenceMs: number, sampledAt: number}>}
 */
export async function measureOffset(timeEndpoint) {
  const samples = [];
  for (let i = 0; i < SAMPLE_COUNT; i++) {
    const t0 = Date.now();
    const res = await fetch(timeEndpoint, { cache: "no-store" });
    const t3 = Date.now();
    const { t1, t2 } = await res.json();

    const delay = (t3 - t0) - (t2 - t1); // round-trip minus server processing
    const offset = ((t1 - t0) + (t2 - t3)) / 2;
    samples.push({ delay, offset });
  }

  samples.sort((a, b) => a.delay - b.delay);
  const kept = samples.slice(0, Math.max(1, Math.ceil(samples.length * KEEP_FRACTION)));
  const offsets = kept.map((s) => s.offset).sort((a, b) => a - b);
  const medianOffset = offsets[Math.floor(offsets.length / 2)];

  return {
    offsetMs: medianOffset,
    confidenceMs: kept[0].delay,
    sampledAt: Date.now(),
  };
}

/**
 * Keeps a live offset estimate fresh by resampling on an interval.
 * Call .current() at schedule time to get the latest offset — a
 * mid-wait resync self-corrects any pending cue, per SYNC_DESIGN.md §3.
 */
export class TimeSync {
  /**
   * @param {string} timeEndpoint
   * @param {number} resyncIntervalMs default 60s, per SYNC_DESIGN.md §2
   */
  constructor(timeEndpoint, resyncIntervalMs = 60_000) {
    this.timeEndpoint = timeEndpoint;
    this.resyncIntervalMs = resyncIntervalMs;
    this.offsetMs = null;
    this.confidenceMs = null;
    this._timer = null;
  }

  /** Resolves once the first sample lands; keeps resyncing after. */
  async start() {
    await this._resync();
    this._timer = setInterval(() => this._resync(), this.resyncIntervalMs);
  }

  stop() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  async _resync() {
    try {
      const { offsetMs, confidenceMs } = await measureOffset(this.timeEndpoint);
      this.offsetMs = offsetMs;
      this.confidenceMs = confidenceMs;
    } catch {
      // Keep the previous offset on a failed resync — a stale-but-valid
      // estimate beats none. Caller can inspect confidenceMs/age if it
      // wants to gate on freshness.
    }
  }

  /** True once at least one sample has landed. */
  get isSynced() {
    return this.offsetMs !== null;
  }

  /** Best current estimate of server time, in epoch ms. */
  serverNow() {
    if (this.offsetMs === null) {
      throw new Error("TimeSync: not synced yet — call start() and await its first resolution");
    }
    return Date.now() + this.offsetMs;
  }
}
