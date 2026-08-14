/**
 * Screen Wake Lock — keeps the display on for the duration of a show.
 * See docs/ARCHITECTURE.md §5: "the app must keep the screen on ... for
 * the show — this is a hard platform constraint, not a bug to fix later."
 *
 * The OS releases the lock automatically whenever the tab is hidden
 * (screen lock, app switch, ...); this re-acquires it on return so a
 * fan who glances away and back doesn't need to do anything manually.
 * Silently no-ops on browsers without the API (still-usable degraded
 * mode, not a hard failure) — Safari/iOS support is recent and uneven.
 */
export class WakeLockKeeper {
  constructor() {
    this._sentinel = null;
    this._active = false;
    this._visibilityHandler = () => this._onVisibilityChange();
  }

  get isSupported() {
    return "wakeLock" in navigator;
  }

  async start() {
    if (!this.isSupported) return;
    this._active = true;
    document.addEventListener("visibilitychange", this._visibilityHandler);
    await this._acquire();
  }

  stop() {
    this._active = false;
    document.removeEventListener("visibilitychange", this._visibilityHandler);
    this._sentinel?.release().catch(() => {});
    this._sentinel = null;
  }

  async _acquire() {
    try {
      this._sentinel = await navigator.wakeLock.request("screen");
    } catch {
      // Denied (e.g. low battery) or page not visible yet — harmless,
      // _onVisibilityChange retries on the next foreground.
    }
  }

  async _onVisibilityChange() {
    if (this._active && document.visibilityState === "visible" && !this._sentinel) {
      await this._acquire();
    }
  }
}
