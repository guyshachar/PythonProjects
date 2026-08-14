/**
 * Pre-fetches every asset a Show references, verifies integrity, and
 * primes video/audio elements — so cue renderers never touch the
 * network (or a codec's decode pipeline) at fire time. See
 * docs/ARCHITECTURE.md §5 ("Asset pre-fetch") and docs/SYNC_DESIGN.md §5
 * ("Pre-roll") for why this has to happen well before showtime: a
 * stadium's network is exactly the kind of hostile, high-jitter
 * environment a cue can't afford to depend on live.
 *
 * All assets download regardless of the viewer's zone (docs/SHOW_FORMAT.md
 * "Field notes" — a cue not in your zone is still fetched, never fired),
 * so switching zones mid-show — not currently possible, but future-
 * proofing — wouldn't need a fetch at exactly the wrong moment.
 */

const RETRY_ATTEMPTS = 3;
const RETRY_BACKOFF_MS = 500;
const CONCURRENCY = 4; // cap parallel downloads — don't pile onto an already-congested venue network
const PRIME_TIMEOUT_MS = 8000; // don't block the whole show forever on one slow decode

export class AssetIntegrityError extends Error {}

export class AssetStore {
  constructor() {
    this._byId = new Map(); // assetId -> { objectUrl, type, mediaEl? }
  }

  /** @returns {{objectUrl: string, type: string, mediaEl?: HTMLMediaElement}|null} */
  get(assetId) {
    return this._byId.get(assetId) ?? null;
  }

  /**
   * Downloads, integrity-checks, and primes every asset. Throws (and
   * leaves already-fetched entries in place, harmlessly) if any asset
   * can't be fetched or fails its sha256 check after retries — callers
   * should treat that as fatal rather than starting a show some fans
   * can't actually render.
   *
   * @param {{assetId: string, type: string, url: string, sha256?: string}[]} assets
   * @param {(done: number, total: number) => void} [onProgress]
   */
  async preload(assets, onProgress) {
    let done = 0;
    const total = assets.length;
    onProgress?.(done, total);
    if (total === 0) return;

    const queue = [...assets];
    const worker = async () => {
      for (;;) {
        const asset = queue.shift();
        if (!asset) return;
        const entry = await this._fetchWithRetry(asset);
        this._byId.set(asset.assetId, entry);
        done++;
        onProgress?.(done, total);
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, total) }, worker));
  }

  /** Revokes every object URL. Call once the show/session is done with them. */
  clear() {
    for (const entry of this._byId.values()) URL.revokeObjectURL(entry.objectUrl);
    this._byId.clear();
  }

  async _fetchWithRetry(asset) {
    let lastErr;
    for (let attempt = 0; attempt < RETRY_ATTEMPTS; attempt++) {
      try {
        return await this._fetchOne(asset);
      } catch (err) {
        lastErr = err;
        if (attempt < RETRY_ATTEMPTS - 1) {
          await new Promise((resolve) => setTimeout(resolve, RETRY_BACKOFF_MS * (attempt + 1)));
        }
      }
    }
    throw lastErr;
  }

  async _fetchOne(asset) {
    const res = await fetch(asset.url, { cache: "force-cache" });
    if (!res.ok) throw new Error(`asset ${asset.assetId}: HTTP ${res.status} fetching ${asset.url}`);
    const buf = await res.arrayBuffer();

    if (asset.sha256) {
      const actual = await sha256Hex(buf);
      if (actual !== asset.sha256.toLowerCase()) {
        throw new AssetIntegrityError(`asset ${asset.assetId}: sha256 mismatch (got ${actual})`);
      }
    }

    const objectUrl = URL.createObjectURL(new Blob([buf]));

    if (asset.type === "video" || asset.type === "audio") {
      const mediaEl = document.createElement(asset.type);
      mediaEl.preload = "auto";
      mediaEl.playsInline = true; // iOS Safari: inline, not fullscreen-takeover, playback
      mediaEl.src = objectUrl;
      await primeMediaElement(mediaEl);
      return { objectUrl, type: asset.type, mediaEl };
    }

    return { objectUrl, type: asset.type };
  }
}

/** Waits for the element to be decoded enough to play through without
 * stalling (or PRIME_TIMEOUT_MS, whichever first) — the "pre-roll" step
 * SYNC_DESIGN.md §5 calls out as necessary because play()'s own startup
 * latency isn't covered by the clock-offset math. */
function primeMediaElement(el) {
  return new Promise((resolve) => {
    if (el.readyState >= HTMLMediaElement.HAVE_ENOUGH_DATA) {
      resolve();
      return;
    }
    const done = () => {
      el.removeEventListener("canplaythrough", done);
      el.removeEventListener("loadeddata", done); // fallback: some browsers are inconsistent firing canplaythrough for blob: URLs
      clearTimeout(timer);
      resolve();
    };
    el.addEventListener("canplaythrough", done, { once: true });
    el.addEventListener("loadeddata", done, { once: true });
    const timer = setTimeout(done, PRIME_TIMEOUT_MS);
    el.load();
  });
}

async function sha256Hex(buf) {
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
